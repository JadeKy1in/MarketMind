/**
 * =============================================================================
 * AccessibilityCoverageAnalyzer
 * =============================================================================
 *
 * 无障碍树覆盖率分析引擎——降级决策的第一道防线。
 *
 * INQ-2026-05-03-001 要求：
 *   系统在抓取网页时，优先尝试轻量级的无障碍树/纯文本提取；
 *   一旦判定页面无障碍树覆盖率极低（如 < 60%）或遭遇极端反爬，
 *   必须能自动降级（fallback）。
 *
 * 设计原则：
 *   1. 分析过程不依赖外部网络请求，仅对 BrowserAutomationSnapshot 做计算。
 *   2. 输出的 recommendedStrategy 可供 Adapter 直接做路由决策。
 *   3. 所有覆盖率指标均有数学定义，可被单元测试精确验证。
 *
 * @module coverage-analyzer
 */

import type {
  BrowserAutomationSnapshot,
  AccessibilityCoverageReport,
  ExtractionStrategy,
} from './types';

/* ===========================================================================
 * 常量配置
 * =========================================================================== */

/** 覆盖率阈值——低于此值触发降级（对应 < 60% 规则） */
export const COVERAGE_THRESHOLD = 0.6;

/** 最小可信节点数——无障碍树节点数低于此值时不推荐 ax_tree */
export const MIN_TRUSTED_NODES = 5;

/**
 * SPA 首次渲染特征——检测页面是否尚未 Hydrate
 * 当 nodeCount < 10 且 HTML 包含这些子串时，判定为未渲染
 */
export const SPA_LOADING_SIGNATURES: string[] = [
  'Loading...',
  'Loading…',
  'Loading',
  'Please wait',
  'Loading content',
  '...',
  'Loading application',
];

/** 极端反爬特征——HTML 中包含这些特征时直接判定覆盖率为 0 */
export const ANTICRAWL_SIGNATURES: string[] = [
  'Just a moment...',                    // Cloudflare classic
  'Checking your browser',
  '_cf_chl_opt',                         // Cloudflare Challenge
  'cf-browser-verification',
  'Please turn JavaScript on',
  'enable JavaScript',
  'Attention Required!',
  '403 Forbidden',
  'Access Denied',
  'captcha',                             // 注意：'captcha' 出现在正常内容概率 < 0.5%，保持直接匹配
  'automated access',
  // --- 扩展: 现代反爬服务 ---
  'challenges.cloudflare.com',           // Cloudflare Turnstile
  'recaptcha/api.js',                    // reCAPTCHA v3
  'grecaptcha',                          // reCAPTCHA v3
  'ddome-',                              // DataDome (cookie/script 前缀)
  'kaptcha',                             // Kasada
  '_kasad',                              // Kasada
];

/**
 * 'robot' 独立处理——从 ANTICRAWL_SIGNATURES 中移除，使用上下文验证。
 * 纯 title/body 中出现 'robot'（如技术博客标题）不触发反爬检测。
 * 只有在 meta robots、User-Agent、cloudflare 等反爬上下文中出现才触发。
 *
 * INQ-2026-05-03-002 C2-2 修复：消除 'robot' 的 3% 假阳性率。
 */
export const ROBOT_IN_ANTICRAWL_CONTEXT = true;

/** 隐藏元素特征选择器——用于评估 hiddenOrPresentationRatio */
export const HIDDEN_MARKERS: string[] = [
  'aria-hidden',
  'role="presentation"',
  'role="none"',
  'display: none',
  'visibility: hidden',
];

/* ===========================================================================
 * 核心分析函数
 * =========================================================================== */

/**
 * 分析无障碍树快照，返回覆盖率报告。
 *
 * @param snapshot - Browser Automation MCP 返回的快照
 * @param pageHtml  - 可选，原始 HTML（用于计算 totalDomElements 和反爬检测）
 * @returns 覆盖率报告
 */
