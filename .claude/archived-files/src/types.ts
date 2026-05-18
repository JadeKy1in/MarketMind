/**
 * =============================================================================
 * BrowserAutomationAdapter — Domain Type Definitions
 * =============================================================================
 *
 * INQ-2026-05-03-001 三轨制降级类型系统:
 *   Track 1 (Primary):  Browser Automation 无障碍树 → 结构化工文本
 *   Track 2 (Lightweight Fallback): Playwright evaluate() → innerText
 *   Track 3 (Heavy Fallback):       Playwright screenshot → base64 视觉数据
 */

/**
 * 轻量级 causationId 生成器，无外部依赖
 */
function createCausationId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/* ===========================================================================
 * 1. 场景上下文
 * =========================================================================== */

export type ScenarioType = 'realtime_request' | 'offline_batch_sync' | 'interactive_operation';

export interface ExtractionContext {
  scenario: ScenarioType;
  causationId: string;
  pageUrl?: string;
  timeoutMs?: number;
  allowScreenshotFallback?: boolean;
  allowScriptInjection?: boolean;
}

export function createDefaultContext(scenario: ScenarioType): ExtractionContext {
  const base: ExtractionContext = {
    scenario,
    causationId: createCausationId(),
    allowScreenshotFallback: true,
    allowScriptInjection: true,
  };

  switch (scenario) {
    case 'realtime_request':
      return { ...base, timeoutMs: 5_000, allowScreenshotFallback: false };
    case 'offline_batch_sync':
      return { ...base, timeoutMs: 30_000 };
    case 'interactive_operation':
      return { ...base, timeoutMs: 10_000 };
  }
}

/* ===========================================================================
 * 2. 提取策略
 * =========================================================================== */

export type ExtractionStrategy =
  | 'ax_tree'
  | 'js_innertext'
  | 'screenshot_visual'
  | 'failed';

export const STRATEGY_TOKEN_ESTIMATES: Record<ExtractionStrategy, {
  avgTokensPerPage: number;
  latencyMs: number;
  vlmRequired: boolean;
}> = {
  'ax_tree':          { avgTokensPerPage: 1_500,  latencyMs: 500,  vlmRequired: false },
  'js_innertext':     { avgTokensPerPage: 4_000,  latencyMs: 1_000, vlmRequired: false },
  'screenshot_visual': { avgTokensPerPage: 20_000, latencyMs: 3_000, vlmRequired: true },
  'failed':           { avgTokensPerPage: 0,      latencyMs: 0,    vlmRequired: false },
};

/* ===========================================================================
 * 3. 无障碍树覆盖率
 * =========================================================================== */

export interface AccessibilityCoverageReport {
  coverageRatio: number;               // 0.0 ~ 1.0
  totalDomElements: number;
  accessibleElements: number;
  hiddenOrPresentationRatio: number;
  hasTextContent: boolean;
  lang?: string;
  recommendedStrategy: ExtractionStrategy;
}

/* ===========================================================================
 * 4. 统一提取结果
 * =========================================================================== */

export interface ExtractionResult {
  strategyUsed: ExtractionStrategy;
  textContent?: string;
  structuredData?: string;
  screenshotBase64?: string;
  coverageReport?: AccessibilityCoverageReport;
  context: ExtractionContext;
  durationMs: number;
  error?: string;
}

/* ===========================================================================
 * 5. MCP 工具契约接口
 * =========================================================================== */

export interface BrowserAutomationInput {
  /** URL 已变为可选——当 navigate 由 adapter 统一管理后，getSnapshot 只需 waitTime */
  url?: string;
  waitForSelector?: string;
  waitTime?: number;
}

export interface BrowserAutomationSnapshot {
  accessibilityTree: any;
  metadata: { title?: string; url?: string; nodeCount: number };
}

export interface PlaywrightEvaluateInput {
  script: string;
}

export interface PlaywrightEvaluateResult {
  result: any;
  logs?: string[];
}

export interface PlaywrightScreenshotInput {
  name: string;
  url: string;
  fullPage?: boolean;
  storeBase64?: boolean;
}

export interface PlaywrightScreenshotResult {
  base64?: string;
  filePath?: string;
}

/* ===========================================================================
 * 6. 交互操作
 * =========================================================================== */

export type InteractionType = 'click' | 'fill' | 'select' | 'hover' | 'scroll' | 'press_key';

export interface InteractionInput {
  type: InteractionType;
  selector: string;
  value?: string;
  delayBeforeMs?: number;
}

export interface InteractionResult {
  success: boolean;
  interaction: InteractionInput;
  snapshotAfter?: BrowserAutomationSnapshot;
  error?: string;
}