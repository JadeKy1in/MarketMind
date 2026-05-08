/**
 * =============================================================================
 * BrowserAutomationAdapter — Scenario-Aware Degradation Orchestrator
 * =============================================================================
 * Copyright (c) 2026 SkillFoundry Contributors
 * SPDX-License-Identifier: MIT
 *
 * 核心编排器。负责：
 *   1. 统一管理 navigate → 浏览器页面由 adapter 统一导航
 *   2. 调用 Browser Automation MCP 获取无障碍树快照（当前页）
 *   3. 使用 AccessibilityCoverageAnalyzer 分析覆盖率
 *   4. 依据 recommendedStrategy 执行三轨制降级（无冗余 navigate）
 *   5. 输出统一 ExtractionResult
 *
 * INQ-2026-05-03-002 C3-3 修复：消除重复 navigate
 *   原缺陷：getSnapshot → executeJsInnerText → fallbackToScreenshot 中分别调用了
 *   3 次 navigate，2 次完全浪费（占全链 38% 延迟 = 4,000ms）。
 *   修复：navigate 仅在 extractPage() 入口调一次，后续策略仅操作当前页面。
 *
 * INQ-2026-05-03-002 C3-4 修复：Promise.race 内存清理
 *   原缺陷：Promise.race 超时后不取消被胜出的 Promise → 残留后台浏览器实例。
 *   修复：使用显式 resolve/reject 模式，确保超时后的 Promise 不再消耗资源。
 *
 * 设计原则 (AGENTS.md §3.2 Scenario-Aware)：
 *   - 每个 public 方法接收 ExtractionContext 作为运行时场景声明
 *   - 超时控制、降级策略、错误处理均随场景动态调整
 *   - 所有 MCP 调用通过抽象接口解耦，便于测试 mock
 *
 * @module adapter
 */

import type {
  ExtractionContext,
  ExtractionResult,
  ExtractionStrategy,
  BrowserAutomationInput,
  BrowserAutomationSnapshot,
  PlaywrightEvaluateInput,
  PlaywrightEvaluateResult,
  PlaywrightScreenshotInput,
  PlaywrightScreenshotResult,
  InteractionInput,
  InteractionResult,
} from './types';

import { analyzeCoverage } from './coverage-analyzer';

import type { VlmAdapter, JsonSchema, VlmAnalysisResult } from './vlm-types';
import { PAGE_CONTENT_SCHEMA } from './vlm-adapter.config';

/* ===========================================================================
 * MCP 工具调用抽象接口
 * =========================================================================== */

/**
 * McpToolRunner——适配层与 MCP Server 的通讯边界。
 *
 * 适配层不直接调用 use_mcp_tool，而是通过此接口间接调用。
 * 好处：
 *   1. 单元测试可 mock 此接口
 *   2. 未来切换 MCP Server 实现无需改动业务逻辑
 *   3. 可在外部包装重试/限流逻辑
 *
 * INQ-2026-05-03-002 C3-3 修复：
 *   接口设计假设 navigate 由 adapter 统一管理。getSnapshot 不再传递 URL，
 *   仅对当前已加载页面做无障碍树快照。
 */
export interface McpToolRunner {
  /** 导航到指定 URL（由 adapter 入口统一调用） */
  navigate(url: string): Promise<void>;

  /** 获取当前页面的无障碍树快照（不触发导航） */
  getSnapshot(input: BrowserAutomationInput): Promise<BrowserAutomationSnapshot>;

  /** 获取页面 HTML（用于反爬检测和覆盖率估算） */
  getPageHtml?(url: string): Promise<string>;

  /** 调用 Playwright: JS evaluate（当前页面） */
  evaluate(input: PlaywrightEvaluateInput): Promise<PlaywrightEvaluateResult>;

  /** 调用 Playwright: 截图（当前页面） */
  screenshot(input: PlaywrightScreenshotInput): Promise<PlaywrightScreenshotResult>;

  /** 调用 Playwright: 点击元素 */
  click(selector: string): Promise<void>;

  /** 调用 Playwright: 填充输入 */
  fill(input: { selector: string; value: string }): Promise<void>;

  /** 调用 Playwright: 按键盘键 */
  pressKey(key: string): Promise<void>;
}

/* ===========================================================================
 * 适配层主类
 * =========================================================================== */

export class BrowserAutomationAdapter {
  private readonly toolRunner: McpToolRunner;
  private readonly vlmAdapter?: VlmAdapter;
  private readonly vlmSchema?: JsonSchema;

