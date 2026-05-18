/**
 * =============================================================================
 * BrowserAutomationAdapter 集成测试
 * =============================================================================
 *
 * 对齐 TEST_DESIGN_OUTLINE.md §3-5 的全部测试用例。
 *
 * 执行顺序：
 *   §3.1 Track 1 — ax_tree 正常路径     (AD-01~AD-03)
 *   §3.2 Track 2 — js_innertext 降级     (AD-04~AD-08)
 *   §3.3 Track 3 — screenshot_visual     (AD-09~AD-13)
 *   §3.4 C3-3 导航单次调用验证            (AD-14~AD-17)
 *   §3.5 C3-4 安全超时验证                (AD-18~AD-22)
 *   §3.6 场景感知超时测试                (SC-01~SC-03)
 *   §4  交互操作测试                     (INT-01~INT-07)
 *   §5  边界与极端情况                   (EDGE-01~EDGE-08)
 */

import { BrowserAutomationAdapter } from '../adapter';
import { createDefaultContext, type ExtractionContext, type BrowserAutomationSnapshot } from '../types';
import {
  createMockRunner,
  DEFAULT_SNAPSHOT,
  DEFAULT_EVALUATE_RESULT,
  DEFAULT_SCREENSHOT_RESULT,
  EMPTY_SNAPSHOT,
  ROOT_ONLY_SNAPSHOT,
  makeSnapshotWithNodeCount,
  makeSnapshotWithText,
  makeHtmlWithTagCount,
  makeAntiCrawlHtml,
} from './helpers/mockToolRunner';

/* ===========================================================================
 * Helper: 创建上下文
 * =========================================================================== */

function context(overrides?: Partial<ExtractionContext>): ExtractionContext {
  return {
    ...createDefaultContext('offline_batch_sync'),
    ...overrides,
  };
}

/* ===========================================================================
 * 辅助: 等待 n 毫秒
 * =========================================================================== */
