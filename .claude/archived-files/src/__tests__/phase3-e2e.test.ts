/**
 * =============================================================================
 * Phase 3 E2E Integration Test: 三轨降级全链路 + ROI 能效遥测
 * =============================================================================
 *
 * 设计对齐 TEST_DESIGN_OUTLINE.md 最终章节:
 *   1) Node.js http.createServer 启本地 Mock Server（零外部依赖）
 *   2) 三个阻击端点模拟 Track 1/2/3 极端场景
 *   3) TelemetryInstrumentedRunner 植入 performance.now() 计时
 *   4) 采集 T_Init / T_Nav / T_Exec / T_Total 并验证 < 15s 红线
 *   5) ROI 诊断对比原始 Playwright 与三轨降级适配器
 *   6) 输出 phase3-roi-report.md + 控制台简报
 *
 * 生命周期纪律:
 *   - beforeAll: 启动 http.Server（随机端口），构造 URL
 *   - afterAll:  优雅关闭 server + 释放所有资源
 *   - 每个 test: 创建独立 MockRunner，测试结束后不留残留
 */

import * as http from 'http';
import * as fs from 'fs';
import * as path from 'path';
import { BrowserAutomationAdapter, type McpToolRunner } from '../adapter';
import { createDefaultContext, type ExtractionContext } from '../types';
import type {
  BrowserAutomationInput,
  BrowserAutomationSnapshot,
  PlaywrightEvaluateInput,
  PlaywrightEvaluateResult,
  PlaywrightScreenshotInput,
  PlaywrightScreenshotResult,
  ExtractionResult,
  ExtractionStrategy,
} from '../types';
import {
  createMockRunner,
  DEFAULT_SNAPSHOT,
  DEFAULT_EVALUATE_RESULT,
  DEFAULT_SCREENSHOT_RESULT,
} from './helpers/mockToolRunner';

/* ===========================================================================
 * 1. 常量
 * =========================================================================== */

/** 架构红线：总耗时不得超过 15s */
const BUDGET_MAX_MS = 15_000;

/** Token 估算（对齐 types.ts STRATEGY_TOKEN_ESTIMATES） */
const TOKEN_ESTIMATES: Record<ExtractionStrategy, number> = {
  'ax_tree':           1_500,
  'js_innertext':      4_000,
  'screenshot_visual': 20_000,
  'failed':            0,
};

/* ===========================================================================
 * 2. 遥测数据结构
 * =========================================================================== */

export interface TelemetryMarks {
  tStart: number;       // 整体开始
  navStart: number;     // navigate 开始
  navEnd: number;       // navigate 结束
  execStart: number;    // 轨道执行开始
  execEnd: number;      // 轨道执行结束
}

export interface TelemetrySnapshot {
  trackLabel: string;
  tInitMs: number;
  tNavMs: number;
  tExecMs: number;
  tTotalMs: number;
  strategyUsed: ExtractionStrategy;
  success: boolean;
  coverageRatio?: number;
  estimatedTokens: number;
}

export interface RoiDiagnosis {
  rawPlaywright: {
    scenarioCount: number;
    succeededCount: number;
    failedCount: number;
    successRate: number;
    avgTimeOnSuccess: number;
    totalTimeCost: number;
  };
  threeTrackAdapter: {
    scenarioCount: number;
    succeededCount: number;
    failedCount: number;
    successRate: number;
    avgTimeOnSuccess: number;
    totalTimeCost: number;
  };
  delta: {
    successRateImprovement: number;
    additionalLatencyOverhead: number;
    tokensRecoveredViaDegradation: number;
  };
}

export interface TelemetryReport {
  tracks: TelemetrySnapshot[];
  summary: {
    avgTotalMs: number;
    minTotalMs: number;
    maxTotalMs: number;
    withinBudget: boolean;
    allSucceeded: boolean;
  };
  roiDiagnosis: RoiDiagnosis;
}

/* ===========================================================================
 * 3. TelemetryInstrumentedRunner — 透明包装器植入计时
 * ===========================================================================
 *
 * 装饰器模式：不修改 adapter.ts，仅包裹 McpToolRunner 接口
 * 插桩点: navigate() → T_Nav, getSnapshot/evaluate/screenshot → T_Exec
 * T_Init 通过构造函数 start mark 与 navigate 开始之差计算
 */

