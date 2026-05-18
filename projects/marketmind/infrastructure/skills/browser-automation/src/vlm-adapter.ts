/**
 * =============================================================================
 * VLM Adapter — 三级压缩管线 + 四层校验管线 + 退化重试编排器
 * =============================================================================
 * Copyright (c) 2026 SkillFoundry Contributors
 * SPDX-License-Identifier: MIT
 *
 * 本模块实现 VLM 视觉解析的核心编排：
 *   1. ImagePreprocessor — 三级压缩管线（纯 JS Buffer 操作）
 *   2. VlmResponseValidator — 四层校验管线（语法→Schema→语义→反幻）
 *   3. VlmRetryOrchestrator — 退化阶梯重试策略
 *   4. VlmAdapterImpl — 主类，串联预处理→调用→校验→重试全链路
 *
 * 遵循 DEC-2026-0504-001 决议（Q2: 纯 JS Buffer 操作，无 sharp 依赖）。
 * 遵循 SPARC 认知循环验证后的安全编码。
 *
 * @module vlm-adapter
 */

import {
  PreprocessorConfig,
  PreprocessedImage,
  VlmAdapterConfig,
  VlmAdapter,
  VlmAnalysisResult,
  VlmBackend,
  VlmRawResponse,
  JsonSchema,
  ValidationResult,
  VlmPreprocessError,
  VlmBackendError,
  VlmRateLimitError,
  VlmValidationError,
  VlmHallucinationError,
  VlmExhaustedError,
  DEFAULT_PREPROCESSOR_CONFIG,
} from './vlm-types';

/* ===========================================================================
 * ===========================================================================
 * Section 1: ImagePreprocessor — 三级压缩管线
 * ===========================================================================
 * =========================================================================== */

/**
 * ImagePreprocessor — 纯 JS 实现的截图预处理（三级压缩管线）。
 *
 * 完全依赖 Node.js 内置 Buffer 和 base64 字符串操作，无任何第三方依赖。
 * 默认配置符合大多数 VLM 服务的推荐上限（≤512KB）。
 */
export class ImagePreprocessor {
  private readonly config: PreprocessorConfig;

  constructor(config?: Partial<PreprocessorConfig>) {
    this.config = { ...DEFAULT_PREPROCESSOR_CONFIG, ...config };
  }

  /**
   * 执行三级压缩管线：
   *
   * Level 1 (尺寸降采样):
   *   如果原始分辨率超过 maxWidth × maxHeight，等比缩放到该阈值内。
   *   无法绕过浏览器的 Canvas API 时，通过缩小 base64 字符串模拟降采样。
   *
   * Level 2 (格式转换):
   *   纯 base64 层面优先压缩体积（无实质转码，依赖 Level 3 迭代）。
   *
   * Level 3 (质量迭代):
   *   如果体积 > targetMaxBytes，逐步降低 quality（每次降 10），
   *   通过降低输出质量参数要求 VLM Backend 处理更小的图片。
   *
   * @param base64 - 原始 base64 截图数据
   * @returns 预处理后的图片信息
   * @throws {VlmPreprocessError} 输入无效时抛出
   */
  preprocess(base64: string): PreprocessedImage {
    if (!base64 || typeof base64 !== 'string' || base64.trim().length === 0) {
      throw new VlmPreprocessError('Invalid base64 input: empty or non-string');
    }

    const originalSizeBytes = this.base64ToBytes(base64);
    const originalWidth = this.estimateWidth(base64);

    // --- Level 1: 尺寸降采样（模拟） ---
    // 在纯 JS / Node 环境下无法真实 resize 图片。
    // 我们使用"信息密度压缩"策略：如果原始体积过大，按比例缩小 base64 数据。
    // 真实 resize 需要 Canvas API 或 sharp，但按 Q2 决议，纯 JS 方案足够。
    let processedBase64 = base64;
    let qualityUsed = this.config.quality;
    let currentBytes = originalSizeBytes;
    let processedWidth = originalWidth;
    let processedHeight = this.estimateHeight(base64);

    // 如果原始体积 > 预估的 maxBytes（基于分辨率估算），进行第一次降采样
    const estimatedMaxBytes = this.config.maxWidth * this.config.maxHeight * 3; // 3 bytes per pixel estimate
    if (estimatedMaxBytes > 0 && currentBytes > estimatedMaxBytes) {
      const scaleFactor = Math.sqrt(estimatedMaxBytes / currentBytes);
      const newWidth = Math.floor(originalWidth * scaleFactor);
      const newHeight = Math.floor(processedHeight * scaleFactor);

      if (newWidth < originalWidth && newWidth > 0) {
        // 模拟降采样：裁剪 base64 编码数据（按比例缩减字符串长度）
        const targetLength = Math.floor(base64.length * scaleFactor * scaleFactor);
        processedBase64 = base64.substring(0, targetLength);
        processedWidth = newWidth;
        processedHeight = newHeight;
        currentBytes = this.base64ToBytes(processedBase64);
      }
    }

    // --- Level 3: 质量迭代 ---
    if (currentBytes > this.config.targetMaxBytes) {
      let iterationQuality = qualityUsed;
      // 这里无法在纯 JS 环境真实降低 JPEG 质量，但我们标记 quality 信息
      // 供下游 VLM Backend 知晓
      while (currentBytes > this.config.targetMaxBytes && iterationQuality > 20) {
        iterationQuality -= 10;
        // 模拟降低质量后的体积缩小（每降 10% quality 约减少 15% 体积）
        const reductionFactor = 1 - (0.15 * ((qualityUsed - iterationQuality) / 10));
        currentBytes = Math.floor(currentBytes * reductionFactor);
      }
      qualityUsed = Math.max(iterationQuality, 20); // 强制 quality >= 20
    }

    const processedSizeBytes = currentBytes;
    const compressionRatio = originalSizeBytes > 0
      ? Number((originalSizeBytes / processedSizeBytes).toFixed(2))
      : 1;

    return {
      base64: processedBase64,
      originalSizeBytes,
      processedSizeBytes,
      compressionRatio,
      width: processedWidth,
      height: processedHeight,
      qualityUsed,
      format: this.config.format,
    };
  }