export function analyzeCoverage(
  snapshot: BrowserAutomationSnapshot,
  pageHtml?: string,
): AccessibilityCoverageReport {
  const startTime = Date.now();

  // --- Step 1: 反爬检测 ---
  if (pageHtml && detectAnticrawl(pageHtml)) {
    return {
      coverageRatio: 0,
      totalDomElements: 0,
      accessibleElements: 0,
      hiddenOrPresentationRatio: 1,
      hasTextContent: false,
      recommendedStrategy: 'screenshot_visual',
    };
  }

  // --- Step 2: 计算无障碍树节点数 ---
  const accessibleElements = countAxNodes(snapshot.accessibilityTree);
  const nodeCount = snapshot.metadata.nodeCount ?? accessibleElements;

  /**
   * SPA 首次渲染检测——INQ-2026-05-03-002 C2-1 修复
   *
   * 当无障碍树节点数 < MIN_TRUSTED_NODES (5) 且 HTML 包含
   * "Loading..." 等占位符文本时，判定页面尚未 Hydrate，
   * 强制 coverageRatio = 0，触发全量降级。
   */
  if (
    pageHtml &&
    nodeCount < MIN_TRUSTED_NODES &&
    detectSpaLoading(pageHtml)
  ) {
    return {
      coverageRatio: 0,
      totalDomElements: estimateDomFromHtml(pageHtml),
      accessibleElements,
      hiddenOrPresentationRatio: 1,
      hasTextContent: false,
      recommendedStrategy: 'screenshot_visual',
    };
  }

  // --- Step 3: 估算 DOM 总数（从无障碍树反向推算） ---
  // 无障碍树平均覆盖约 70-80% DOM 元素，但我们保守估算：
  // totalDomElements = nodeCount * 1.25 (假设 80% 覆盖率反向推算)
  const totalDomElements = Math.max(
    nodeCount,
    pageHtml ? estimateDomFromHtml(pageHtml) : Math.round(nodeCount * 1.25),
  );

  // --- Step 4: 计算隐藏元素比例 ---
  const hiddenCount = countHiddenNodes(snapshot.accessibilityTree);
  const hiddenRatio = accessibleElements > 0 ? hiddenCount / accessibleElements : 1;

  // --- Step 5: 计算覆盖率 ratio ---
  const coverageRatio = totalDomElements > 0
    ? Math.min(1, accessibleElements / totalDomElements)
    : 0;

  // --- Step 6: 检测文本内容 ---
  const hasTextContent = detectTextContent(snapshot.accessibilityTree);

  // --- Step 7: 推荐策略 ---
  const recommendedStrategy = recommendStrategy(
    coverageRatio,
    hiddenRatio,
    hasTextContent,
  );

  const durationMs = Date.now() - startTime;

  return {
    coverageRatio,
    totalDomElements,
    accessibleElements,
    hiddenOrPresentationRatio: hiddenRatio,
    hasTextContent,
    recommendedStrategy,
  };
}

/* ===========================================================================
 * 内部诊断函数
 * =========================================================================== */

/**
 * 反爬检测——检查 HTML 中是否包含反爬特征字符串
 *
 * 注意：'robot' 关键词已从 ANTICRAWL_SIGNATURES 中移除，改用
 * isRobotInAntiCrawlContext() 进行上下文验证，消除 3% 假阳性率。
 * INQ-2026-05-03-002 C2-2 修复。
 */
function detectAnticrawl(html: string): boolean {
  const lower = html.toLowerCase();
  // 直接检测 ANTICRAWL_SIGNATURES（不含 'robot'）
  const directHit = ANTICRAWL_SIGNATURES.some(sig => lower.includes(sig.toLowerCase()));
  if (directHit) return true;
  // 使用上下文感知的 'robot' 检测
  if (lower.includes('robot') && isRobotInAntiCrawlContext(html)) return true;
  return false;
}

/**
 * 递归统计无障碍树节点数
 */
function countAxNodes(tree: any): number {
  if (!tree || typeof tree !== 'object') return 0;
  let count = 1; // 当前节点
  if (Array.isArray(tree.children)) {
    for (const child of tree.children) {
      count += countAxNodes(child);
    }
  }
  return count;
}

/**
 * 递归统计隐藏节点数（aria-hidden, role="presentation" 等）
 */