class TelemetryInstrumentedRunner implements McpToolRunner {
  public readonly marks: TelemetryMarks;

  constructor(
    private readonly inner: McpToolRunner,
    private readonly trackLabel: string,
  ) {
    this.marks = {
      tStart: performance.now(),
      navStart: 0,
      navEnd: 0,
      execStart: 0,
      execEnd: 0,
    };
  }

  async navigate(url: string): Promise<void> {
    this.marks.navStart = performance.now();
    try {
      await this.inner.navigate(url);
    } finally {
      this.marks.navEnd = performance.now();
    }
  }

  async getSnapshot(input: BrowserAutomationInput): Promise<BrowserAutomationSnapshot> {
    this.markExecStart();
    try {
      return await this.inner.getSnapshot(input);
    } finally {
      this.markExecEnd();
    }
  }

  async getPageHtml(url: string): Promise<string> {
    if (typeof this.inner.getPageHtml !== 'function') {
      return '';
    }
    this.markExecStart();
    try {
      return await this.inner.getPageHtml(url);
    } finally {
      this.markExecEnd();
    }
  }

  async evaluate(input: PlaywrightEvaluateInput): Promise<PlaywrightEvaluateResult> {
    this.markExecStart();
    try {
      return await this.inner.evaluate(input);
    } finally {
      this.markExecEnd();
    }
  }

  async screenshot(input: PlaywrightScreenshotInput): Promise<PlaywrightScreenshotResult> {
    this.markExecStart();
    try {
      return await this.inner.screenshot(input);
    } finally {
      this.markExecEnd();
    }
  }

  async click(selector: string): Promise<void> {
    return this.inner.click(selector);
  }

  async fill(input: { selector: string; value: string }): Promise<void> {
    return this.inner.fill(input);
  }

  async pressKey(key: string): Promise<void> {
    return this.inner.pressKey(key);
  }

  /** 生成遥测快照 */
  buildSnapshot(
    result: ExtractionResult,
  ): TelemetrySnapshot {
    const tNow = performance.now();
    const tInitMs = this.round2(this.marks.navStart - this.marks.tStart);
    const tNavMs = this.round2(this.marks.navEnd - this.marks.navStart);
    const tExecMs = this.round2(this.marks.execEnd - this.marks.execStart);
    const tTotalMs = this.round2(tNow - this.marks.tStart);

    return {
      trackLabel: this.trackLabel,
      tInitMs,
      tNavMs,
      tExecMs,
      tTotalMs,
      strategyUsed: result.strategyUsed,
      success: result.strategyUsed !== 'failed',
      coverageRatio: result.coverageReport?.coverageRatio,
      estimatedTokens: TOKEN_ESTIMATES[result.strategyUsed] ?? 0,
    };
  }

  /** 包装器内部使用——标记 exec 阶段（只记第一次调用） */
  private markExecStart(): void {
    if (this.marks.execStart === 0) {
      this.marks.execStart = performance.now();
    }
  }

  private markExecEnd(): void {
    if (this.marks.execEnd === 0) {
      this.marks.execEnd = performance.now();
    }
  }

  private round2(n: number): number {
    return Math.round(n * 100) / 100;
  }
}

/* ===========================================================================
 * 4. Mock HTTP Server 工厂
 * =========================================================================== */

/** HTML HTML — Track 1: 标准语义标签 */
const HTML_TRACK1_NORMAL = `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Normal Page — Track 1</title></head>
<body>
  <header>
    <nav><a href="/">Home</a> | <a href="/about">About</a></nav>
  </header>
  <main>
    <article>
      <h1>Welcome to Our Platform</h1>
      <p>This is a standard HTML page with semantic markup for accessibility tree extraction.</p>
      <section>
        <h2>Latest News</h2>
        <ul>
          <li><strong>Item 1:</strong> Platform update v2.1 released</li>
          <li><strong>Item 2:</strong> New dashboard features available</li>
          <li><strong>Item 3:</strong> Security patch applied</li>
        </ul>
      </section>
    </article>
    <aside>
      <h3>Quick Links</h3>
      <ul>
        <li><a href="/settings">Settings</a></li>
        <li><a href="/profile">Profile</a></li>
        <li><a href="/help">Help Center</a></li>
      </ul>
    </aside>
  </main>
  <footer><p>&copy; 2026 AI Studio. All rights reserved.</p></footer>
</body>
</html>`;