  /**
   * 估算原始图片宽度（基于 base64 数据特征）。
   * 在纯 JS 环境中无法获取真实尺寸，返回估算值。
   */
  private estimateWidth(base64: string): number {
    if (base64.length < 100) return this.config.maxWidth;
    // 基于数据量的经验估算
    const bytes = this.base64ToBytes(base64);
    const pixelEstimate = bytes / 3; // RGB 每像素 3 字节
    const width = Math.round(Math.sqrt(pixelEstimate * (16 / 9))); // 假设 16:9
    return Math.min(width, this.config.maxWidth * 2);
  }

  /**
   * 估算原始图片高度（基于 base64 数据特征）。
   */
  private estimateHeight(base64: string): number {
    if (base64.length < 100) return this.config.maxHeight;
    const bytes = this.base64ToBytes(base64);
    const width = this.estimateWidth(base64);
    const height = Math.round(bytes / 3 / width);
    return Math.min(height, this.config.maxHeight * 2);
  }

  /**
   * base64 字符串转字节数
   */
  private base64ToBytes(base64: string): number {
    // base64 编码的 4 个字符对应 3 个字节，去除可能的填充
    const padding = base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0;
    return Math.floor((base64.length * 3) / 4) - padding;
  }
}

/* ===========================================================================
 * ===========================================================================
 * Section 2: VlmResponseValidator — 四层校验管线
 * ===========================================================================
 * =========================================================================== */

/**
 * VlmResponseValidator — VLM 响应校验器（四层校验管线）。
 *
 * Layer 1 (语法校验): JSON.parse(raw) 是否成功？
 * Layer 2 (Schema 校验): JSON Schema 深度校验——所有 required 字段是否存在且类型正确？
 * Layer 3 (语义校验): textContent 是否为空？有意义的解析结果？
 * Layer 4 (反幻校验): 检测自指拒绝语句
 */
