/**
 * MockToolRunner — 用于 BrowserAutomationAdapter 和 CoverageAnalyzer 的 Mock 工厂
 *
 * 设计要点（对齐 TEST_DESIGN_OUTLINE.md §1.1）：
 *   - 每个方法返回 Promise，可配置成功/失败/延迟
 *   - trackCalls 启用时记录每次调用的参数，用于断言调用次数
 *   - 默认 navigate 成功，getSnapshot 返回含 2-3 个节点的标准无障碍树
 *   - 支持 getAllCalls() 统一获取所有调用记录
 *   - 支持每操作独立延迟（override 共享 delayMs）
 *   - 支持交互操作错误模拟
 */

import type {
  BrowserAutomationInput,
  BrowserAutomationSnapshot,
  PlaywrightEvaluateInput,
  PlaywrightEvaluateResult,
  PlaywrightScreenshotInput,
  PlaywrightScreenshotResult,
} from '../../types';

import type { McpToolRunner } from '../../adapter';

/* ===========================================================================
 * Mock 配置接口
 * =========================================================================== */

export interface MockToolRunnerConfig {
  /** navigate: 是否成功（默认 true） */
  navigateSuccess?: boolean;
  navigateError?: string | Error;

  /** getSnapshot: 返回的无障碍树快照 */
  snapshot?: BrowserAutomationSnapshot;
  snapshotError?: string | Error;

  /** getPageHtml: 返回的原始 HTML */
  pageHtml?: string;
  pageHtmlError?: string | Error;

  /** evaluate: JS 注入结果 */
  evaluateResult?: PlaywrightEvaluateResult;
  evaluateError?: string | Error;

  /** screenshot: 截图结果 */
  screenshotResult?: PlaywrightScreenshotResult;
  screenshotError?: string | Error;

  /** 延迟模拟（ms）——所有操作共享的基准延迟 */
  delayMs?: number;

  /** 各操作独立延迟（覆盖共享 delayMs） */
  navigateDelayMs?: number;
  snapshotDelayMs?: number;
  evaluateDelayMs?: number;
  screenshotDelayMs?: number;

  /** 交互操作错误模拟 */
  clickError?: string | Error;
  fillError?: string | Error;
  pressKeyError?: string | Error;

  /** 调用追踪（验证 navigate 调用次数等） */
  trackCalls?: boolean;
}

/* ===========================================================================
 * 默认快照——标准 3 节点无障碍树
 * =========================================================================== */

export const DEFAULT_SNAPSHOT: BrowserAutomationSnapshot = {
  accessibilityTree: {
    name: 'root',
    role: 'RootWebArea',
    children: [
      {
        name: 'Navigation',
        role: 'navigation',
        children: [
          { name: 'Home', role: 'link' },
        ],
      },
      {
        name: 'Main Content',
        role: 'main',
        children: [
          { name: 'Welcome to our site', role: 'heading' },
          {
            name: 'This is a paragraph with enough text content for detection',
            role: 'paragraph',
          },
        ],
      },
    ],
  },
  metadata: { title: 'Test Page', url: 'https://example.com', nodeCount: 6 },
};

/* ===========================================================================
 * 默认 evaluate 结果
 * =========================================================================== */

export const DEFAULT_EVALUATE_RESULT: PlaywrightEvaluateResult = {
  result: 'This is meaningful text content extracted via JS innerText injection for testing purposes.',
  logs: [],
};

/* ===========================================================================
 * 默认截图结果
 * =========================================================================== */

export const DEFAULT_SCREENSHOT_RESULT: PlaywrightScreenshotResult = {
  base64: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==',
  filePath: '/tmp/screenshot.png',
};

/* ===========================================================================
 * 调用记录类型
 * =========================================================================== */

export interface MockCalls {
  navigate: Array<{ url: string }>;
  getSnapshot: Array<{ input: BrowserAutomationInput }>;
  getPageHtml: Array<{ url: string }>;
  evaluate: Array<{ input: PlaywrightEvaluateInput }>;
  screenshot: Array<{ input: PlaywrightScreenshotInput }>;
  click: Array<{ selector: string }>;
  fill: Array<{ selector: string; value: string }>;
  pressKey: Array<{ key: string }>;
}

/* ===========================================================================
 * 核心 Mock 工厂
 * =========================================================================== */