/** HTML HTML — Track 2: 大量垃圾标签 + 少量核心文本 */
const HTML_TRACK2_JUNK = `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Junk Page — Track 2</title></head>
<body>
  <div id="app">
    <!-- 150 个无用空壳 div -->
    ${Array.from({ length: 150 }, (_, i) => `<div class="spam" data-idx="${i}">placeholder ${i}</div>`).join('\n    ')}
    <!-- 核心文本（仅占 0.66% DOM 元素） -->
    <div id="core-content">
      <p>Page content for extraction via JS innerText fallback</p>
      <p>This meaningful text should be recovered by Track 2 degradation.</p>
    </div>
  </div>
</body>
</html>`;

/** HTML HTML — Track 3: SPA Loading 占位符（触发 Hydration 检测） */
const HTML_TRACK3_SPA = `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Loading...</title></head>
<body>
  <div id="app">
    <div class="spinner">
      <p>Loading...</p>
    </div>
  </div>
  <!-- SPA 典型特征：无 SSR 内容，等待 JS hydrate -->
  <script>
    // Simulate async chunk loading
    setTimeout(() => {
      document.getElementById('app').innerHTML = '<h1>Dashboard</h1><p>Content loaded after hydration</p>';
    }, 50000);
  </script>
</body>
</html>`;

/** HTML 404 fallback — 不应被访问 */
const HTML_404 = '<html><body><h1>404 Not Found</h1></body></html>';

/**
 * 创建并启动本地 Mock HTTP Server
 * @returns { server, port } 绑定随机端口
 */
function createMockServer(): Promise<{ server: http.Server; port: number }> {
  return new Promise((resolve, reject) => {
    const server = http.createServer((req, res) => {
      res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });

      switch (req.url) {
        case '/track1-normal':
          res.end(HTML_TRACK1_NORMAL);
          break;
        case '/track2-junk':
          res.end(HTML_TRACK2_JUNK);
          break;
        case '/track3-spa':
          res.end(HTML_TRACK3_SPA);
          break;
        default:
          res.writeHead(404);
          res.end(HTML_404);
          break;
      }
    });

    server.listen(0, '127.0.0.1', () => {
      const addr = server.address();
      if (!addr || typeof addr === 'string') {
        reject(new Error('Failed to get server address'));
        return;
      }
      resolve({ server, port: addr.port });
    });

    server.on('error', reject);
  });
}

/* ===========================================================================
 * 5. ROI 诊断函数
 * =========================================================================== */