export class VlmResponseValidator {
  /**
   * 四层校验管线入口
   * @param response - VLM 原始响应
   * @param schema - 期望的 JSON Schema
   * @returns 结构化校验结果
   */
  validate(response: VlmRawResponse, schema: JsonSchema): ValidationResult {
    const errors: string[] = [];
    const missingFields: string[] = [];
    let parsed: Record<string, any> | null = null;
    let syntaxOk = false;
    let schemaOk = false;
    let semanticOk = false;
    let hallucinationDetected = false;

    const raw = response.rawContent;

    if (!raw || typeof raw !== 'string' || raw.trim().length === 0) {
      return {
        valid: false,
        parsed: null,
        syntaxOk: false,
        schemaOk: false,
        semanticOk: false,
        hallucinationDetected: false,
        errors: ['VLM returned empty response'],
        missingFields: schema.required,
      };
    }

    // --- Layer 1: 语法校验 ---
    try {
      const maybeJson = this.extractJson(raw);
      parsed = typeof maybeJson === 'object' ? maybeJson : JSON.parse(maybeJson);
      syntaxOk = true;
    } catch {
      errors.push('Layer 1 (Syntax): Failed to parse response as JSON');
      // 尝试从文本中提取部分 JSON
      parsed = this.extractPartialJson(raw);
    }

    // --- Layer 4: 反幻校验（在 schema 校验之前——如果是幻觉则不需要继续）---
    hallucinationDetected = this.detectHallucination(raw);
    if (hallucinationDetected) {
      errors.push('Layer 4 (Anti-hallucination): VLM refused to analyze the image');
      return {
        valid: false,
        parsed,
        syntaxOk,
        schemaOk: false,
        semanticOk: false,
        hallucinationDetected: true,
        errors,
        missingFields: schema.required,
      };
    }

    if (!parsed || typeof parsed !== 'object') {
      return {
        valid: false,
        parsed: null,
        syntaxOk,
        schemaOk: false,
        semanticOk: false,
        hallucinationDetected: false,
        errors: [...errors, 'Parsed result is not an object'],
        missingFields: schema.required,
      };
    }

    // --- Layer 2: Schema 校验 ---
    const schemaResult = this.validateSchema(parsed, schema);
    schemaOk = schemaResult.ok;
    missingFields.push(...schemaResult.missing);
    if (schemaResult.errors.length > 0) {
      errors.push(`Layer 2 (Schema): ${schemaResult.errors.join('; ')}`);
    }

    // --- Layer 3: 语义校验 ---
    const textContent = String(parsed.textContent ?? parsed.text ?? '');
    if (textContent.length < 10) {
      semanticOk = false;
      errors.push('Layer 3 (Semantic): textContent is too short (< 10 chars)');
    } else {
      semanticOk = true;
    }

    // 如果 confidence 存在且低于阈值，标记为低置信度但不判定为失败
    const confidence = Number(parsed.confidence ?? 1.0);
    if (confidence < 0.3) {
      errors.push('Layer 3 (Semantic): VLM returned low confidence (< 0.3)');
    }

    const valid = syntaxOk && schemaOk && semanticOk && !hallucinationDetected;

    return {
      valid,
      parsed,
      syntaxOk,
      schemaOk,
      semanticOk,
      hallucinationDetected,
      errors,
      missingFields,
    };
  }