export function createMockRunner(
  config: MockToolRunnerConfig = {},
): { runner: McpToolRunner; calls: MockCalls } {
  const calls: MockCalls = {
    navigate: [],
    getSnapshot: [],
    getPageHtml: [],
    evaluate: [],
    screenshot: [],
    click: [],
    fill: [],
    pressKey: [],
  };

  const shouldTrack = config.trackCalls ?? false;

  /**
   * 延迟辅助——根据等效延迟毫秒数等待
   */
  function delay(ms: number | undefined): Promise<void> {
    if (ms && ms > 0) {
      // eslint-disable-next-line no-restricted-properties
      return new Promise(resolve => setTimeout(resolve, ms));
    }
    return Promise.resolve();
  }

  /**
   * 获取操作的实际延迟：优先操作独占延迟，退回到共享 delayMs
   */
  function getEffectiveDelay(
    operationDelayMs: number | undefined,
  ): number | undefined {
    return operationDelayMs ?? config.delayMs;
  }

  /**
   * 根据成功/错误配置生成返回或拒绝
   */
  function outcome<T>(
    success: boolean | undefined,
    successVal: T,
    delayMs?: number,
    errorVal?: string | Error,
  ): Promise<T> {
    if (success === false) {
      const err = errorVal ?? new Error('Mock: operation failed');
      return delay(delayMs).then(() => {
        throw typeof err === 'string' ? new Error(err) : err;
      });
    }
    return delay(delayMs).then(() => successVal);
  }

  /**
   * 解析操作延迟并执行 outcome
   */
  function outcomeWithDelay<T>(
    success: boolean | undefined,
    successVal: T,
    operationDelayMs: number | undefined,
    errorVal?: string | Error,
  ): Promise<T> {
    return outcome(success, successVal, getEffectiveDelay(operationDelayMs), errorVal);
  }

  const runner: McpToolRunner = {
    async navigate(url: string): Promise<void> {
      if (shouldTrack) calls.navigate.push({ url });
      const hasError = !!config.navigateError;
      return outcomeWithDelay(
        hasError ? false : (config.navigateSuccess ?? true),
        undefined,
        config.navigateDelayMs,
        config.navigateError,
      ) as Promise<void>;
    },

    async getSnapshot(input: BrowserAutomationInput): Promise<BrowserAutomationSnapshot> {
      if (shouldTrack) calls.getSnapshot.push({ input });
      // getSnapshot 独立于 navigate——adapter 只有在 navigate 成功后才会调用 getSnapshot
      const snapSuccess = config.snapshotError ? false : true;
      return outcomeWithDelay(
        snapSuccess,
        config.snapshot ?? DEFAULT_SNAPSHOT,
        config.snapshotDelayMs,
        config.snapshotError,
      );
    },

    async getPageHtml(url: string): Promise<string> {
      if (shouldTrack) calls.getPageHtml.push({ url });
      if (config.pageHtmlError) {
        const err = typeof config.pageHtmlError === 'string'
          ? new Error(config.pageHtmlError)
          : config.pageHtmlError;
        return delay(getEffectiveDelay(undefined)).then(() => { throw err; });
      }
      return delay(getEffectiveDelay(undefined)).then(() => config.pageHtml ?? '');
    },

    async evaluate(input: PlaywrightEvaluateInput): Promise<PlaywrightEvaluateResult> {
      if (shouldTrack) calls.evaluate.push({ input });
      return outcomeWithDelay(
        config.evaluateError ? false : true,
        config.evaluateResult ?? DEFAULT_EVALUATE_RESULT,
        config.evaluateDelayMs,
        config.evaluateError,
      );
    },

    async screenshot(input: PlaywrightScreenshotInput): Promise<PlaywrightScreenshotResult> {
      if (shouldTrack) calls.screenshot.push({ input });
      return outcomeWithDelay(
        config.screenshotError ? false : true,
        config.screenshotResult ?? DEFAULT_SCREENSHOT_RESULT,
        config.screenshotDelayMs,
        config.screenshotError,
      );
    },

    async click(selector: string): Promise<void> {
      if (shouldTrack) calls.click.push({ selector });
      if (config.clickError) {
        const err = typeof config.clickError === 'string'
          ? new Error(config.clickError)
          : config.clickError;
        return Promise.reject(err);
      }
      return Promise.resolve();
    },

    async fill(input: { selector: string; value: string }): Promise<void> {
      if (shouldTrack) calls.fill.push({ selector: input.selector, value: input.value });
      if (config.fillError) {
        const err = typeof config.fillError === 'string'
          ? new Error(config.fillError)
          : config.fillError;
        return Promise.reject(err);
      }
      return Promise.resolve();
    },

    async pressKey(key: string): Promise<void> {
      if (shouldTrack) calls.pressKey.push({ key });
      if (config.pressKeyError) {
        const err = typeof config.pressKeyError === 'string'
          ? new Error(config.pressKeyError)
          : config.pressKeyError;
        return Promise.reject(err);
      }
      return Promise.resolve();
    },
  };

  return { runner, calls };
}