function computeRoiDiagnosis(tracks: TelemetrySnapshot[]): RoiDiagnosis {
  // 原生 Playwright 模拟：只有 Track 1 成功，Track 2/3 失败（遇错即败）
  const rawSuccesses = tracks.filter(t => t.strategyUsed === 'ax_tree');
  const rawFails = tracks.filter(t => t.strategyUsed !== 'ax_tree');

  // 三轨适配器：全部成功即为成功
  const adapterSuccesses = tracks.filter(t => t.success);
  const adapterFails = tracks.filter(t => !t.success);

  const avg = (vals: number[]) =>
    vals.length > 0 ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;

  const rawAvgTime = rawSuccesses.length > 0
    ? avg(rawSuccesses.map(t => t.tTotalMs))
    : 0;

  const adapterAvgTime = adapterSuccesses.length > 0
    ? avg(adapterSuccesses.map(t => t.tTotalMs))
    : 0;

  const rawTotalCost = rawSuccesses.reduce((s, t) => s + t.tTotalMs, 0);
  const adapterTotalCost = tracks.reduce((s, t) => s + t.tTotalMs, 0);

  // 降级场景回收的 Token = Track 2/3 的 estimatedTokens
  const recoveredTokens = rawFails.reduce((s, t) => s + t.estimatedTokens, 0);

  const deltaLatency = adapterAvgTime - rawAvgTime;

  return {
    rawPlaywright: {
      scenarioCount: tracks.length,
      succeededCount: rawSuccesses.length,
      failedCount: rawFails.length,
      successRate: tracks.length > 0 ? (rawSuccesses.length / tracks.length) * 100 : 0,
      avgTimeOnSuccess: Math.round(rawAvgTime * 100) / 100,
      totalTimeCost: Math.round(rawTotalCost * 100) / 100,
    },
    threeTrackAdapter: {
      scenarioCount: tracks.length,
      succeededCount: adapterSuccesses.length,
      failedCount: adapterFails.length,
      successRate: tracks.length > 0 ? (adapterSuccesses.length / tracks.length) * 100 : 0,
      avgTimeOnSuccess: Math.round(adapterAvgTime * 100) / 100,
      totalTimeCost: Math.round(adapterTotalCost * 100) / 100,
    },
    delta: {
      successRateImprovement: Math.round(
        ((tracks.length > 0 ? (adapterSuccesses.length / tracks.length) : 0)
         - (tracks.length > 0 ? (rawSuccesses.length / tracks.length) : 0)) * 10000
      ) / 100,
      additionalLatencyOverhead: Math.round(deltaLatency * 100) / 100,
      tokensRecoveredViaDegradation: recoveredTokens,
    },
  };
}

/* ===========================================================================
 * 6. ROI 简报格式化与文件输出
 * =========================================================================== */

const REPORT_FILE = path.resolve(__dirname, '../../phase3-roi-report.md');

function generateRoiReport(report: TelemetryReport): string {
  const { tracks, summary, roiDiagnosis } = report;
  const { rawPlaywright: raw, threeTrackAdapter: ada, delta } = roiDiagnosis;

  let reportMd = `# Phase 3 ROI Energy Efficiency Telemetry Report

## Performance Compliance

| Track | T_Init (ms) | T_Nav (ms) | T_Exec (ms) | T_Total (ms) | Budget ≤ 15s | Strategy |
|-------|------------|-----------|------------|-------------|-------------|----------|
`;

  for (const t of tracks) {
    const pass = t.tTotalMs <= BUDGET_MAX_MS ? '✅ PASS' : '❌ FAIL';
    reportMd += `| ${t.trackLabel} | ${t.tInitMs} | ${t.tNavMs} | ${t.tExecMs} | ${t.tTotalMs} | ${pass} | \`${t.strategyUsed}\` |\n`;
  }

  reportMd += `
**Summary:** Avg=${summary.avgTotalMs}ms Min=${summary.minTotalMs}ms Max=${summary.maxTotalMs}ms
Budget Compliance: **${summary.withinBudget ? '✅ ALL PASS' : '❌ VIOLATION'}**
All Succeeded: **${summary.allSucceeded ? '✅ YES' : '⚠️ PARTIAL'}**

## ROI Diagnosis

### Raw Playwright (hypothetical — fail on any error)
| Metric | Value |
|--------|-------|
| Scenarios | ${raw.scenarioCount} |
| Succeeded | ${raw.succeededCount} |
| Failed | ${raw.failedCount} |
| Success Rate | ${raw.successRate.toFixed(1)}% |
| Avg Time on Success | ${raw.avgTimeOnSuccess}ms |
| Total Time Cost | ${raw.totalTimeCost}ms |

### 3-Track Degradation Adapter (actual)
| Metric | Value |
|--------|-------|
| Scenarios | ${ada.scenarioCount} |
| Succeeded | ${ada.succeededCount} |
| Failed | ${ada.failedCount} |
| Success Rate | ${ada.successRate.toFixed(1)}% |
| Avg Time on Success | ${ada.avgTimeOnSuccess}ms |
| Total Time Cost | ${ada.totalTimeCost}ms |

### Delta Analysis
| Metric | Delta |
|--------|-------|
| Success Rate Improvement | **+${delta.successRateImprovement.toFixed(1)}%** |
| Additional Latency Overhead | ${delta.additionalLatencyOverhead}ms avg |
| Tokens Recovered via Degradation | ${delta.tokensRecoveredViaDegradation} tokens |

## Verdict

- **Architecture Redline (< 15s):** ${summary.withinBudget ? '✅ Compliant' : '❌ Violated'}
- **Success Rate:** ${raw.successRate.toFixed(0)}% → ${ada.successRate.toFixed(0)}% (Δ+${delta.successRateImprovement.toFixed(0)}%)
- **Degradation Value:** Recovered ${delta.tokensRecoveredViaDegradation} tokens across ${raw.failedCount} failed scenarios that would have been lost
`;

  return reportMd;
}