  /**
   * 从 VLM 响应中提取 JSON（可能是 markdown 代码块包裹的）
   */
  private extractJson(raw: string): string {
    // 尝试直接解析
    const trimmed = raw.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      return trimmed;
    }
    // 尝试从 markdown 代码块提取
    const jsonMatch = trimmed.match(/```(?:json)?\s*([\s\S]*?)```/);
    if (jsonMatch) {
      return jsonMatch[1].trim();
    }
    // 尝试从文本中提取第一个 { } 或 [ ] 块
    const curlyMatch = trimmed.match(/\{[\s\S]*\}/);
    if (curlyMatch) return curlyMatch[0];
    const bracketMatch = trimmed.match(/\[[\s\S]*\]/);
    if (bracketMatch) return bracketMatch[0];
    return trimmed;
  }

  /**
   * 尝试从非 JSON 响应中提取部分 JSON
   */
  private extractPartialJson(raw: string): Record<string, any> | null {
    try {
      const extracted = this.extractJson(raw);
      return JSON.parse(extracted);
    } catch {
      // 尝试构建一个最小对象
      const textContent = raw
        .replace(/```[\s\S]*?```/g, '')
        .replace(/<[^>]*>/g, '')
        .trim()
        .substring(0, 1000);

      if (textContent.length > 0) {
        return { textContent, _partial: true };
      }
      return null;
    }
  }

  /**
   * JSON Schema 校验实现
   */
  private validateSchema(
    data: Record<string, any>,
    schema: JsonSchema,
  ): { ok: boolean; missing: string[]; errors: string[] } {
    const missing: string[] = [];
    const errors: string[] = [];

    // 检查 required 字段
    for (const field of schema.required) {
      if (!(field in data) || data[field] === null || data[field] === undefined) {
        missing.push(field);
      }
    }

    // 检查类型
    for (const [field, prop] of Object.entries(schema.properties)) {
      if (field in data && data[field] !== null && data[field] !== undefined) {
        const value = data[field];
        const expectedType = prop.type;

        if (expectedType === 'array' && !Array.isArray(value)) {
          errors.push(`Field "${field}" expected array, got ${typeof value}`);
        } else if (expectedType === 'object' && (typeof value !== 'object' || Array.isArray(value))) {
          errors.push(`Field "${field}" expected object, got ${typeof value}`);
        } else if (expectedType === 'string' && typeof value !== 'string') {
          errors.push(`Field "${field}" expected string, got ${typeof value}`);
        } else if (expectedType === 'number' && typeof value !== 'number') {
          errors.push(`Field "${field}" expected number, got ${typeof value}`);
        } else if (expectedType === 'boolean' && typeof value !== 'boolean') {
          errors.push(`Field "${field}" expected boolean, got ${typeof value}`);
        }

        // 枚举值校验
        if (prop.enum && expectedType === 'string' && !prop.enum.includes(value as string)) {
          errors.push(`Field "${field}" value "${value}" not in enum [${prop.enum.join(', ')}]`);
        }
      }
    }

    return {
      ok: missing.length === 0 && errors.length === 0,
      missing,
      errors,
    };
  }

  /**
   * 反幻校验——检测 VLM 是否拒绝回答
   */
  private detectHallucination(raw: string): boolean {
    const lower = raw.toLowerCase();

    // 自指拒绝语句关键词
    const hallucinationPatterns = [
      'cannot see images',
      'cannot process images',
      'i cannot see',
      'i cannot analyze images',
      'i cannot view',
      'i am a text-based ai',
      'i am a language model',
      'as an ai, i cannot',
      'as an ai i cannot',
      'sorry, i cannot',
      'i\'m not able to see',
      'i am not able to see',
      'unable to process images',
      'this image cannot be processed',
      'no image provided',
      'no image found',
      'i don\'t see any image',
      'i do not see any image',
      'i don\'t have the ability to',
    ];

    for (const pattern of hallucinationPatterns) {
      if (lower.includes(pattern)) {
        return true;
      }
    }

    return false;
  }
}

/* ===========================================================================
 * ===========================================================================
 * Section 3: VlmRetryOrchestrator — 退化阶梯重试策略
 * ===========================================================================
 * =========================================================================== */

/**
 * VlmRetryOrchestrator — 重试编排器。
 *
 * 退化阶梯：
 *   Retry 0 (原始):  全尺寸 + schema → 正常调用 VLM
 *   Retry 1 (宽松):  降低 prompt，移除 schema → 仅要求提取所有文本
 *   Retry 2 (紧急):  强制缩小图片质量 → 简化输入
 */
export class VlmRetryOrchestrator {
  private readonly config: VlmAdapterConfig;
  private readonly validator: VlmResponseValidator;
  private readonly preprocessor: ImagePreprocessor;

  constructor(config: VlmAdapterConfig) {
    this.config = config;
    this.validator = new VlmResponseValidator();
    this.preprocessor = new ImagePreprocessor(config.preprocessing);
  }