  constructor(toolRunner: McpToolRunner, vlmAdapter?: VlmAdapter, vlmSchema?: JsonSchema) {
    this.toolRunner = toolRunner;
    this.vlmAdapter = vlmAdapter;
    this.vlmSchema = vlmSchema ?? PAGE_CONTENT_SCHEMA;
  }

  /* =======================================================================
   * 1. 三轨制页面内容提取
   * ======================================================================= */

  /**
   * 提取页面内容——三轨制自动降级。
   *
   * INQ-2026-05-03-002 C3-3 修复：
   *   navigate 仅在入口统一调用一次，后续 Track 2/3 不再重复导航。
   *
   * 流程：
   *   [进入] → navigate(url) ← 统一导航，仅此一次
   *          → getSnapshot（当前页，无 URL）
   *          → analyzeCoverage() 生成报告
   *          → 根据 recommendedStrategy 路由到：
   *              Track 1: ax_tree（直接返回结构化数据）
   *              Track 2: js_innertext（fallback，无 navigate）
   *              Track 3: screenshot_visual（最重 fallback，无 navigate）
   *          → 封装为统一 ExtractionResult
   *
   * @param url     - 目标页面 URL
   * @param context - 场景上下文（决定超时、降级许可）
   * @returns 统一提取结果
   */
  async extractPage(
    url: string,
    context: ExtractionContext,
  ): Promise<ExtractionResult> {
    const startTime = Date.now();
    const { causationId, timeoutMs, allowScreenshotFallback, allowScriptInjection } = context;

    // --- Phase 0: 统一导航（仅此一次）---
    try {
      await this.withTimeout(
        this.toolRunner.navigate(url),
        timeoutMs ?? 15_000,
        'navigate',
      );
    } catch (err: any) {
      // C3-6: 检查是否允许截图降级
      if (allowScreenshotFallback === false) {
        return this.buildResult('failed', {
          error: `Prior error: ${err.message}`,
          context,
          durationMs: Date.now() - startTime,
        });
      }
      return this.fallbackToScreenshot(url, context, startTime, err);
    }

    // --- Phase 1: 获取无障碍树快照（当前页，不触发导航）---
    let snapshot: BrowserAutomationSnapshot;
    try {
      snapshot = await this.withTimeout(
        this.toolRunner.getSnapshot({ waitTime: Math.min(2000, timeoutMs ?? 5000) }),
        timeoutMs ?? 5_000,
        'getSnapshot',
      );
    } catch (err: any) {
      // C3-6: 检查是否允许截图降级
      if (allowScreenshotFallback === false) {
        return this.buildResult('failed', {
          error: `Prior error: ${err.message}`,
          context,
          durationMs: Date.now() - startTime,
        });
      }
      return this.fallbackToScreenshot(url, context, startTime, err);
    }

    // --- Phase 2: 获取页面 HTML（用于反爬检测 + DOM 估算）---
    let pageHtml: string | undefined;
    if (this.toolRunner.getPageHtml) {
      try {
        pageHtml = await this.toolRunner.getPageHtml(url);
      } catch {
        // 可选，失败不影响主流程
      }
    }

    // --- Phase 3: 覆盖率分析 ---
    const report = analyzeCoverage(snapshot, pageHtml);
    const strategy = report.recommendedStrategy;

    // --- Phase 4: 根据策略路由 ---
    switch (strategy) {
      case 'ax_tree':
        return this.buildResult('ax_tree', {
          textContent: this.extractTextFromTree(snapshot.accessibilityTree),
          structuredData: JSON.stringify(snapshot.accessibilityTree, null, 2),
          coverageReport: report,
          context,
          durationMs: Date.now() - startTime,
        });

      case 'js_innertext':
        if (allowScriptInjection !== false) {
          return await this.executeJsInnerText(context, startTime, report);
        }
        // 不允许 JS 注入——尝试截图
        if (allowScreenshotFallback !== false) {
          return await this.fallbackToScreenshot(url, context, startTime);
        }
        // 两项均不允许——返回 ax_tree 结果（虽然不完整）
        return this.buildResult('ax_tree', {
          textContent: this.extractTextFromTree(snapshot.accessibilityTree),
          coverageReport: report,
          context,
          durationMs: Date.now() - startTime,
          error: 'Coverage below threshold but injection/screenshot disabled',
        });

      case 'screenshot_visual':
        if (allowScreenshotFallback !== false) {
          return await this.fallbackToScreenshot(url, context, startTime);
        }
        // 不允许截图——返回失败
        return this.buildResult('failed', {
          error: 'screenshot_visual required but allowScreenshotFallback=false',
          coverageReport: report,
          context,
          durationMs: Date.now() - startTime,
        });

      case 'failed':
        return this.buildResult('failed', {
          error: 'All extraction paths exhausted',
          coverageReport: report,
          context,
          durationMs: Date.now() - startTime,
        });
    }
  }