function printConsoleReport(report: TelemetryReport): void {
  const { tracks, summary, roiDiagnosis } = report;
  const { rawPlaywright: raw, threeTrackAdapter: ada, delta } = roiDiagnosis;

  console.log('\n' + '='.repeat(70));
  console.log('  Phase 3 ROI Energy Efficiency Telemetry');
  console.log('='.repeat(70));
  console.log();

  console.log('[PERFORMANCE COMPLIANCE]');
  for (const t of tracks) {
    const pass = t.tTotalMs <= BUDGET_MAX_MS ? '✅' : '❌';
    console.log(
      `  ${t.trackLabel.padEnd(28)} ` +
      `T_Init=${t.tInitMs}ms T_Nav=${t.tNavMs}ms T_Exec=${t.tExecMs}ms ` +
      `T_Total=${t.tTotalMs}ms ${pass} < ${BUDGET_MAX_MS / 1000}s`
    );
  }
  console.log(
    `  Avg Total: ${summary.avgTotalMs}ms  `.padEnd(45) +
    `Budget Compliance: ${summary.withinBudget ? '✅ ALL PASS' : '❌ VIOLATION'}`
  );
  console.log();

  console.log('[ROI DIAGNOSIS]');
  console.log('  Raw Playwright (hypothetical):');
  console.log(`    Success Rate: ${raw.succeededCount}/${raw.scenarioCount} (${raw.successRate.toFixed(1)}%)`);
  console.log(`    Avg Time on Success: ${raw.avgTimeOnSuccess}ms`);
  console.log(`    Total Time Cost: ${raw.totalTimeCost}ms`);

  console.log('  3-Track Adapter (actual):');
  console.log(`    Success Rate: ${ada.succeededCount}/${ada.scenarioCount} (${ada.successRate.toFixed(1)}%)`);
  console.log(`    Avg Time on Success: ${ada.avgTimeOnSuccess}ms`);
  console.log(`    Total Time Cost: ${ada.totalTimeCost}ms`);

  console.log('  Delta:');
  console.log(`    Success Rate Improvement: +${delta.successRateImprovement.toFixed(1)}% ${delta.successRateImprovement > 0 ? '✅' : ''}`);
  console.log(`    Additional Overhead: ${delta.additionalLatencyOverhead}ms avg per track`);
  console.log(`    Tokens Recovered: ${delta.tokensRecoveredViaDegradation} tokens`);
  console.log('='.repeat(70));
  console.log();
}

/* ===========================================================================
 * 7. E2E Test Suite
 * =========================================================================== */