function wait(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/* ===========================================================================
 * 测试套件
 * =========================================================================== */

describe('BrowserAutomationAdapter — Phase 3: 集成测试', () => {
  /* ======================================================================
   * §3.1 Track 1 — ax_tree 正常路径
   * ====================================================================== */

  describe('§3.1 Track 1 — ax_tree 正常路径', () => {
    // AD-01: 标准提取 — 无障碍树全覆盖
    it('AD-01: 标准提取 — ax_tree 全覆盖路径', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('ax_tree');
      expect(result.structuredData).toBeDefined();
      expect(result.structuredData).toContain('root');
      expect(result.textContent).toBeDefined();
      expect(result.textContent).toContain('Welcome to our site');
      expect(calls.navigate).toHaveLength(1);
      expect(calls.navigate[0].url).toBe('https://example.com');
      expect(calls.getSnapshot).toHaveLength(1);
    });

    // AD-02: getPageHtml 可选失败 — 忽略错误
    it('AD-02: getPageHtml 可选失败应忽略', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        pageHtmlError: 'Network error fetching HTML',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      // 即使 getPageHtml 失败，仍正常返回 ax_tree
      expect(result.strategyUsed).toBe('ax_tree');
      expect(calls.navigate).toHaveLength(1);
      expect(calls.getSnapshot).toHaveLength(1);
    });

    // AD-03: causationId 传递验证
    it('AD-03: causationId 应正确传递', async () => {
      const { runner } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      const ctx = context({ causationId: 'test-causation-123' });
      const result = await adapter.extractPage('https://example.com', ctx);

      expect(result.context.causationId).toBe('test-causation-123');
    });
  });

  /* ======================================================================
   * §3.2 Track 2 — js_innertext 降级路径
   * ====================================================================== */

  describe('§3.2 Track 2 — js_innertext 降级路径', () => {
    // AD-04: 覆盖率不足 — JS 注入成功
    it('AD-04: 覆盖率不足时触发 JS innerText 注入', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        // 覆盖率低: 1 个无障碍节点 + 50 个 DOM 标签 => 1/50 = 0.02 < 0.6
        snapshot: makeSnapshotWithText(['This is long text content for detection purposes']),
        pageHtml: makeHtmlWithTagCount(50),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('js_innertext');
      expect(result.textContent).toBeDefined();
      expect(result.textContent!.length).toBeGreaterThan(0);
      // C3-3 验证：navigate 仅 1 次
      expect(calls.navigate).toHaveLength(1);
    });

    // AD-05: evaluate 失败 — 降级到 screenshot
    it('AD-05: evaluate 失败时降级到 screenshot', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['Long content for detection']),
        pageHtml: makeHtmlWithTagCount(50),
        evaluateError: 'JS execution failed',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
      expect(calls.navigate).toHaveLength(1);
      expect(calls.evaluate).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-06: evaluate 返回内容过少 — 降级到 screenshot
    it('AD-06: evaluate 返回 < 10 字符时降级到 screenshot', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['Long content for detection']),
        pageHtml: makeHtmlWithTagCount(50),
        evaluateResult: { result: 'Hi', logs: [] },
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.evaluate).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-07: JS 注入被禁用且截图禁用 — 返回 ax_tree + error
    it('AD-07: JS 注入和截图均禁用时返回 ax_tree 加 error', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['Long content for detection']),
        pageHtml: makeHtmlWithTagCount(50),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        allowScriptInjection: false,
        allowScreenshotFallback: false,
      }));

      expect(result.strategyUsed).toBe('ax_tree');
      expect(result.error).toContain('disabled');
      expect(calls.navigate).toHaveLength(1);
    });

    // AD-08: JS 注入禁用但截图启用 — 降级到 screenshot
    it('AD-08: JS 注入禁用但截图启用时降级到 screenshot', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['Long content for detection']),
        pageHtml: makeHtmlWithTagCount(50),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        allowScriptInjection: false,
        allowScreenshotFallback: true,
      }));

      // 覆盖率低 + 无 JS 注入 => 走截图
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
      expect(calls.navigate).toHaveLength(1);
    });
  });

  /* ======================================================================
   * §3.3 Track 3 — screenshot_visual 全量降级
   * ====================================================================== */

  describe('§3.3 Track 3 — screenshot_visual 全量降级', () => {
    // AD-09: 反爬触发截图降级
    it('AD-09: 反爬触发截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Just a moment...'),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
      expect(calls.navigate).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-10: navigate 失败 → 直接 fallbackToScreenshot
    it('AD-10: navigate 失败时直接进入截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        navigateError: 'Navigation timed out',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
      expect(calls.navigate).toHaveLength(1);
      // navigate 失败所以不会调用 getSnapshot
      expect(calls.getSnapshot).toHaveLength(0);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-11: getSnapshot 失败 → fallbackToScreenshot
    it('AD-11: getSnapshot 失败时进入截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshotError: 'Accessibility tree not available',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
      expect(calls.navigate).toHaveLength(1);
      expect(calls.getSnapshot).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-12: screenshot 自身失败 → 'failed'
    it('AD-12: screenshot 自身失败时返回 failed', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Just a moment...'),
        screenshotError: 'Screenshot capture failed',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('failed');
      expect(result.error).toBeDefined();
      expect(result.error).toContain('Screenshot');
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-13: 截图降级被禁用 → 'failed'
    it('AD-13: 截图降级被禁用时返回 failed', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Just a moment...'),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        allowScreenshotFallback: false,
      }));

      expect(result.strategyUsed).toBe('failed');
      expect(result.error).toContain('allowScreenshotFallback=false');
      // 不应调用 screenshot
      expect(calls.screenshot).toHaveLength(0);
    });
  });

  /* ======================================================================
   * §3.4 C3-3 导航单次调用验证
   * ====================================================================== */

  describe('§3.4 C3-3 导航单次调用验证', () => {
    // AD-14: 完整 Track 1 — navigate 仅 1 次
    it('AD-14: ax_tree 路径 navigate 仅 1 次', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      await adapter.extractPage('https://example.com', context());

      expect(calls.navigate).toHaveLength(1);
    });

    // AD-15: Track 1 → Track 2 — navigate 仅 1 次
    it('AD-15: Track1→Track2 降级 navigate 仍仅 1 次', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['Long text for detection purposes']),
        pageHtml: makeHtmlWithTagCount(50),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('js_innertext');
      expect(calls.navigate).toHaveLength(1);
    });

    // AD-16: Track 1 → Track 3 — navigate 仍仅 1 次
    it('AD-16: Track1→Track3 反爬降级 navigate 仍仅 1 次', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Just a moment...'),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.navigate).toHaveLength(1);
    });

    // AD-17: navigate 失败 — navigate 仍仅 1 次
    it('AD-17: navigate 失败 navigate 仍仅 1 次', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        navigateError: 'Connection refused',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      await adapter.extractPage('https://example.com', context());

      expect(calls.navigate).toHaveLength(1);
    });
  });

  /* ======================================================================
   * §3.5 C3-4 安全超时验证
   * ====================================================================== */

  describe('§3.5 C3-4 安全超时验证', () => {
    // AD-18: navigate 超时 → 降级到 screenshot
    it('AD-18: navigate 超时时间到', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        navigateDelayMs: 200,  // 200ms 延迟
      });
      const adapter = new BrowserAutomationAdapter(runner);

      // 设置 50ms 超时，远小于 200ms 延迟
      const result = await adapter.extractPage('https://example.com', context({
        timeoutMs: 50,
      }));

      // navigate 超时 → fallbackToScreenshot
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
      expect(calls.navigate).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-19: getSnapshot 超时 → 降级到 screenshot
    it('AD-19: getSnapshot 超时后进入截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshotDelayMs: 300,  // 300ms 延迟
      });
      const adapter = new BrowserAutomationAdapter(runner);

      // timeoutMs 被传递给上下文 → 覆盖 getSnapshot 内部超时
      const result = await adapter.extractPage('https://example.com', context({
        timeoutMs: 50,
      }));

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.navigate).toHaveLength(1);
      expect(calls.getSnapshot).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-20: evaluate 超时 → 降级到 screenshot
    it('AD-20: evaluate 超时后进入截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['Long text for detection purposes']),
        pageHtml: makeHtmlWithTagCount(50),
        evaluateDelayMs: 300,  // 300ms 延迟
      });
      const adapter = new BrowserAutomationAdapter(runner);

      // 覆盖率低 → js_innertext → evaluate 超时
      const result = await adapter.extractPage('https://example.com', context({
        timeoutMs: 50,
      }));

      // evaluate 超时 → 尝试截图
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.evaluate).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-21: screenshot 超时 → failed
    it('AD-21: screenshot 超时后返回 failed', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Just a moment...'),
        screenshotDelayMs: 300,  // 300ms 延迟
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        timeoutMs: 50,
      }));

      expect(result.strategyUsed).toBe('failed');
      expect(result.error).toBeDefined();
      expect(result.error).toContain('screenshot');
      expect(calls.screenshot).toHaveLength(1);
    });

    // AD-22: 超时后 Promise 不残留
    it('AD-22: 超时后慢 Promise 结果被正确忽略', async () => {
      // 模拟场景：慢 Promise 在超时后 resolve
      // 但 withTimeout 使用显式 resolve/reject，Promise 只会 settle 一次
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        navigateDelayMs: 200,  // 200ms 后 resolve
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        timeoutMs: 50,
      }));

      // 超时后立即得到降级结果
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.navigate).toHaveLength(1);

      // 等待足够时间让慢 Promise 完成（虽然它已经被 settle 忽略）
      await wait(300);

      // 结果不应改变（Promise 已被 settle）
      expect(result.strategyUsed).toBe('screenshot_visual');
    });
  });

  /* ======================================================================
   * §3.6 场景感知超时测试
   * ====================================================================== */

  describe('§3.6 场景感知超时测试', () => {
    // SC-01: realtime_request 场景 → timeoutMs=5000, allowScreenshotFallback=false
    it('SC-01: realtime_request 场景超时配置', async () => {
      const { runner } = createMockRunner({
        navigateDelayMs: 6000,
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const ctx = createDefaultContext('realtime_request');
      const result = await adapter.extractPage('https://example.com', ctx);

      // realtime_request: timeoutMs=5000, 无截图降级
      // navigate 延迟 6s > 5s 超时 → 且 screenshot 被禁用
      expect(result.strategyUsed).toBe('failed');
      expect(result.error).toBeDefined();
    });

    // SC-02: offline_batch_sync 场景 → 允许全量降级
    it('SC-02: offline_batch_sync 场景允许全量降级', async () => {
      const { runner } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Just a moment...'),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const ctx = createDefaultContext('offline_batch_sync');
      const result = await adapter.extractPage('https://example.com', ctx);

      // offline_batch_sync 允许截图降级
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
    });

    // SC-03: interactive_operation 场景 → 超时较长 + 允许降级
    it('SC-03: interactive_operation 场景超时配置', async () => {
      const { runner } = createMockRunner({
        trackCalls: true,
        snapshot: DEFAULT_SNAPSHOT,
        pageHtml: makeAntiCrawlHtml('Checking your browser...'),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const ctx = createDefaultContext('interactive_operation');
      const result = await adapter.extractPage('https://example.com', ctx);

      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(result.screenshotBase64).toBeDefined();
    });
  });

  /* ======================================================================
   * §4 交互操作测试
   * ====================================================================== */

  describe('§4 交互操作测试', () => {
    // INT-01: click 成功 — 通过 interact() 调用
    it('INT-01: 点击操作成功', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await adapter.interact('https://example.com', [
        { type: 'click', selector: '#submit-button' },
      ], context());

      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(true);
      expect(calls.click).toHaveLength(1);
      expect(calls.click[0].selector).toBe('#submit-button');
    });

    // INT-02: click 失败
    it('INT-02: 点击操作失败应返回错误', async () => {
      const { runner } = createMockRunner({
        trackCalls: true,
        clickError: 'Element not found',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await adapter.interact('https://example.com', [
        { type: 'click', selector: '#missing-button' },
      ], context());

      expect(results[0].success).toBe(false);
      expect(results[0].error).toContain('Element not found');
    });

    // INT-03: fill 成功 — 通过 interact() 调用
    it('INT-03: 填充操作成功', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await adapter.interact('https://example.com', [
        { type: 'fill', selector: '#username', value: 'testuser' },
      ], context());

      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(true);
      expect(calls.fill).toHaveLength(1);
      expect(calls.fill[0].selector).toBe('#username');
      expect(calls.fill[0].value).toBe('testuser');
    });

    // INT-04: fill 失败
    it('INT-04: 填充操作失败应返回错误', async () => {
      const { runner } = createMockRunner({
        trackCalls: true,
        fillError: 'Input element disabled',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await adapter.interact('https://example.com', [
        { type: 'fill', selector: '#disabled-input', value: 'test' },
      ], context());

      expect(results[0].success).toBe(false);
      expect(results[0].error).toContain('Input element disabled');
    });

    // INT-05: press_key 成功 — 通过 interact() 调用
    it('INT-05: 按键操作成功', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await adapter.interact('https://example.com', [
        { type: 'press_key', selector: '', value: 'Enter' },
      ], context());

      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(true);
      expect(calls.pressKey).toHaveLength(1);
      expect(calls.pressKey[0].key).toBe('Enter');
    });

    // INT-06: press_key 失败
    it('INT-06: 按键操作失败应返回错误', async () => {
      const { runner } = createMockRunner({
        trackCalls: true,
        pressKeyError: 'Keyboard not available',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await adapter.interact('https://example.com', [
        { type: 'press_key', selector: '', value: 'Escape' },
      ], context());

      expect(results[0].success).toBe(false);
      expect(results[0].error).toContain('Keyboard not available');
    });

    // INT-07: evaluate 自定义脚本
    it('INT-07: 自定义 evaluate 脚本执行', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        evaluateResult: { result: 'custom script result', logs: [] },
      });
      const adapter = new BrowserAutomationAdapter(runner);

      // evaluate 直接转发到 mock
      const result = await runner.evaluate({ script: 'document.title' });

      expect(result.result).toBe('custom script result');
      expect(calls.evaluate).toHaveLength(1);
      expect(calls.evaluate[0].input.script).toBe('document.title');
    });
  });

  /* ======================================================================
   * §5 边界与极端情况
   * ====================================================================== */

  describe('§5 边界与极端情况', () => {
    // EDGE-01: 空 URL
    it('EDGE-01: 空 URL 处理', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        navigateError: 'Empty URL',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('', context());

      // 空 URL → navigate 失败 → fallbackToScreenshot
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.navigate).toHaveLength(1);
    });

    // EDGE-02: 极短超时 0ms
    it('EDGE-02: 0ms 超时应立即降级', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true, navigateDelayMs: 10 });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        timeoutMs: 0,
      }));

      // 0ms 超时 → navigate 立即超时 → fallbackToScreenshot
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.navigate).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // EDGE-03: 多次并行提取 — 互不干扰
    it('EDGE-03: 多次并行提取互不干扰', async () => {
      const { runner, calls } = createMockRunner({ trackCalls: true });
      const adapter = new BrowserAutomationAdapter(runner);

      const results = await Promise.all([
        adapter.extractPage('https://page1.com', context()),
        adapter.extractPage('https://page2.com', context()),
        adapter.extractPage('https://page3.com', context()),
      ]);

      // 全部成功
      results.forEach(r => {
        expect(r.strategyUsed).toBe('ax_tree');
      });

      // navigate 被调用了 3 次
      expect(calls.navigate).toHaveLength(3);
      expect(calls.navigate.map(c => c.url)).toContain('https://page1.com');
      expect(calls.navigate.map(c => c.url)).toContain('https://page2.com');
      expect(calls.navigate.map(c => c.url)).toContain('https://page3.com');
    });

    // EDGE-04: 无障碍树为 null
    it('EDGE-04: 无障碍树为 null 时进入截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: EMPTY_SNAPSHOT,
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      // 空树 → 检测 coverageRatio=0 → 且无文本内容 → screenshot_visual
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.getSnapshot).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // EDGE-05: 无障碍树只有根节点（无 children）
    it('EDGE-05: 无障碍树只有根节点时进入截图降级', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: ROOT_ONLY_SNAPSHOT,
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      // 只有根节点 → coverageRatio=0 → 且无文本内容 → screenshot_visual
      expect(result.strategyUsed).toBe('screenshot_visual');
      expect(calls.getSnapshot).toHaveLength(1);
      expect(calls.screenshot).toHaveLength(1);
    });

    // EDGE-06: 反爬关键词出现在 pageHtml 但不在上下文中（纯内容匹配）— 不应触发反爬
    it('EDGE-06: 纯内容含 "robot" 但不贴近反爬关键词时不触发反爬', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: makeSnapshotWithText(['A robot is a mechanical or virtual artificial agent']),
        pageHtml: `<html><body><p>A robot is a mechanical or virtual artificial agent, typically electro-mechanical.</p></body></html>`,
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      // 不应触发反爬 → 应为 ax_tree（覆盖率足够 + 有文本内容）
      expect(result.strategyUsed).toBe('ax_tree');
      expect(calls.navigate).toHaveLength(1);
      expect(calls.getSnapshot).toHaveLength(1);
    });

    // EDGE-07: 超长 HTML — 大量 DOM 标签
    it('EDGE-07: 大量 DOM 标签不影响稳定性', async () => {
      // 需要 5 个无障碍树节点 + 每个节点名 > 10 字符 → 通过 detectTextContent 检查
      // 但同时 5/1000 = 0.005 < 0.6 覆盖率低 → 触发 js_innertext 降级
      const manyNodesSnapshot: BrowserAutomationSnapshot = {
        accessibilityTree: {
          name: 'root',
          role: 'RootWebArea',
          children: Array.from({ length: 5 }, (_, i) => ({
            name: `This is long text content for node detection purposes item ${i}`,
            role: i % 2 === 0 ? 'button' : 'heading',
          })),
        },
        metadata: { title: 'Test Page', url: 'https://example.com', nodeCount: 5 },
      };
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        snapshot: manyNodesSnapshot,
        pageHtml: makeHtmlWithTagCount(1000),
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context());

      // 5/1000 = 0.005 < 0.6 覆盖率不足 → 降级到 JS innertext
      expect(result.strategyUsed).toBe('js_innertext');
      expect(calls.navigate).toHaveLength(1);
    });

    // EDGE-08: 禁用所有降级 — 直接返回 'failed'
    it('EDGE-08: 禁用所有降级时直接返回 failed', async () => {
      const { runner, calls } = createMockRunner({
        trackCalls: true,
        navigateError: 'Connection timeout',
      });
      const adapter = new BrowserAutomationAdapter(runner);

      const result = await adapter.extractPage('https://example.com', context({
        allowScreenshotFallback: false,
      }));

      // navigate 失败 + 无截图降级 → failed
      expect(result.strategyUsed).toBe('failed');
      expect(result.error).toBeDefined();
      // 不应调用 screenshot
      expect(calls.screenshot).toHaveLength(0);
    });
  });
});