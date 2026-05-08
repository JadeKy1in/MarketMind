/**
 * =============================================================================
 * VLM Adapter — Domain Type Definitions
 * =============================================================================
 * Copyright (c) 2026 SkillFoundry Contributors
 * SPDX-License-Identifier: MIT
 *
 * 本模块定义 VLM (Vision Language Model) 适配层的所有类型接口。
 * 遵循 DEC-2026-0504-001 决议：
 *   - Q1 决议 C: VlmBackend 为可插拔接口，默认提供 MockBackend
 *   - Q2 决议 B: ImagePreprocessor 使用纯 JS Buffer 操作，无 sharp 依赖
 *   - Q3 决议 B: VLM Adapter 作为 browser-automation 子模块，非顶层 Skill
 *
 * @module vlm-types
 */

/* ===========================================================================
 * 1. VLM Backend 抽象接口（可插拔）
 * =========================================================================== */

/** VLM Backend 返回的原始响应 */
export interface VlmRawResponse {
  /** LLM 原始文本输出 */
  rawContent: string;
  /** Token 用量统计 */
  tokenUsage: { input: number; output: number };
  /** 后端响应延迟（毫秒） */
  latencyMs: number;
}

/**
 * VLM Backend 抽象接口。
 *
 * 支持多种视觉模型后端：
 *   - GPT-4V (Azure OpenAI)
 *   - Claude 3 Vision
 *   - 本地模型 (LLaVA, Qwen-VL)
 *   - MockBackend（单元测试用）
 */
export interface VlmBackend {
  /**
   * 分析截图并返回结构化结果
   * @param base64Image - base64 编码的截图数据
   * @param prompt      - 分析指令（可被重试策略修改）
   * @param schema      - JSON Schema 声明期望输出结构
   * @returns VLM 原始响应
   */
  analyze(
    base64Image: string,
    prompt: string,
    schema: JsonSchema,
  ): Promise<VlmRawResponse>;
}

/* ===========================================================================
 * 2. JSON Schema 类型（轻量级，无外部依赖）
 * =========================================================================== */

/** 轻量级 JSON Schema 定义——调用方必须显式声明期望结构 */
export interface JsonSchema {
  type: 'object';
  properties: Record<string, JsonSchemaProperty>;
  required: string[];
}

/** Schema 属性定义 */
export interface JsonSchemaProperty {
  type: 'string' | 'number' | 'boolean' | 'array' | 'object';
  description?: string;
  items?: JsonSchemaProperty;       // 数组子项类型
  enum?: string[];                  // 枚举值限制
  properties?: Record<string, JsonSchemaProperty>; // 嵌套对象
}

/* ===========================================================================
 * 3. 图片预处理配置与结果
 * =========================================================================== */

/** 图片预处理器配置 */
export interface PreprocessorConfig {
  /** 最大宽度（默认 1024px） */
  maxWidth: number;
  /** 最大高度（默认 1024px） */
  maxHeight: number;
  /** JPEG 质量（0-100，默认 85） */
  quality: number;
  /** 输出格式（默认 'jpeg'，更小体积） */
  format: 'jpeg' | 'png';
  /** 目标最大字节数（默认 512KB） */
  targetMaxBytes: number;
}

/** 预处理后的图片 */
export interface PreprocessedImage {
  /** 处理后的 base64 数据 */
  base64: string;
  /** 原始大小（字节） */
  originalSizeBytes: number;
  /** 处理后大小（字节） */
  processedSizeBytes: number;
  /** 压缩比（> 1 表示有压缩） */
  compressionRatio: number;
  /** 处理后宽度（像素） */
  width: number;
  /** 处理后高度（像素） */
  height: number;
  /** 实际使用的 JPEG 质量 */
  qualityUsed: number;
  /** 输出格式 */
  format: 'jpeg' | 'png';
}

/* ===========================================================================
 * 4. VLM Adapter 配置与结果
 * =========================================================================== */