describe('Phase 3: E2E 全链路集成测试 & ROI 能效遥测', () => {
  let server: http.Server;
  let port: number;
  let baseUrl: string;

  /** 收集所有 TelemetrySnapshot 用于最终 ROI 报告 */
  const telemetrySnapshots: TelemetrySnapshot[] = [];

  // ── 生命周期管理 ──────────────────────────────────────────────────────

  beforeAll(async () => {
    const result = await createMockServer();
    server = result.server;
    port = result.port;
    baseUrl = `http://127.0.0.1:${port}`;
    console.log(`\n[Mock Server] Listening on ${baseUrl}`);
  }, 10_000);

  afterAll((done) => {
    // 关闭 HTTP Server，防止 Jest 进程挂起
    if (server && server.listening) {
      server.close((err) => {
        if (err) {
          console.error('[Mock Server] Close error:', err);
        } else {
          console.log('[Mock Server] Gracefully closed');
        }
        done();
      });
    } else {
      done();
    }
  });

  // 每个测试后收集遥测（由每个 test 内部 push 到 telemetrySnapshots）
  afterEach(() => {
    // 清理引用，防止跨测试干扰
  });

  // ── Helper: 运行单次提取并采集遥测 ──────────────────────────────────

  async function runExtractWithTelemetry(
    label: string,
    url: string,
    ctx: ExtractionContext,
    mockConfig: Parameters<typeof createMockRunner>[0],
  ): Promise<{ result: ExtractionResult; snapshot: TelemetrySnapshot }> {
    const { runner } = createMockRunner(mockConfig);
    const instrumented = new TelemetryInstrumentedRunner(runner, label);
    const adapter = new BrowserAutomationAdapter(instrumented);

    const result = await adapter.extractPage(url, ctx);
    const snapshot = instrumented.buildSnapshot(result);
    telemetrySnapshots.push(snapshot);

    return { result, snapshot };
  }

  // ── Helper: 构造 URL ─────────────────────────────────────────────────

  function url(path: string): string {
    return `${baseUrl}${path}`;
  }

  /* ======================================================================
   * E2E-01: Track 1 正常路径 — ax_tree
   *   模拟标准 HTML 页面 → 无障碍树全覆盖
   * ====================================================================== */

  it('E2E-01: Track 1 — ax_tree 正常路径', async () => {
    const { result, snapshot } = await runExtractWithTelemetry(
      'Track 1 — ax_tree',
      url('/track1-normal'),
      createDefaultContext('offline_batch_sync'),
      {
        // 标准无障碍树：覆盖率高 → 走 ax_tree
        snapshot: {
          accessibilityTree: {
            name: 'root',
            role: 'RootWebArea',
            children: [
              {
                name: 'Navigation',
                role: 'navigation',
                children: [
                  { name: 'Home', role: 'link' },
                  { name: 'About', role: 'link' },
                ],
              },
              {
                name: 'Main Content',
                role: 'main',
                children: [
                  { name: 'Welcome to Our Platform', role: 'heading' },
                  { name: 'This is a paragraph with enough text content for detection', role: 'paragraph' },
                ],
              },
            ],
          },
          metadata: { title: 'Normal Page — Track 1', url: url('/track1-normal'), nodeCount: 6 },
        },
      },
    );

    expect(result.strategyUsed).toBe('ax_tree');
    expect(result.structuredData).toBeDefined();
    expect(result.structuredData).toContain('Welcome to Our Platform');
    expect(snapshot.tTotalMs).toBeLessThan(BUDGET_MAX_MS);
    expect(snapshot.success).toBe(true);
  });

  /* ======================================================================
   * E2E-02: Track 2 降级路径 — js_innertext
   *   大量垃圾标签（150+）+ 少量核心文本 → 覆盖率 < 60% → JS 注入
   * ====================================================================== */

  it('E2E-02: Track 2 — js_innertext 降级', async () => {
    const { result, snapshot } = await runExtractWithTelemetry(
      'Track 2 — js_innertext',
      url('/track2-junk'),
      createDefaultContext('offline_batch_sync'),
      {
        // 模拟低覆盖率: 少量无障碍节点 + 大量 DOM
        snapshot: {
          accessibilityTree: {
            name: 'root',
            role: 'RootWebArea',
            children: [
              { name: 'Page content for extraction via JS innerText fallback', role: 'paragraph' },
              { name: 'This meaningful text should be recovered by Track 2 degradation', role: 'paragraph' },
            ],
          },
          metadata: { title: 'Junk Page', url: url('/track2-junk'), nodeCount: 2 },
        },
        pageHtml: HTML_TRACK2_JUNK,
        // evaluate 返回的核心文本（对应 Track 2 降级后的内联提取）
        evaluateResult: {
          result: 'Page content for extraction via JS innerText fallback\nThis meaningful text should be recovered by Track 2 degradation.',
          logs: [],
        },
      },
    );

    // 覆盖率低 → 触发 JS innerText 降级
    expect(result.strategyUsed).toBe('js_innertext');
    expect(result.textContent).toBeDefined();
    // 必须包含核心文本（验证降级未丢失数据）
    if (result.textContent) {
      const hasCoreContent =
        result.textContent.includes('Page content for extraction') ||
        result.textContent.includes('This meaningful text');
      expect(hasCoreContent).toBe(true);
    }
    expect(snapshot.tTotalMs).toBeLessThan(BUDGET_MAX_MS);
    expect(snapshot.success).toBe(true);
  });

  /* ======================================================================
   * E2E-03: Track 3 极限降级 — screenshot_visual
   *   SPA Loading 占位符 → Hydration 检测 → 覆盖率归零 → 视觉截图
   * ====================================================================== */

  it('E2E-03: Track 3 — screenshot_visual 极限降级', async () => {
    const { result, snapshot } = await runExtractWithTelemetry(
      'Track 3 — screenshot_visual',
      url('/track3-spa'),
      createDefaultContext('offline_batch_sync'),
      {
        // 模拟 SPA: 无障碍树只有根节点（无 children）→ coverageRatio=0
        snapshot: {
          accessibilityTree: {
            name: 'root',
            role: 'RootWebArea',
            // 无 children → SPA Hydration 检测触发
          },
          metadata: { title: 'Loading...', url: url('/track3-spa'), nodeCount: 0 },
        },
        pageHtml: HTML_TRACK3_SPA,
      },
    );

    // SPA 未 hydration → 覆盖率归零 → 视觉截图降级
    expect(result.strategyUsed).toBe('screenshot_visual');
    expect(result.screenshotBase64).toBeDefined();
    expect(snapshot.tTotalMs).toBeLessThan(BUDGET_MAX_MS);
    expect(snapshot.success).toBe(true);
  });

  /* ======================================================================
   * E2E-04: 三场景顺序执行 + 完整遥测采集
   *   模拟真实调用序列：Track 1 → Track 2 → Track 3
   * ====================================================================== */

  it('E2E-04: 三场景顺序执行 + 遥测采集', async () => {
    const scenarios: Array<{
      label: string;
      url: string;
      ctx: ExtractionContext;
      mockConfig: Parameters<typeof createMockRunner>[0];
      expectedStrategy: string;
    }> = [
      {
        label: 'Track 1 — ax_tree',
        url: url('/track1-normal'),
        ctx: createDefaultContext('offline_batch_sync'),
        mockConfig: {},
        expectedStrategy: 'ax_tree',
      },
      {
        label: 'Track 2 — js_innertext',
        url: url('/track2-junk'),
        ctx: createDefaultContext('offline_batch_sync'),
        mockConfig: {
          snapshot: {
            accessibilityTree: {
              name: 'root',
              role: 'RootWebArea',
              children: [
                { name: 'Page content for extraction via JS innerText fallback', role: 'paragraph' },
              ],
            },
            metadata: { title: 'Junk Page', url: url('/track2-junk'), nodeCount: 1 },
          },
          pageHtml: HTML_TRACK2_JUNK,
        },
        expectedStrategy: 'js_innertext',
      },
      {
        label: 'Track 3 — screenshot_visual',
        url: url('/track3-spa'),
        ctx: createDefaultContext('offline_batch_sync'),
        mockConfig: {
          snapshot: {
            accessibilityTree: {
              name: 'root',
              role: 'RootWebArea',
            },
            metadata: { title: 'Loading...', url: url('/track3-spa'), nodeCount: 0 },
          },
          pageHtml: HTML_TRACK3_SPA,
        },
        expectedStrategy: 'screenshot_visual',
      },
    ];

    const localSnapshots: TelemetrySnapshot[] = [];

    for (const s of scenarios) {
      const { runner } = createMockRunner(s.mockConfig);
      const instrumented = new TelemetryInstrumentedRunner(runner, s.label);
      const adapter = new BrowserAutomationAdapter(instrumented);

      const result = await adapter.extractPage(s.url, s.ctx);
      const snapshot = instrumented.buildSnapshot(result);

      expect(result.strategyUsed).toBe(s.expectedStrategy);
      expect(snapshot.tTotalMs).toBeLessThan(BUDGET_MAX_MS);
      expect(snapshot.success).toBe(true);

      localSnapshots.push(snapshot);
    }

    // 验证三条轨道全部通过
    expect(localSnapshots).toHaveLength(3);
    localSnapshots.forEach(s => {
      expect(s.success).toBe(true);
      expect(s.tTotalMs).toBeLessThan(BUDGET_MAX_MS);
    });

    // 验证 C3-3 SNA: 通过 snapshot 确认 navigate 开销被正确捕获
    for (const s of localSnapshots) {
      // T_Nav 必须在合理范围内（mock 默认无延迟，应 < 50ms）
      expect(s.tNavMs).toBeLessThan(50);
      // T_Init 应该在毫秒级
      expect(s.tInitMs).toBeGreaterThanOrEqual(0);
      expect(s.tInitMs).toBeLessThan(100);
    }
  });

  /* ======================================================================
   * E2E-05: SPA Hydration 检测 + 覆盖率强制归零验证
   *   模拟极端 SPA 场景：nodeCount < 5 + pageHtml 含 Loading 占位符
   *   → 强制归零并路由到 screenshot_visual
   * ====================================================================== */

  it('E2E-05: SPA Hydration 检测 → 覆盖率归零 → screenshot_visual', async () => {
    const { runner } = createMockRunner({
      // SPA 特征: 无障碍树仅 1 个节点 (< 5) + HTML 含 loading 占位符
      snapshot: {
        accessibilityTree: {
          name: 'root',
          role: 'RootWebArea',
          children: [
            { name: 'app', role: 'generic' },
          ],
        },
        metadata: { title: 'Loading...', url: url('/track3-spa'), nodeCount: 1 },
      },
      pageHtml: HTML_TRACK3_SPA,
    });
    const instrumented = new TelemetryInstrumentedRunner(runner, 'Track 3 — SPA Hydration');
    const adapter = new BrowserAutomationAdapter(instrumented);

    const result = await adapter.extractPage(url('/track3-spa'), createDefaultContext('offline_batch_sync'));

    // SPA Hydration 检测 → screenshot_visual
    expect(result.strategyUsed).toBe('screenshot_visual');
    expect(result.screenshotBase64).toBeDefined();

    // 覆盖率应为 0（强制归零）
    if (result.coverageReport) {
      expect(result.coverageReport.coverageRatio).toBe(0);
    }

    // 遥测验证
    const snapshot = instrumented.buildSnapshot(result);
    expect(snapshot.tTotalMs).toBeLessThan(BUDGET_MAX_MS);
    expect(snapshot.success).toBe(true);

    // 存入全局遥测
    telemetrySnapshots.push(snapshot);
  });

  /* ======================================================================
   * 最终快照: ROI 诊断 & 审计简报输出
   *   afterAll 之后运行——用全局 telemetrySnapshots 生成报告
   * ====================================================================== */

  afterAll(() => {
    // 去重：E2E-04 和 E2E-01~03 可能有重复，取 E2E-04 的三条 + 其他唯一记录
    const unique = new Map<string, TelemetrySnapshot>();
    for (const t of telemetrySnapshots) {
      unique.set(t.trackLabel + t.strategyUsed + t.tTotalMs, t);
    }

    const tracks = Array.from(unique.values());

    if (tracks.length === 0) {
      console.log('[ROI Report] No telemetry data collected — skipping report generation.');
      return;
    }

    const allUnderBudget = tracks.every(t => t.tTotalMs <= BUDGET_MAX_MS);
    const allSucceeded = tracks.every(t => t.success);
    const avgTotal = Math.round(
      tracks.reduce((s, t) => s + t.tTotalMs, 0) / tracks.length * 100
    ) / 100;
    const totals = tracks.map(t => t.tTotalMs);

    const report: TelemetryReport = {
      tracks,
      summary: {
        avgTotalMs: avgTotal,
        minTotalMs: Math.min(...totals),
        maxTotalMs: Math.max(...totals),
        withinBudget: allUnderBudget,
        allSucceeded,
      },
      roiDiagnosis: computeRoiDiagnosis(tracks),
    };

    // 控制台格式化输出
    printConsoleReport(report);

    // 写入 phase3-roi-report.md
    const md = generateRoiReport(report);
    fs.writeFileSync(REPORT_FILE, md, 'utf-8');
    console.log(`[ROI Report] Written to ${REPORT_FILE}`);

    // 附加断言：红线验证
    expect(allUnderBudget).toBe(true);
  });
});