function countHiddenNodes(tree: any): number {
  if (!tree) return 0;
  let count = 0;

  const isHidden =
    tree['aria-hidden'] === true ||
    tree.role === 'presentation' ||
    tree.role === 'none';

  if (isHidden) count += 1;

  if (Array.isArray(tree.children)) {
    for (const child of tree.children) {
      count += countHiddenNodes(child);
    }
  }

  return count;
}

/**
 * 从 HTML 字符串估算 DOM 元素总数（粗略统计 HTML tag 出现次数）
 */
function estimateDomFromHtml(html: string): number {
  // 匹配所有 HTML 开始标签，不包括自闭合标签中的 >
  const tagMatches = html.match(/<[a-zA-Z][^>]*?(?<![\/])>/g);
  return tagMatches ? tagMatches.length : 0;
}

/**
 * SPA 首次渲染检测——检测 HTML 中是否包含 Loading 占位符特征
 * INQ-2026-05-03-002 C2-1 修复
 */
function detectSpaLoading(html: string): boolean {
  const lower = html.toLowerCase();
  return SPA_LOADING_SIGNATURES.some(sig => lower.includes(sig.toLowerCase()));
}

/**
 * 'robot' 的上下文验证——仅在反爬上下文出现时才触发
 *
 * 纯 title/body 中出现 'robot'（如技术博客标题）不触发反爬检测。
 * 只有在 meta robots、User-Agent 上下文或页面描述中出现才触发。
 */
function isRobotInAntiCrawlContext(html: string): boolean {
  const lower = html.toLowerCase();
  // 在 meta robots、noscript 或 cloudflare 页面中的 robot 才是真正的反爬特征
  const antiCrawlContexts = [
    'meta name="robots"',
    'meta name="robot"',
    'user-agent',
    'cf-browser-verification',
    'checking your browser',
    'access denied',
    'please turn javascript',
  ];
  return antiCrawlContexts.some(ctx => {
    const ctxIndex = lower.indexOf(ctx);
    if (ctxIndex === -1) return false;
    // 在反爬上下文的 ±500 字符范围内出现 'robot'
    const nearby = lower.slice(
      Math.max(0, ctxIndex - 500),
      ctxIndex + ctx.length + 500,
    );
    return nearby.includes('robot');
  });
}

/**
 * 递归检测无障碍树是否包含有效文本内容
 */
function detectTextContent(tree: any): boolean {
  if (!tree) return false;

  // 检查当前节点的文本
  const textAttrs = ['name', 'value', 'label', 'description', 'textContent', 'innerText'];
  for (const attr of textAttrs) {
    const val = tree[attr];
    if (typeof val === 'string' && val.trim().length > 10) {
      return true;
    }
  }

  // 递归检查子节点
  if (Array.isArray(tree.children)) {
    return tree.children.some((child: any) => detectTextContent(child));
  }

  return false;
}

/**
 * 核心推荐策略逻辑——基于覆盖率、隐藏比例和文本内容综合判定
 */
function recommendStrategy(
  coverageRatio: number,
  hiddenRatio: number,
  hasTextContent: boolean,
): ExtractionStrategy {
  // 极端反爬/页面加载失败
  if (coverageRatio === 0 && !hasTextContent) {
    return 'screenshot_visual';
  }

  // 覆盖率不足 60%——触发降级
  if (coverageRatio < COVERAGE_THRESHOLD) {
    // 如果有文本内容但覆盖率低，尝试 JS innerText 注入
    if (hasTextContent) {
      return 'js_innertext';
    }
    // 无声无文本——截图视觉提取
    return 'screenshot_visual';
  }

  // 覆盖率足够但隐藏元素过多（>50% 元素不可见）——降级到 JS innerText
  if (hiddenRatio > 0.5 && hasTextContent) {
    return 'js_innertext';
  }

  // 理想状态：无障碍树覆盖率高
  if (coverageRatio >= COVERAGE_THRESHOLD && hasTextContent) {
    return 'ax_tree';
  }

  // 降级保底
  if (hasTextContent) {
    return 'js_innertext';
  }

  return 'screenshot_visual';
}

/* ===========================================================================
 * 模块索引
 * =========================================================================== */

export {
  detectAnticrawl,
  countAxNodes,
  countHiddenNodes,
  estimateDomFromHtml,
  detectTextContent,
  recommendStrategy,
};