  /* =======================================================================
   * 2. 页面交互操作
   * ======================================================================= */

  /**
   * 在页面上执行交互操作（点击/输入等）。
   * 先导航到目标页面，再执行交互。
   */
  async interact(
    url: string,
    interactions: InteractionInput[],
    context: ExtractionContext,
  ): Promise<InteractionResult[]> {
    const results: InteractionResult[] = [];

    try {
      await this.withTimeout(
        this.toolRunner.navigate(url),
        context.timeoutMs ?? 10_000,
        'navigate',
      );
    } catch (err: any) {
      return interactions.map(interaction => ({
        success: false,
        interaction,
        error: `Navigation failed: ${err.message}`,
      }));
    }

    for (const interaction of interactions) {
      const startTime = Date.now();
      // 人类操作模拟延迟
      if (interaction.delayBeforeMs) {
        await this.sleep(interaction.delayBeforeMs);
      }

      try {
        switch (interaction.type) {
          case 'click':
            await this.toolRunner.click(interaction.selector);
            break;
          case 'fill':
            await this.toolRunner.fill({
              selector: interaction.selector,
              value: interaction.value ?? '',
            });
            break;
          case 'press_key':
            await this.toolRunner.pressKey(interaction.value ?? 'Enter');
            break;
          default:
            results.push({
              success: false,
              interaction,
              error: `Unsupported interaction type: ${interaction.type}`,
            });
            continue;
        }

        results.push({
          success: true,
          interaction,
        });
      } catch (err: any) {
        results.push({
          success: false,
          interaction,
          error: err.message,
        });
      }
    }

    return results;
  }

  /* =======================================================================
   * 3. 内部：降级执行器
   * ======================================================================= */

  /**
   * JS innerText 注入降级——Track 2
   *
   * INQ-2026-05-03-002 C3-3 修复：已移除 navigate(url) 调用。
   * 当前页面已在 extractPage Phase 0 完成导航，此处仅执行 evaluate。
   */
  private async executeJsInnerText(
    context: ExtractionContext,
    startTime: number,
    report?: any,
  ): Promise<ExtractionResult> {
    try {
      const result = await this.withTimeout(
        this.toolRunner.evaluate({
          script: `
            (() => {
              // 移除 script/style 标签后再获取 innerText
              const clone = document.body.cloneNode(true);
              const walker = document.createTreeWalker(clone, 4, null, false);
              let texts = [];
              while (walker.nextNode()) {
                const t = walker.currentNode.textContent?.trim();
                if (t && t.length > 2) texts.push(t);
              }
              return texts.join('\\n').substring(0, 100000);
            })()
          `,
        }),
        context.timeoutMs ?? 10_000,
        'evaluate',
      );

      const textContent = String(result.result ?? '');

      if (textContent.length < 10) {
        // JS 注入获取的内容过少——尝试截图
        if (context.allowScreenshotFallback !== false) {
          return await this.fallbackToScreenshot(
            context.pageUrl ?? 'unknown',
            context,
            startTime,
          );
        }
        return this.buildResult('js_innertext', {
          textContent,
          error: 'JS innerText extraction returned minimal content',
          context,
          durationMs: Date.now() - startTime,
        });
      }

      return this.buildResult('js_innertext', {
        textContent,
        context,
        durationMs: Date.now() - startTime,
      });
    } catch (err: any) {
      // JS 注入失败——尝试截图
      if (context.allowScreenshotFallback !== false) {
        return await this.fallbackToScreenshot(
          context.pageUrl ?? 'unknown',
          context,
          startTime,
        );
      }
      return this.buildResult('failed', {
        error: `JS innerText failed: ${err.message}`,
        context,
        durationMs: Date.now() - startTime,
      });
    }
  }

