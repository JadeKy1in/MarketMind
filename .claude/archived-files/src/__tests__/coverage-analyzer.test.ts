/**
 * CoverageAnalyzer 单元测试
 * =============================================================================
 *
 * 对齐 TEST_DESIGN_OUTLINE.md §2 的测试设计。
 * Phase 1 (基础层验证): CA-01~CA-06, TC-01~TC-03, HE-01~HE-03
 *
 * 测试策略：
 *   - 直接调用 analyzeCoverage() 及内部导出函数
 *   - 使用 mockToolRunner 辅助函数构造精确的测试快照
 */

import {
  analyzeCoverage,
  countAxNodes,
  countHiddenNodes,
  estimateDomFromHtml,
  detectTextContent,
  recommendStrategy,
  COVERAGE_THRESHOLD,
  MIN_TRUSTED_NODES,
} from '../coverage-analyzer';

import type {
  BrowserAutomationSnapshot,
} from '../types';

import {
  makeSnapshotWithNodeCount,
  makeSnapshotWithHidden,
  makeSnapshotWithText,
  EMPTY_SNAPSHOT,
  ROOT_ONLY_SNAPSHOT,
  DEFAULT_SNAPSHOT,
} from './helpers/mockToolRunner';

/* ===========================================================================
 * 辅助函数——生成指定 tag 数量的 HTML
 * =========================================================================== */

/** 生成含指定数量 `<div>` 标签的 HTML 字符串 */
function htmlWithTags(tagCount: number): string {
  return Array(tagCount).fill('<div></div>').join('\n');
}

/** 生成不含反爬特征的纯文本 HTML */
function simpleHtml(body: string): string {
  return `<html><head><title>Test</title></head><body>${body}</body></html>`;
}

/* ===========================================================================
 * §2.1 覆盖率计算核心路径 (CA-01 ~ CA-06)
 * =========================================================================== */