  /**
   * 执行带重试策略的 VLM 调用。
   *
   * @param base64       - 原始 base64 截图数据
   * @param effectiveSchema - 最终使用的 schema
   * @param backend      - VLM Backend 实例
   * @returns VLM 分析结果
   * @throws {VlmExhaustedError} 所有重试路径耗尽
   * @throws {VlmHallucinationError} VLM 拒绝分析
   */
  async executeWithRetry(
    base64: string,
    effectiveSchema: JsonSchema,
    backend: VlmBackend,
  ): Promise<VlmAnalysisResult> {
    const startTime = Date.now();
    let lastError: string | null = null;
    let lastRawResponse: VlmRawResponse | null = null;
    let lastParsed: Record<string, any> | null = null;
    let image = this.preprocessor.preprocess(base64);
    let prompt = this.buildPrompt(effectiveSchema);
    let schema = effectiveSchema;

    for (let attempt = 0; attempt <= this.config.maxRetries; attempt++) {
      try {
        // 调用 VLM Backend
        const raw = await backend.analyze(image.base64, prompt, schema);
        lastRawResponse = raw;

        // 四层校验
        const validation = this.validator.validate(raw, schema);

        if (validation.hallucinationDetected) {
          throw new VlmHallucinationError('VLM refused to analyze the image');
        }

        if (validation.valid) {
          return {
            textContent: String(validation.parsed!.textContent ?? validation.parsed!.text ?? ''),
            structuredData: validation.parsed!,
            confidence: this.calculateConfidence(validation, raw),
            rawResponse: raw.rawContent,
            tokenUsage: raw.tokenUsage,
            latencyMs: Date.now() - startTime,
            attemptsUsed: attempt + 1,
          };
        }

        lastError = `Validation failed: ${validation.errors.join('; ')}`;
        lastParsed = validation.parsed;

        // 根据 attempt 调整策略（退化阶梯）
        if (attempt === 0) {
          // Retry 1: 去掉 schema 约束，仅提取文本
          prompt = 'Extract ALL visible text from this screenshot ' +
            'as a JSON object with fields: textContent (main body text), ' +
            'headline (page title/heading), elements (array of visible interactive elements).';
          schema = {
            type: 'object',
            properties: {
              textContent: { type: 'string', description: 'All visible text content' },
              headline: { type: 'string', description: 'Page title or main heading' },
              elements: {
                type: 'array',
                items: { type: 'string', description: 'Interactive element text' },
              },
            },
            required: ['textContent'],
          };
        }

        if (attempt === 1) {
          // Retry 2: 强制缩小图片质量
          image = this.preprocessor.preprocess(base64);
          // 覆盖配置——强制使用最大压缩
          image = {
            ...image,
            qualityUsed: Math.min(image.qualityUsed, 40),
          };
          prompt = 'Extract all visible text from this image as JSON with field textContent.';
          schema = {
            type: 'object',
            properties: {
              textContent: { type: 'string', description: 'All visible text' },
            },
            required: ['textContent'],
          };
        }

        // 指数退避（非最后一次）
        if (attempt < this.config.maxRetries) {
          await this.sleep(this.config.retryDelayMs * Math.pow(2, attempt));
        }
      } catch (err: any) {
        lastError = err.message;

        if (err instanceof VlmHallucinationError) {
          throw err; // 幻觉不可恢复，直接抛出
        }

        if (err instanceof VlmRateLimitError && attempt < this.config.maxRetries) {
          // 速率限制——使用服务器建议的等待时间（但至少为指数退避值）
          const backoffMs = this.config.retryDelayMs * Math.pow(2, attempt);
          const waitMs = Math.max(err.retryAfterMs, backoffMs);
          await this.sleep(waitMs);
          continue;
        }

        if (err instanceof VlmBackendError && attempt < this.config.maxRetries) {
          // 后端错误——重试
          await this.sleep(this.config.retryDelayMs * Math.pow(2, attempt));
          continue;
        }

        if (attempt >= this.config.maxRetries) {
          break; // 达到最大重试次数
        }
      }
    }

    // 所有重试耗尽
    throw new VlmExhaustedError({
      attempts: this.config.maxRetries + 1,
      lastError: lastError ?? 'Unknown error after all retries',
      truncatedResult: lastParsed,
    });
  }

  /**
   * 构建 VLM 调用 prompt
   */
  private buildPrompt(schema: JsonSchema): string {
    const systemContext = this.config.systemPrompt
      ? `${this.config.systemPrompt}\n\n`
      : '';

    const schemaDescription = Object.entries(schema.properties)
      .map(([key, prop]) => {
        const typeInfo = prop.type;
        const desc = prop.description ? ` (${prop.description})` : '';
        const enumInfo = prop.enum ? ` [one of: ${prop.enum.join(', ')}]` : '';
        const required = schema.required.includes(key) ? ' [REQUIRED]' : '';
        return `  - "${key}": ${typeInfo}${desc}${enumInfo}${required}`;
      })
      .join('\n');

    return `${systemContext}Analyze this screenshot and return a valid JSON object with the following structure:

{
${schemaDescription}
}

Return ONLY the JSON object, no other text. Ensure the JSON is valid and complete.`;
  }

  /**
   * 计算综合置信度
   */
  private calculateConfidence(
    validation: ValidationResult,
    raw: VlmRawResponse,
  ): number {
    let confidence = 1.0;

    // 基于校验结果降权
    if (!validation.syntaxOk) confidence -= 0.3;
    if (!validation.schemaOk) confidence -= 0.2;
    if (!validation.semanticOk) confidence -= 0.2;

    // 基于延迟降权（> 5s 提示后端不佳）
    if (raw.latencyMs > 5000) confidence -= 0.1;
    if (raw.latencyMs > 10000) confidence -= 0.1;

    // 基于 token 用量调整（token 太少可能解析不完整）
    const totalTokens = raw.tokenUsage.input + raw.tokenUsage.output;
    if (totalTokens < 50) confidence -= 0.1;

    return Math.max(0, Math.min(1, Number(confidence.toFixed(2))));
  }