/** VLM Adapter 完整配置 */
export interface VlmAdapterConfig {
  /** 视觉后端实例 */
  backend: VlmBackend;
  /** JSON Schema——强制调用方声明期望结构 */
  schema: JsonSchema;
  /** 系统级指令（可选） */
  systemPrompt?: string;
  /** 最大重试次数（默认 3） */
  maxRetries: number;
  /** 重试间隔毫秒（默认 1000ms） */
  retryDelayMs: number;
  /** VLM 温度参数（默认 0.1） */
  temperature?: number;
  /** 最大输出 Token（默认 4096） */
  maxTokens?: number;
  /** 预处理配置（可选） */
  preprocessing?: PreprocessorConfig;
}

/** VLM 分析结果（结构化输出） */
export interface VlmAnalysisResult {
  /** 提取的纯文本 */
  textContent: string;
  /** 按 schema 解析后的结构化数据 */
  structuredData: Record<string, any>;
  /** 置信度（0.0 ~ 1.0） */
  confidence: number;
  /** 原始响应（调试用） */
  rawResponse: string;
  /** Token 用量 */
  tokenUsage: { input: number; output: number };
  /** 总延迟（毫秒） */
  latencyMs: number;
  /** 最终使用的重试次数 */
  attemptsUsed: number;
  /** 错误信息（可选） */
  error?: string;
}

/* ===========================================================================
 * 5. 校验结果
 * =========================================================================== */

/** VLM 响应校验结果 */
export interface ValidationResult {
  /** 总体是否通过 */
  valid: boolean;
  /** 解析后的对象（可能部分有效） */
  parsed: Record<string, any> | null;
  /** Layer 1：语法校验通过？ */
  syntaxOk: boolean;
  /** Layer 2：Schema 校验通过？ */
  schemaOk: boolean;
  /** Layer 3：语义校验通过？ */
  semanticOk: boolean;
  /** Layer 4：反幻校验通过？ */
  hallucinationDetected: boolean;
  /** 所有校验错误的明细 */
  errors: string[];
  /** Schema required 但缺失的字段列表 */
  missingFields: string[];
}

/* ===========================================================================
 * 6. VLM 异常类型层次
 * =========================================================================== */

/** VLM 异常基类 */
export abstract class VlmError extends Error {
  constructor(
    message: string,
    /** 错误类别 */
    public readonly category: 'validation' | 'backend' | 'preprocess' | 'exhausted',
    /** 是否可恢复（可重试） */
    public readonly recoverable: boolean,
  ) {
    super(message);
    this.name = 'VlmError';
  }
}

/** 校验失败——包含缺失字段明细 */
export class VlmValidationError extends VlmError {
  public readonly missingFields: string[];
  public readonly parsed: Record<string, any> | null;

  constructor(msg: string, missingFields?: string[], parsed?: Record<string, any> | null) {
    super(msg, 'validation', true);
    this.name = 'VlmValidationError';
    this.missingFields = missingFields ?? [];
    this.parsed = parsed ?? null;
  }
}

/** VLM 后端调用异常 */
export class VlmBackendError extends VlmError {
  constructor(msg: string) {
    super(msg, 'backend', true);
    this.name = 'VlmBackendError';
  }
}

/**
 * VLM 速率限制异常（HTTP 429）——可重试，需更长的指数退避。
 * 携带 retryAfterMs（来自 Retry-After 头或默认值）供上层编排器决策。
 */
export class VlmRateLimitError extends VlmBackendError {
  /**
   * @param msg           - 错误描述
   * @param retryAfterMs  - 服务端建议的等待时间（毫秒），默认 5000
   */
  constructor(msg: string, public readonly retryAfterMs: number = 5000) {
    super(msg);
    this.name = 'VlmRateLimitError';
  }
}

/**
 * VLM 请求参数异常（HTTP 4xx，除 429 外）——通常不可恢复。
 * 如 400（参数错误）、401（认证失败）、403（权限不足）、404（端点不存在）。
 */
export class VlmRequestError extends VlmBackendError {
  public readonly statusCode: number;
  constructor(msg: string, statusCode: number) {
    super(msg);
    this.name = 'VlmRequestError';
    this.statusCode = statusCode;
  }
}

/** 预处理异常（不可恢复） */
export class VlmPreprocessError extends VlmError {
  constructor(msg: string) {
    super(msg, 'preprocess', false);
    this.name = 'VlmPreprocessError';
  }
}