describe('CA — 覆盖率计算核心路径', () => {
  /**
   * CA-01: 覆盖率 ≥ 60% — 标准页面
   *   snapshot 含 60 个 a11y 节点, html 含 80 个 DOM 元素
   *   期望: coverageRatio ≥ 0.6, recommendedStrategy = 'screenshot_visual'
   */
  test('CA-01: 覆盖率 ≥ 60% — 标准页面', () => {
    const snapshot = makeSnapshotWithNodeCount(59);
    // 80 div tags + 4 wrapper (html,head,title,body) = 84 total DOM elements
    const pageHtml = simpleHtml(htmlWithTags(80));

    const report = analyzeCoverage(snapshot, pageHtml);

    // 59 children + root = 60 accessible; 84 total DOM elements
    // coverage = 60 / 84 ≈ 0.714 ≥ 0.6
    // hasTextContent: names "Node X" (< 10 chars) → false
    // coverage ≥ 60% + !hasTextContent → screenshot_visual
    expect(report.coverageRatio).toBeGreaterThanOrEqual(0.6);
    expect(report.totalDomElements).toBe(84);
    expect(report.accessibleElements).toBe(60);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * CA-02: 覆盖率 = 60% 边界值
   *   snapshot 含 60 个 a11y 节点, html 含 96 div + 4 wrapper = 100 DOM 元素（正好 60%）
   *   期望: coverageRatio = 0.6
   */
  test('CA-02: 覆盖率 = 60% 边界值', () => {
    const snapshot = makeSnapshotWithNodeCount(59);
    // 96 divs + 4 wrapper (html,head,title,body) = 100 total
    const pageHtml = simpleHtml(htmlWithTags(96));

    const report = analyzeCoverage(snapshot, pageHtml);

    expect(report.coverageRatio).toBe(0.6);
    expect(report.totalDomElements).toBe(100);
    expect(report.accessibleElements).toBe(60);
  });

  /**
   * CA-03: 覆盖率 < 60% — 触发降级
   *   snapshot 含 40 个 a11y 节点, 96 divs + 4 wrapper = 100 个 DOM 元素
   *   期望: coverageRatio = 41/100 = 0.41, recommendedStrategy = 'screenshot_visual'
   *   节点 name="Node X" < 10 字符 → hasTextContent=false
   *   coverage < 60% + !hasTextContent → screenshot_visual
   */
  test('CA-03: 覆盖率 < 60% — 触发降级', () => {
    const snapshot = makeSnapshotWithNodeCount(40);
    // 96 divs + 4 wrapper = 100 total
    const pageHtml = simpleHtml(htmlWithTags(96));

    const report = analyzeCoverage(snapshot, pageHtml);

    expect(report.accessibleElements).toBe(41);
    expect(report.totalDomElements).toBe(100);
    expect(report.coverageRatio).toBe(0.41);
    expect(report.coverageRatio).toBeLessThan(COVERAGE_THRESHOLD);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * CA-04: 覆盖率 = 0% — 极端降级
   *   snapshot a11y tree = null
   *   期望: coverageRatio = 0, recommendedStrategy = 'screenshot_visual'
   */
  test('CA-04: 覆盖率 = 0% — 极端降级', () => {
    const report = analyzeCoverage(EMPTY_SNAPSHOT);

    expect(report.coverageRatio).toBe(0);
    expect(report.accessibleElements).toBe(0);
    expect(report.totalDomElements).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * CA-05: DOM 元素统计靠 HTML 标签
   *   116 body tags (div+p+a) + 4 wrapper (html,head,title,body) = 120 DOM 元素
   *   期望: totalDomElements = 120
   */
  test('CA-05: DOM 元素统计靠 HTML 标签', () => {
    const mixedHtml = simpleHtml(
      Array(38).fill('<div></div>').join('\n') +
      Array(39).fill('<p></p>').join('\n') +
      Array(39).fill('<a></a>').join('\n'),
    ); // 38+39+39=116 body tags + 4 wrapper = 120

    const snapshot = makeSnapshotWithNodeCount(50);
    const report = analyzeCoverage(snapshot, mixedHtml);

    expect(report.totalDomElements).toBe(120);
  });

  /**
   * CA-06: 无 pageHtml 时的回退估算
   *   snapshot.metadata.nodeCount = 80 (不含 root), accessible = 81
   *   实际代码用 nodeCount 做估算: round(80*1.25) = 100
   *   totalDomElements = max(81, 100) = 100
   *   coverageRatio = 81/100 = 0.81
   */
  test('CA-06: 无 pageHtml 时的回退估算', () => {
    const nodeCount = 80;
    const snapshot = makeSnapshotWithNodeCount(nodeCount);

    const report = analyzeCoverage(snapshot);

    const accessibleElements = countAxNodes(snapshot.accessibilityTree); // 81
    const estimated = Math.round(nodeCount * 1.25); // 100
    expect(report.totalDomElements).toBe(Math.max(accessibleElements, estimated)); // 100
    expect(report.coverageRatio).toBe(0.81);
  });
});

/* ===========================================================================
 * §2.4 文本检测 (TC-01 ~ TC-03)
 * =========================================================================== */

describe('TC — 文本检测', () => {
  /**
   * TC-01: 文本检测 — 有长文本
   *   tree 含 name="This is page content with >10 chars"
   *   期望: hasTextContent = true
   */
  test('TC-01: 有长文本', () => {
    const snapshot = makeSnapshotWithText([
      'This is page content with >10 chars',
    ]);

    const report = analyzeCoverage(snapshot);
    expect(report.hasTextContent).toBe(true);
  });

  /**
   * TC-02: 文本检测 — 仅有短文本
   *   tree 含 name="OK", label="Hi"（均 < 10 字符）
   *   期望: hasTextContent = false
   */
  test('TC-02: 仅有短文本', () => {
    const snapshot: BrowserAutomationSnapshot = {
      accessibilityTree: {
        name: 'OK',
        label: 'Hi',
        role: 'button',
        children: [
          { name: 'AB', role: 'text' },
        ],
      },
      metadata: { title: '', url: '', nodeCount: 3 },
    };

    const report = analyzeCoverage(snapshot);
    expect(report.hasTextContent).toBe(false);
  });

  /**
   * TC-03: 文本检测 — 空树
   *   期望: hasTextContent = false
   */
  test('TC-03: 空树', () => {
    const report = analyzeCoverage(EMPTY_SNAPSHOT);
    expect(report.hasTextContent).toBe(false);
  });

  /**
   * 额外验证：detectTextContent 直接测试
   */
  test('detectTextContent 直接测试', () => {
    expect(detectTextContent(DEFAULT_SNAPSHOT.accessibilityTree)).toBe(true);
    expect(detectTextContent(null)).toBe(false);
    expect(detectTextContent({ name: 'Hi', role: 'text' })).toBe(false);
    expect(detectTextContent({ name: 'Hello World', role: 'heading' })).toBe(true);
  });
});

/* ===========================================================================
 * §2.4 隐藏元素检测 (HE-01 ~ HE-03)
 * =========================================================================== */

describe('HE — 隐藏元素与文本检测', () => {
  /**
   * HE-01: 隐藏元素 > 50% — 触发文本降级
   *   hiddenOrPresentationRatio > 0.5 且 hasTextContent = true
   *   期望: strategy = 'js_innertext'
   *
   *   构造：2 visible（含长文本）+ 4 hidden（aria-hidden=true）
   *   total nodes = root + 2 + 4 = 7
   *   hiddenCount = 4, hiddenOrPresentationRatio = 4/7 ≈ 0.571 > 0.5
   *   名带长文本 → hasTextContent=true
   *   coverage ≥ 60% + hiddenRatio > 0.5 + hasTextContent → js_innertext
   */
  test('HE-01: 隐藏元素 > 50% — 触发文本降级', () => {
    const tree = {
      name: 'root',
      role: 'RootWebArea',
      children: [
        { name: 'This is visible content with enough length', role: 'heading' },
        { name: 'More visible text for coverage detection', role: 'paragraph' },
        { name: 'Hid1', role: 'presentation', 'aria-hidden': true },
        { name: 'Hid2', role: 'presentation', 'aria-hidden': true },
        { name: 'Hid3', role: 'presentation', 'aria-hidden': true },
        { name: 'Hid4', role: 'presentation', 'aria-hidden': true },
      ],
    };

    const snapshot: BrowserAutomationSnapshot = {
      accessibilityTree: tree,
      metadata: { title: 'Test', url: '', nodeCount: 6 },
    };

    const report = analyzeCoverage(snapshot);

    // hiddenOrPresentationRatio = 4/7 ≈ 0.571 > 0.5
    expect(report.hiddenOrPresentationRatio).toBeGreaterThan(0.5);
    // hasTextContent: visible 节点文本 > 10 char → true
    expect(report.hasTextContent).toBe(true);
    // hiddenRatio > 0.5 + hasTextContent → 'js_innertext'
    expect(report.recommendedStrategy).toBe('js_innertext');
  });

  /**
   * HE-02: 隐藏元素 ≤ 50% — 不触发隐藏降级
   *   hiddenOrPresentationRatio ≤ 0.5
   *   期望: 不会因为 hidden 触发 js_innertext，按 coverage 正常判断
   */
  test('HE-02: 隐藏元素 ≤ 50% — 不触发隐藏降级', () => {
    const snapshot = makeSnapshotWithHidden(6, 3);
    // total = 10 (root + 6 visible + 3 hidden)
    // hiddenOrPresentationRatio = 3/10 = 0.3 ≤ 0.5
    // name="Visible X"/"Hidden X" all < 10 → hasTextContent=false
    // coverage ≥ 0.6 但 !hasTextContent → screenshot_visual
    const report = analyzeCoverage(snapshot);

    expect(report.hiddenOrPresentationRatio).toBeLessThanOrEqual(0.5);
  });

  /**
   * HE-03: 无隐藏元素 — 正常行为
   */
  test('HE-03: 无隐藏元素 — 正常行为', () => {
    const snapshot = makeSnapshotWithNodeCount(10);
    const report = analyzeCoverage(snapshot);

    // makeSnapshotWithNodeCount 创建无 hidden 节点
    // hiddenOrPresentationRatio = 0/11 = 0
    expect(report.hiddenOrPresentationRatio).toBe(0);
  });
});

/* ===========================================================================
 * 工具函数独立测试
 * =========================================================================== */

describe('工具函数独立测试', () => {
  test('countAxNodes — 递归统计', () => {
    // DEFAULT_SNAPSHOT: root + 5 children = 6
    expect(countAxNodes(DEFAULT_SNAPSHOT.accessibilityTree)).toBe(6);
    expect(countAxNodes(null)).toBe(0);
    expect(countAxNodes({ name: 'single', role: 'text' })).toBe(1);
  });

  test('countAxNodes — 深度递归', () => {
    const deepTree = {
      name: 'root',
      role: 'RootWebArea',
      children: [
        {
          name: 'A',
          role: 'group',
          children: [
            { name: 'A1', role: 'button' },
            {
              name: 'A2',
              role: 'group',
              children: [
                { name: 'A2a', role: 'text' },
              ],
            },
          ],
        },
        { name: 'B', role: 'heading' },
      ],
    };

    expect(countAxNodes(deepTree)).toBe(6); // root + A + A1 + A2 + A2a + B
  });

  test('countAxNodes — 非对象兜底', () => {
    expect(countAxNodes('not an object' as any)).toBe(0);
    expect(countAxNodes(undefined as any)).toBe(0);
  });

  test('countHiddenNodes — 递归查找 aria-hidden=true', () => {
    const tree = {
      name: 'root',
      role: 'RootWebArea',
      children: [
        { name: 'v1', role: 'button' },
        { name: 'h1', role: 'presentation', 'aria-hidden': true },
        {
          name: 'group',
          role: 'group',
          children: [
            { name: 'h2', role: 'text', 'aria-hidden': true },
            { name: 'v2', role: 'text' },
          ],
        },
      ],
    };

    expect(countHiddenNodes(tree)).toBe(2);
  });

  test('countHiddenNodes — 空树', () => {
    expect(countHiddenNodes(null)).toBe(0);
    expect(countHiddenNodes(undefined as any)).toBe(0);
  });

  test('estimateDomFromHtml — HTML 标签统计', () => {
    const html1 = '<div><p><span></span></p><a></a></div>';
    expect(estimateDomFromHtml(html1)).toBe(4);

    const html2 = simpleHtml(htmlWithTags(50));
    // 50 divs + 4 wrapper (html,head,title,body) = 54
    expect(estimateDomFromHtml(html2)).toBe(54);

    expect(estimateDomFromHtml('')).toBe(0);
  });

  test('recommendStrategy — 全覆盖 + 有文本 → ax_tree', () => {
    const strategy = recommendStrategy(0.8, 0, true);
    expect(strategy).toBe('ax_tree');
  });

  test('recommendStrategy — 全覆盖 + 无文本 → screenshot_visual', () => {
    const strategy = recommendStrategy(0.8, 0, false);
    expect(strategy).toBe('screenshot_visual');
  });

  test('recommendStrategy — 隐藏过多 + 有文本 → js_innertext', () => {
    const strategy = recommendStrategy(0.8, 0.6, true);
    expect(strategy).toBe('js_innertext');
  });

  test('recommendStrategy — 覆盖率 < 60% + 有文本 → js_innertext', () => {
    const strategy = recommendStrategy(0.4, 0, true);
    expect(strategy).toBe('js_innertext');
  });

  test('recommendStrategy — 覆盖率 < 60% + 无文本 → screenshot_visual', () => {
    const strategy = recommendStrategy(0.4, 0, false);
    expect(strategy).toBe('screenshot_visual');
  });

  test('recommendStrategy — 覆盖率 0 + 无文本 → screenshot_visual', () => {
    const strategy = recommendStrategy(0, 1, false);
    expect(strategy).toBe('screenshot_visual');
  });

  test('recommendStrategy — 覆盖率 ≥ 60% + 隐藏过多 + 无文本 → screenshot_visual', () => {
    // hiddenRatio > 0.5 但 !hasTextContent → 跳过隐藏分支
    // coverage ≥ 60% + !hasTextContent → screenshot_visual
    const strategy = recommendStrategy(0.75, 0.55, false);
    expect(strategy).toBe('screenshot_visual');
  });
});

/* ===========================================================================
 * §2.2 SPA Hydration 检测 (SPA-01 ~ SPA-06)
 * =========================================================================== */

describe('SPA — SPA Hydration 检测', () => {
  /**
   * SPA-01: SPA 未 Hydrate — Loading 占位符
   *   nodeCount=2 (< MIN_TRUSTED_NODES=5), html 含 "Loading..."
   *   期望: coverageRatio=0, strategy='screenshot_visual'
   */
  test('SPA-01: SPA 未 Hydrate — Loading 占位符', () => {
    const snapshot = makeSnapshotWithNodeCount(1);
    const html = simpleHtml('<div>Loading...</div>');

    const report = analyzeCoverage(snapshot, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * SPA-02: SPA 未 Hydrate — 省略号占位符
   *   nodeCount=3 (< 5)
   *   期望: coverageRatio=0
   */
  test('SPA-02: SPA 未 Hydrate — 省略号占位符', () => {
    const snapshot = makeSnapshotWithNodeCount(2);
    const html = simpleHtml('<div>Loading...</div>');

    const report = analyzeCoverage(snapshot, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * SPA-03: SPA 未 Hydrate — Please wait
   *   nodeCount=1 (< 5)
   *   期望: coverageRatio=0
   */
  test('SPA-03: SPA 未 Hydrate — Please wait', () => {
    const snapshot = makeSnapshotWithNodeCount(0);
    const html = simpleHtml('<div>Please wait</div>');

    const report = analyzeCoverage(snapshot, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * SPA-04: 非 SPA 页面 — 节点少但无 Loading 签名
   *   nodeCount=3 (< 5), html 无 SPA Loading 签名，不强制降级
   *   期望: 正常计算覆盖率
   *
   *   makeSnapshotWithNodeCount(3) → children names "Node X" (<10) → hasTextContent=false
   *   coverage ≥ 60% + !hasTextContent → screenshot_visual
   */
  test('SPA-04: 非 SPA 页面 — 节点少但无 Loading 签名', () => {
    const snapshot = makeSnapshotWithNodeCount(3);
    const html = simpleHtml('<div><p>Content here</p></div>');

    const report = analyzeCoverage(snapshot, html);

    // HTML 标签: html,head,title,body,div,p = 6
    // accessible: root + 3 children = 4
    // totalDomElements = max(3, 6) = 6
    // coverage = 4/6 ≈ 0.667 ≥ 0.6
    // hasTextContent: "Node X" < 10 chars → false
    // coverage ≥ 60% + !hasTextContent → screenshot_visual
    expect(report.totalDomElements).toBe(6);
    expect(report.coverageRatio).toBeGreaterThanOrEqual(0.6);
    expect(report.hasTextContent).toBe(false);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * SPA-05: nodeCount > MIN_TRUSTED_NODES 即使有 Loading 也正常处理
   *   nodeCount=9 (≥ 5) 即使 HTML 含 "Loading..." 也不强制降级
   *
   *   9 children + root = 10 accessible
   *   html: html,head,title,body,div = 5 tags
   *   nodeCount=9 > estimateDom=5, totalDomElements = max(9, 5) = 9
   *   coverage = min(1, 10/9) = 1
   *   正常计算（不降级）
   */
  test('SPA-05: nodeCount > MIN_TRUSTED_NODES 即使有 Loading 也正常处理', () => {
    const snapshot = makeSnapshotWithNodeCount(9);
    const html = simpleHtml('<div>Loading...</div>');

    const report = analyzeCoverage(snapshot, html);

    expect(report.accessibleElements).toBe(10);
    expect(report.totalDomElements).toBe(9);
    // coverage = min(1, 10/9) = 1 — 不强制 0
    expect(report.coverageRatio).toBe(1);
  });

  /**
   * SPA-06: nodeCount = 0 — 空 snapshot
   *   期望: 走覆盖率 0% 逻辑
   */
  test('SPA-06: nodeCount = 0 空 snapshot', () => {
    const report = analyzeCoverage(EMPTY_SNAPSHOT);

    expect(report.coverageRatio).toBe(0);
    expect(report.accessibleElements).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });
});

/* ===========================================================================
 * §2.3 反爬检测 (AC-01 ~ AC-10)
 * =========================================================================== */

describe('AC — 反爬检测', () => {
  /**
   * AC-01: Cloudflare classic
   */
  test('AC-01: Cloudflare classic', () => {
    const html = '<html><body>Just a moment...</body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-02: reCAPTCHA v3
   */
  test('AC-02: reCAPTCHA v3', () => {
    const html = '<html><head><script src="https://www.google.com/recaptcha/api.js"></script></head><body></body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-03: DataDome
   */
  test('AC-03: DataDome', () => {
    const html = '<html><body><script>ddome-12345</script></body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-04: Kasada
   */
  test('AC-04: Kasada', () => {
    const html = '<html><body>kaptcha verification</body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-05: Cloudflare Turnstile
   */
  test('AC-05: Cloudflare Turnstile', () => {
    const html = '<html><body><div id="cf-turnstile" data-sitekey="xxx"></div><script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-06: 'robot' 在反爬上下文中 — meta robots
   */
  test('AC-06: robot 在 meta robots 上下文中', () => {
    const html = '<html><head><meta name="robots" content="noindex"></head><body>This site uses robots.txt to block AI crawlers</body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-07: 'robot' 在反爬上下文中 — User-Agent
   */
  test('AC-07: robot 在 User-Agent 上下文中', () => {
    const html = '<html><head><meta name="User-Agent" content="*"></head><body>Disallow: /for-robots/ Only allow robots to access public pages</body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-08: 'robot' 在正常内容中（假阳性消除）
   *   纯 title "AI Robot Technology Blog" 不应触发反爬
   */
  test('AC-08: robot 在正常内容中不触发反爬', () => {
    const html = '<html><head><title>AI Robot Technology Blog</title></head><body><p>This article discusses robotics and AI automation in modern manufacturing.</p><p>Our robot fleet achieved 99.9% uptime last quarter.</p></body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    // 不应触发反爬降级——正常计算覆盖率
    expect(report.coverageRatio).toBeGreaterThan(0);
    expect(report.recommendedStrategy).not.toBe('screenshot_visual');
  });

  /**
   * AC-09: 'captcha' 在正常页面中（直接匹配，接受假阳性）
   */
  test('AC-09: captcha 直接触发反爬', () => {
    const html = '<html><body><div>Please complete the captcha to continue</div></body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });

  /**
   * AC-10: 多重反爬特征叠加
   */
  test('AC-10: 多重反爬特征叠加', () => {
    const html = '<html><body><p>Just a moment...</p><script src="https://www.google.com/recaptcha/api.js"></script><p>Checking your browser before accessing the site. This process is automatic. recaptcha will verify you are not a robot.</p></body></html>';
    const report = analyzeCoverage(DEFAULT_SNAPSHOT, html);

    // 触发一次降级即可
    expect(report.coverageRatio).toBe(0);
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });
});

/* ===========================================================================
 * §2.4 HE-02 补充: 隐藏 > 50% + 无文本 → screenshot_visual
 * =========================================================================== */

describe('HE (§2.4 补充)— 隐藏 + 文本组合', () => {
  test('HE-02 补充: 隐藏 > 50% + 无文本 → screenshot_visual', () => {
    // 构造: 2 visible (短名 < 10) + 5 hidden
    const tree = {
      name: 'root',
      role: 'RootWebArea',
      children: [
        { name: 'V1', role: 'text' },
        { name: 'V2', role: 'text' },
        { name: 'H1', role: 'presentation', 'aria-hidden': true },
        { name: 'H2', role: 'presentation', 'aria-hidden': true },
        { name: 'H3', role: 'presentation', 'aria-hidden': true },
        { name: 'H4', role: 'presentation', 'aria-hidden': true },
        { name: 'H5', role: 'presentation', 'aria-hidden': true },
      ],
    };
    const snapshot: BrowserAutomationSnapshot = {
      accessibilityTree: tree,
      metadata: { title: '', url: '', nodeCount: 7 },
    };
    const report = analyzeCoverage(snapshot);

    // total = 8 (root + 7 children), hidden = 5
    // hiddenRatio = 5/8 = 0.625 > 0.5
    expect(report.hiddenOrPresentationRatio).toBeGreaterThan(0.5);
    // 所有 name < 10 → hasTextContent=false
    // coverage >= 0.6 + hidden > 0.5 + !hasTextContent → 跳过隐藏分支 → screenshot_visual
    expect(report.recommendedStrategy).toBe('screenshot_visual');
  });
});