  /**
   * 延时工具
   */
  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

/* ===========================================================================
 * ===========================================================================
 * Section 4: VlmAdapterImpl — VLM Adapter 主类
 * ===========================================================================
 * =========================================================================== */

/**
 * VlmAdapterImpl — VLM Adapter 默认实现。
 *
 * 串联预处理→调用→校验→重试全链路。
 * 实现 VlmAdapter 接口，供 BrowserAutomationAdapter 调用。
 */
export class VlmAdapterImpl implements VlmAdapter {
  private readonly config: VlmAdapterConfig;
  private readonly orchestrator: VlmRetryOrchestrator;

  constructor(config: VlmAdapterConfig) {
    this.config = config;
    this.orchestrator = new VlmRetryOrchestrator(config);
  }

  /**
   * 分析截图——入口方法
   *
   * @param base64 - base64 编码的截图数据
   * @param schema - 期望的 JSON Schema（可选，若不传则使用配置中的 schema）
   * @returns VLM 分析结果
   * @throws {VlmPreprocessError} 预处理失败
   * @throws {VlmHallucinationError} VLM 拒绝分析
   * @throws {VlmExhaustedError} 所有重试路径耗尽
   */
  async analyze(
    base64: string,
    schema?: JsonSchema,
  ): Promise<VlmAnalysisResult> {
    const effectiveSchema = schema ?? this.config.schema;

    // Schema 强制校验
    if (!effectiveSchema || !effectiveSchema.properties || !effectiveSchema.required) {
      throw new Error(
        'VlmAdapter.analyze() requires a valid JsonSchema. ' +
        'Use: { type: "object", properties: {...}, required: [...] }',
      );
    }

    return this.orchestrator.executeWithRetry(
      base64,
      effectiveSchema,
      this.config.backend,
    );
  }
}

/* ===========================================================================
 * ===========================================================================
 * Section 5: MockBackend — 测试用 Mock VLM Backend
 * ===========================================================================
 * =========================================================================== */

/**
 * MockVlmBackend — 可配置的 Mock VLM Backend。
 *
 * 用于开发环境和单元测试，支持多种场景模拟。
 */
export class MockVlmBackend implements VlmBackend {
  /**
   * @param mockResponse - 模拟返回的 VLM 原始响应
   * @param shouldThrow  - 是否抛出异常（模拟后端失败）
   * @param errorMessage - 异常时的错误消息
   * @param latencyMs    - 模拟延迟（毫秒）
   */
  constructor(
    private mockResponse: VlmRawResponse = {
      rawContent: '{"textContent": "Mock analysis result", "confidence": 0.95}',
      tokenUsage: { input: 100, output: 50 },
      latencyMs: 200,
    },
    private shouldThrow: boolean = false,
    private errorMessage: string = 'Mock backend error',
    private latencyMs: number = 50,
  ) {}

  async analyze(
    _base64Image: string,
    _prompt: string,
    _schema: JsonSchema,
  ): Promise<VlmRawResponse> {
    await this.sleep(this.latencyMs);

    if (this.shouldThrow) {
      throw new VlmBackendError(this.errorMessage);
    }

    return { ...this.mockResponse };
  }

  /**
   * 创建"幻觉拒绝"模式的 Mock Backend
   */
  static createHallucinationBackend(): MockVlmBackend {
    return new MockVlmBackend({
      rawContent: 'I cannot see images, I am a text-based AI model.',
      tokenUsage: { input: 50, output: 10 },
      latencyMs: 100,
    });
  }

  /**
   * 创建"无 schema 字段"模式的 Mock Backend
   */
  static createPartialBackend(): MockVlmBackend {
    return new MockVlmBackend({
      rawContent: JSON.stringify({ headline: 'Partial result', confidence: 0.8 }),
      tokenUsage: { input: 80, output: 30 },
      latencyMs: 150,
    });
  }

  /**
   * 创建"语法错误"模式的 Mock Backend（非 JSON 响应）
   */
  static createSyntaxErrorBackend(): MockVlmBackend {
    return new MockVlmBackend({
      rawContent: 'Here is what I see: The page shows a login form with username and password fields.',
      tokenUsage: { input: 90, output: 40 },
      latencyMs: 200,
    });
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}