/* ===========================================================================
 * 辅助工具——构造特定场景的快照
 * =========================================================================== */

/**
 * 生成指定数量的无障碍树节点（用于覆盖率测试）
 */
export function makeSnapshotWithNodeCount(
  count: number,
  overrides?: Partial<BrowserAutomationSnapshot>,
): BrowserAutomationSnapshot {
  const children: any[] = [];
  for (let i = 0; i < count; i++) {
    children.push({
      name: `Node ${i}`,
      role: i % 2 === 0 ? 'button' : 'heading',
    });
  }

  return {
    accessibilityTree: {
      name: 'root',
      role: 'RootWebArea',
      children: children.length > 0 ? children : undefined,
    },
    metadata: {
      title: 'Test Page',
      url: 'https://example.com',
      nodeCount: count,
    },
    ...overrides,
  };
}

/**
 * 生成含隐藏元素的无障碍树
 */
export function makeSnapshotWithHidden(
  visibleCount: number,
  hiddenCount: number,
): BrowserAutomationSnapshot {
  const children: any[] = [];

  for (let i = 0; i < visibleCount; i++) {
    children.push({ name: `Visible ${i}`, role: 'button' });
  }

  for (let i = 0; i < hiddenCount; i++) {
    children.push({
      name: `Hidden ${i}`,
      role: 'presentation',
      'aria-hidden': true,
    });
  }

  return {
    accessibilityTree: {
      name: 'root',
      role: 'RootWebArea',
      children,
    },
    metadata: {
      title: 'Test Page',
      url: 'https://example.com',
      nodeCount: visibleCount + hiddenCount,
    },
  };
}

/**
 * 生成含文本内容的无障碍树
 */
export function makeSnapshotWithText(
  texts: string[],
): BrowserAutomationSnapshot {
  const children = texts.map((text, i) => ({
    name: text,
    role: i === 0 ? 'heading' : 'paragraph',
  }));

  return {
    accessibilityTree: {
      name: 'root',
      role: 'RootWebArea',
      children,
    },
    metadata: {
      title: 'Test Page',
      url: 'https://example.com',
      nodeCount: children.length,
    },
  };
}

/**
 * 生成空无障碍树（tree = null）
 */
export const EMPTY_SNAPSHOT: BrowserAutomationSnapshot = {
  accessibilityTree: null,
  metadata: { title: '', url: '', nodeCount: 0 },
};

/**
 * 生成只有根节点、没有 children 键的无障碍树
 */
export const ROOT_ONLY_SNAPSHOT: BrowserAutomationSnapshot = {
  accessibilityTree: { name: 'root', role: 'RootWebArea' },
  metadata: { title: 'Root Only', url: 'https://example.com', nodeCount: 0 },
};

/**
 * 生成大量 DOM 标签的 HTML 字符串（用于覆盖率测试中拉低覆盖率）
 * @param count 标签数量
 * @returns HTML 字符串
 */
export function makeHtmlWithTagCount(count: number): string {
  let html = '<html><body>';
  for (let i = 0; i < count; i++) {
    html += `<div id="elem-${i}">content</div>`;
  }
  html += '</body></html>';
  return html;
}

/**
 * 生成含反爬特征的 HTML 字符串
 */
export function makeAntiCrawlHtml(signature: string): string {
  return `<html><head><title>Test</title></head><body>
    <div class="content">
      <p>${signature}</p>
    </div>
  </body></html>`;
}

/**
 * 生成 SPA Loading 占位符 HTML
 */
export function makeSpaLoadingHtml(loadingText: string): string {
  return `<html><head><title>Loading...</title></head><body>
    <div id="app">
      <div class="spinner">
        <p>${loadingText}</p>
      </div>
    </div>
  </body></html>`;
}