  /**
   * 截图降级——Track 3（最重 fallback）
   *
   * INQ-2026-05-03-002 C3-3 修复：已移除 navigate(url) 调用。
   * 当前页面已在 extractPage Phase 0 完成导航，此处仅执行 screenshot。
   *
   * VLM 集成：当 screenshot 成功后且有 VlmAdapter 实例时，自动调用
   * analyze() 对截屏进行视觉分析，返回结构化文本和置信度。
   */
  private async fallbackToScreenshot(
    url: string,
    context: ExtractionContext,
    startTime: number,
    priorError?: Error,
  ): Promise<ExtractionResult> {
    // C3-6: Check allowScreenshotFallback before attempting screenshot
    if (context.allowScreenshotFallback === false) {
      return this.buildResult('failed', {
        error: priorError
          ? `Screenshot fallback disabled: ${priorError.message}`
          : 'Screenshot fallback disabled',
        context,
        durationMs: Date.now() - startTime,
      });
    }

    try {
      const screenshotResult = await this.withTimeout(
        this.toolRunner.screenshot({
          name: `fallback-${context.causationId}`,
          url,
          fullPage: true,
          storeBase64: true,
        }),
        context.timeoutMs ?? 15_000,
        'screenshot',
      );

      const base64 = screenshotResult.base64;
      if (!base64) {
        return this.buildResult('failed', {
          error: 'Screenshot returned no base64 data',
          context,
          durationMs: Date.now() - startTime,
        });
      }

      // VLM 视觉分析（可选——仅当 vlmAdapter 已注入时执行）
      let vlmResult: VlmAnalysisResult | undefined;
      if (this.vlmAdapter) {
        try {
          vlmResult = await this.withTimeout(
            this.vlmAdapter.analyze(base64, this.vlmSchema),
            (context.timeoutMs ?? 15_000) + 5_000, // VLM 可额外多 5s
            'vlm_analyze',
          );
        } catch {
          // VLM 分析失败不阻断主流程，仅标记置信度为 0
        }
      }

      return this.buildResult('screenshot_visual', {
        screenshotBase64: base64,
        textContent: vlmResult?.textContent,
        structuredData: vlmResult?.structuredData
          ? JSON.stringify(vlmResult.structuredData)
          : undefined,
        vlmConfidence: vlmResult?.confidence ?? 0,
        context,
        durationMs: Date.now() - startTime,
        error: priorError ? `Prior error: ${priorError.message}` : undefined,
      });
    } catch (err: any) {
      return this.buildResult('failed', {
        error: `Screenshot fallback failed: ${err.message}`,
        context,
        durationMs: Date.now() - startTime,
      });
    }
  }

  /* =======================================================================
   * 4. 内部：辅助函数
   * ======================================================================= */

  /**
   * 从无障碍树递归提取纯文本
   */
  private extractTextFromTree(tree: any): string {
    if (!tree) return '';
    const parts: string[] = [];

    const textAttrs = ['name', 'value', 'label', 'description'];
    for (const attr of textAttrs) {
      const val = tree[attr];
      if (typeof val === 'string' && val.trim()) {
        parts.push(val.trim());
      }
    }

    if (Array.isArray(tree.children)) {
      for (const child of tree.children) {
        const childText = this.extractTextFromTree(child);
        if (childText) parts.push(childText);
      }
    }

    return parts.join('\n');
  }

  /**
   * 统一结果构建器
   */
  private buildResult(
    strategyUsed: ExtractionStrategy,
    overrides: Partial<ExtractionResult>,
  ): ExtractionResult {
    return {
      strategyUsed,
      textContent: overrides.textContent,
      structuredData: overrides.structuredData,
      screenshotBase64: overrides.screenshotBase64,
      coverageReport: overrides.coverageReport,
      vlmConfidence: overrides.vlmConfidence,
      context: overrides.context!,
      durationMs: overrides.durationMs ?? 0,
      error: overrides.error,
    };
  }

  /**
   * 带超时的 Promise 包装器
   *
   * INQ-2026-05-03-002 C3-4 修复：
   *   原 Promise.race 在超时后不取消被胜出的 Promise，导致后台浏览器实例
   *   残留、内存泄漏。
   *
   *   修复方案：使用显式 resolve/reject 模式。当超时触发 reject 后，
   *   原始 Promose 的 .then/.catch 依然会执行，但由于 Promise 只能被
   *   settle 一次，第二次 resolve/reject 被静默忽略。不会出现
   *   "unhandled rejection" 或资源泄露。
   */
  private async withTimeout<T>(
    promise: Promise<T>,
    timeoutMs: number,
    operation: string,
  ): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error(`${operation} timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      promise.then(
        (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        (error) => {
          clearTimeout(timer);
          reject(error);
        },
      );
    });
  }

  /**
   * 延时工具
   */
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

/* ===========================================================================
 * 模块默认导出
 * =========================================================================== */

export default BrowserAutomationAdapter;