/** 幻觉检测异常——VLM 拒绝分析或生成自指语句（不可恢复） */
export class VlmHallucinationError extends VlmError {
  constructor(msg: string) {
    super(msg, 'validation', false);
    this.name = 'VlmHallucinationError';
  }
}

/** 重试耗尽异常——所有重试路径均已尝试 */
export class VlmExhaustedError extends VlmError {
  /** 尝试次数 */
  public readonly attempts: number;
  /** 最后一次尝试的部分解析结果（可能为 null） */
  public readonly truncatedResult: Record<string, any> | null;

  constructor(details: {
    attempts: number;
    lastError: string;
    truncatedResult?: Record<string, any> | null;
  }) {
    super(
      `VLM exhausted after ${details.attempts} attempts: ${details.lastError}`,
      'exhausted',
      false,
    );
    this.name = 'VlmExhaustedError';
    this.attempts = details.attempts;
    this.truncatedResult = details.truncatedResult ?? null;
  }
}

/* ===========================================================================
 * 7. RestVlmBackend 配置类型
 * =========================================================================== */

/**
 * RestVlmBackend 配置（纯 Fetch 实现）。
 *
 * 设计原则（Phase 2 强制补丁）：
 *   - endpoint 从 VLM_ENDPOINT 环境变量读取
 *   - apiKey 从 VLM_API_KEY 环境变量读取
 *   - timeoutMs 默认 60000ms（AbortSignal.timeout）
 *   - customHeaders 预留 Azure api-version 等扩展槽位
 *   - 零外部依赖
 */
export interface RestBackendConfig {
  /** OpenAI-compatible 端点 URL（例如 https://api.openai.com/v1/chat/completions） */
  endpoint: string;
  /** API Key（Bearer token） */
  apiKey: string;
  /** 物理网络超时毫秒（默认 60000） */
  timeoutMs: number;
  /** 自定义请求头扩展槽位（Azure api-version 等） */
  customHeaders?: Record<string, string>;
}

/** 默认 RestBackendConfig 常量 */
export const DEFAULT_REST_BACKEND_CONFIG: Partial<RestBackendConfig> = {
  timeoutMs: 60000,
};

/* ===========================================================================
 * 8. 与 adapter.ts 的挂接类型
 * =========================================================================== */

/** VlmAdapterOption——BrowserAutomationAdapter 构造函数注入（零侵入） */
export interface VlmAdapterOption {
  /** VLM Adapter 实例；null = 禁用 VLM 解析 */
  adapter: VlmAdapter | null;
}

/**
 * VLM Adapter 主接口——供 BrowserAutomationAdapter 调用。
 *
 * 设计原则：
 *   - analyze() 接收 base64 截图 + schema，返回结构化结果
 *   - 内部封装预处理+校验+重试全链路
 *   - 不对 adapter.ts 暴露内部细节
 */
export interface VlmAdapter {
  /**
   * 分析截图
   * @param base64 - base64 编码的截图数据
   * @param schema - JSON Schema 声明期望输出结构（可选，若不传则使用 config.schema）
   * @returns VLM 分析结果
   * @throws {VlmPreprocessError} 预处理失败
   * @throws {VlmBackendError} 后端调用失败
   * @throws {VlmExhaustedError} 所有重试路径耗尽
   */
  analyze(
    base64: string,
    schema?: JsonSchema,
  ): Promise<VlmAnalysisResult>;
}

/** 默认预处理配置常量 */
export const DEFAULT_PREPROCESSOR_CONFIG: PreprocessorConfig = {
  maxWidth: 1024,
  maxHeight: 1024,
  quality: 85,
  format: 'jpeg',
  targetMaxBytes: 512 * 1024, // 512KB
};

/** 默认 VLM Adapter 配置常量 */
export const DEFAULT_VLM_ADAPTER_CONFIG: Partial<VlmAdapterConfig> = {
  maxRetries: 3,
  retryDelayMs: 1000,
  temperature: 0.1,
  maxTokens: 4096,
  preprocessing: DEFAULT_PREPROCESSOR_CONFIG,
};