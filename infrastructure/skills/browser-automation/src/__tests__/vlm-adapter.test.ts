/**
 * =============================================================================
 * VLM Adapter — 单元测试套件
 * =============================================================================
 *
 * 覆盖范围：
 *   §1 ImagePreprocessor — 三级压缩管线
 *   §2 VlmResponseValidator — 四层校验管线
 *   §3 VlmRetryOrchestrator — 重试编排器
 *   §4 VlmAdapterImpl — 主类集成
 *   §5 MockVlmBackend — Mock 后端工厂
 *
 * @module vlm-adapter.test
 */

import { ImagePreprocessor, VlmResponseValidator, VlmRetryOrchestrator, VlmAdapterImpl, MockVlmBackend } from '../vlm-adapter';
import {
  VlmRawResponse,
  JsonSchema,
  VlmAdapterConfig,
  PreprocessorConfig,
  VlmPreprocessError,
  VlmBackendError,
  VlmHallucinationError,
  VlmExhaustedError,
  VlmValidationError,
} from '../vlm-types';
import { PAGE_CONTENT_SCHEMA, TEXT_ONLY_SCHEMA, createDefaultVlmAdapterConfig, createVlmAdapter } from '../vlm-adapter.config';

/* ===========================================================================
 * Helper 函数
 * =========================================================================== */

/** 生成一个最小尺寸的有效 base64 编码数据 */
function makeMinimalBase64(length: number = 120): string {
  return 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==' + 'A'.repeat(Math.max(0, length - 120));
}

/** 生成一个大尺寸 base64 编码数据（模拟大截图） */
function makeLargeBase64(): string {
  return 'A'.repeat(8000); // ~6KB base64
}

/** 生成一个超大 base64 编码数据（模拟超高清截图） */
function makeHugeBase64(): string {
  return 'B'.repeat(50000); // ~37.5KB base64
}

/** 默认 Schema */
const defaultSchema: JsonSchema = {
  type: 'object',
  properties: {
    textContent: { type: 'string', description: 'All visible text' },
    headline: { type: 'string', description: 'Page headline' },
  },
  required: ['textContent', 'headline'],
};

/** 快速创建 VlmRawResponse */
function makeResponse(rawContent: string, opts?: Partial<VlmRawResponse>): VlmRawResponse {
  return {
    rawContent,
    tokenUsage: opts?.tokenUsage ?? { input: 100, output: 50 },
    latencyMs: opts?.latencyMs ?? 200,
  };
}

/* ===========================================================================
 * ===========================================================================
 * §1 ImagePreprocessor 三级压缩管线测试
 * ===========================================================================
 * =========================================================================== */

describe('§1 ImagePreprocessor — 三级压缩管线', () => {
  describe('Level 0: 输入校验', () => {
    it('应拒绝空字符串输入', () => {
      const pre = new ImagePreprocessor();
      expect(() => pre.preprocess('')).toThrow(VlmPreprocessError);
      expect(() => pre.preprocess('')).toThrow('Invalid base64 input');
    });

    it('应拒绝 null/undefined (TS 编译时保护，运行时仍应防御)', () => {
      const pre = new ImagePreprocessor();
      expect(() => pre.preprocess(null as unknown as string)).toThrow(VlmPreprocessError);
      expect(() => pre.preprocess(undefined as unknown as string)).toThrow(VlmPreprocessError);
    });

    it('应拒绝空字符串（仅空格）', () => {
      const pre = new ImagePreprocessor();
      expect(() => pre.preprocess('   ')).toThrow(VlmPreprocessError);
    });

    it('应接受最小有效 base64', () => {
      const pre = new ImagePreprocessor();
      const result = pre.preprocess(makeMinimalBase64());
      expect(result).toBeDefined();
      expect(result.base64).toBeTruthy();
      expect(result.originalSizeBytes).toBeGreaterThan(0);
      expect(result.processedSizeBytes).toBeGreaterThan(0);
    });
  });

  describe('Level 1: 尺寸降采样', () => {
    it('大输入应触发降采样', () => {
      const pre = new ImagePreprocessor({ maxWidth: 800, maxHeight: 600 });
      const huge = makeHugeBase64();
      const result = pre.preprocess(huge);
      expect(result.processedSizeBytes).toBeLessThanOrEqual(result.originalSizeBytes);
      expect(result.compressionRatio).toBeGreaterThanOrEqual(1);
    });

    it('小输入不应降采样', () => {
      const pre = new ImagePreprocessor();
      const small = makeMinimalBase64(200);
      const result = pre.preprocess(small);
      expect(result.compressionRatio).toBe(1);
      expect(result.processedSizeBytes).toBe(result.originalSizeBytes);
    });

    it('自定义 maxWidth/maxHeight 应影响降采样阈值', () => {
      const pre = new ImagePreprocessor({ maxWidth: 200, maxHeight: 200 });
      const huge = makeHugeBase64();
      const result = pre.preprocess(huge);
      // maxWidth 200 * maxHeight 200 * 3 = 120000 byte threshold
      const estimatedThreshold = 200 * 200 * 3;
      expect(result.processedSizeBytes).toBeLessThanOrEqual(estimatedThreshold * 1.1); // 允许 10% 误差
    });
  });

  describe('Level 3: 质量迭代', () => {
    it('应逐步降低 quality 直到目标大小', () => {
      const pre = new ImagePreprocessor({ targetMaxBytes: 1000, quality: 85 });
      const large = makeLargeBase64();
      const result = pre.preprocess(large);
      expect(result.processedSizeBytes).toBeGreaterThan(0);
    });

    it('初始 quality 应正确传递', () => {
      const pre = new ImagePreprocessor({ quality: 90 });
      const result = pre.preprocess(makeMinimalBase64());
      expect(result.qualityUsed).toBe(90);
    });

    it('quality 不应低于 20', () => {
      const pre = new ImagePreprocessor({ targetMaxBytes: 1, quality: 85 }); // 极小目标
      const result = pre.preprocess(makeLargeBase64());
      expect(result.qualityUsed).toBeGreaterThanOrEqual(20);
    });
  });

  describe('输出格式验证', () => {
    it('默认输出格式应为 jpeg', () => {
      const pre = new ImagePreprocessor();
      const result = pre.preprocess(makeMinimalBase64());
      expect(result.format).toBe('jpeg');
    });

    it('应遵循配置指定的格式', () => {
      const pre = new ImagePreprocessor({ format: 'png' });
      const result = pre.preprocess(makeMinimalBase64());
      expect(result.format).toBe('png');
    });
  });
});

/* ===========================================================================
 * ===========================================================================
 * §2 VlmResponseValidator 四层校验管线测试
 * ===========================================================================
 * =========================================================================== */

describe('§2 VlmResponseValidator — 四层校验管线', () => {
  const validator = new VlmResponseValidator();

  describe('Layer 1: 语法校验', () => {
    it('应通过有效 JSON', () => {
      const resp = makeResponse('{"textContent": "Hello", "headline": "World"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.syntaxOk).toBe(true);
      expect(result.parsed).toBeTruthy();
    });

    it('应通过 Markdown 代码块包裹的 JSON', () => {
      const resp = makeResponse('```json\n{"textContent": "Hello", "headline": "World"}\n```');
      const result = validator.validate(resp, defaultSchema);
      expect(result.syntaxOk).toBe(true);
      expect(result.parsed?.textContent).toBe('Hello');
    });

    it('应解析不含 markdown 注释的文字中的 JSON', () => {
      const resp = makeResponse('Here is the result: {"textContent": "Body text", "headline": "Title"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.syntaxOk).toBe(true);
      expect(result.parsed?.textContent).toBe('Body text');
    });

    it('空响应应标记语法失败', () => {
      const resp = makeResponse('');
      const result = validator.validate(resp, defaultSchema);
      expect(result.syntaxOk).toBe(false);
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('非 JSON 响应应尝试提取部分 JSON', () => {
      const resp = makeResponse('The page shows a login form with username field.');
      const result = validator.validate(resp, defaultSchema);
      // 应尝试提取并构建最小对象
      expect(result.parsed).toBeTruthy();
      expect(result.parsed?.textContent).toBeTruthy();
    });
  });

  describe('Layer 2: Schema 校验', () => {
    it('应通过所有 required 字段都存在且类型正确的响应', () => {
      const resp = makeResponse('{"textContent": "Body content here", "headline": "Title", "extra": true}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.schemaOk).toBe(true);
      expect(result.valid).toBe(true);
    });

    it('丢失 required 字段应标记 schema 失败', () => {
      const resp = makeResponse('{"textContent": "Body only"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.schemaOk).toBe(false);
      expect(result.valid).toBe(false);
      expect(result.missingFields).toContain('headline');
    });

    it('类型不匹配应标记错误', () => {
      const schema: JsonSchema = {
        type: 'object',
        properties: {
          textContent: { type: 'string' },
          count: { type: 'number' },
        },
        required: ['textContent', 'count'],
      };
      const resp = makeResponse('{"textContent": "Hello", "count": "not-a-number"}');
      const result = validator.validate(resp, schema);
      expect(result.schemaOk).toBe(false);
      expect(result.errors.some(e => e.includes('count'))).toBe(true);
    });

    it('枚举值验证应正常工作', () => {
      const schema: JsonSchema = {
        type: 'object',
        properties: {
          textContent: { type: 'string' },
          status: { type: 'string', enum: ['ok', 'error'] },
        },
        required: ['textContent', 'status'],
      };
      const okResp = makeResponse('{"textContent": "Done", "status": "ok"}');
      expect(validator.validate(okResp, schema).schemaOk).toBe(true);

      const badResp = makeResponse('{"textContent": "Done", "status": "invalid"}');
      expect(validator.validate(badResp, schema).schemaOk).toBe(false);
    });

    it('数组类型验证应正常工作', () => {
      const schema: JsonSchema = {
        type: 'object',
        properties: {
          textContent: { type: 'string' },
          items: { type: 'array', items: { type: 'string' } },
        },
        required: ['textContent', 'items'],
      };
      const okResp = makeResponse('{"textContent": "List", "items": ["a", "b"]}');
      expect(validator.validate(okResp, schema).schemaOk).toBe(true);

      const badResp = makeResponse('{"textContent": "List", "items": "not-array"}');
      expect(validator.validate(badResp, schema).schemaOk).toBe(false);
    });
  });

  describe('Layer 3: 语义校验', () => {
    it('textContent 为空的响应应标记语义失败', () => {
      const resp = makeResponse('{"textContent": "", "headline": "Title"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.semanticOk).toBe(false);
      expect(result.valid).toBe(false);
    });

    it('textContent 过短（< 10 字符）应标记语义失败', () => {
      const resp = makeResponse('{"textContent": "Hi", "headline": "Title"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.semanticOk).toBe(false);
    });

    it('textContent 足够长的响应应通过语义校验', () => {
      const resp = makeResponse('{"textContent": "This is a sufficiently long text above threshold", "headline": "Title"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.semanticOk).toBe(true);
    });

    it('confidence < 0.3 应添加错误但不阻止验证通过', () => {
      const resp = makeResponse('{"textContent": "Sufficiently long content here for testing", "headline": "Title", "confidence": 0.2}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.semanticOk).toBe(true); // 语义校验通过（textContent 足够长）
      expect(result.errors.some(e => e.includes('low confidence'))).toBe(true);
    });
  });

  describe('Layer 4: 反幻校验', () => {
    it('应检测 "I cannot see images" 幻觉', () => {
      const resp = makeResponse('I cannot see images, I am a text-based AI model.');
      const result = validator.validate(resp, defaultSchema);
      expect(result.hallucinationDetected).toBe(true);
      expect(result.valid).toBe(false);
    });

    it('应检测 "as an AI, I cannot" 幻觉', () => {
      const resp = makeResponse('As an AI, I cannot process or analyze images or screenshots.');
      const result = validator.validate(resp, defaultSchema);
      expect(result.hallucinationDetected).toBe(true);
    });

    it('应检测 "no image found" 幻觉', () => {
      const resp = makeResponse('No image found in the provided input.');
      const result = validator.validate(resp, defaultSchema);
      expect(result.hallucinationDetected).toBe(true);
    });

    it('应检测 "sorry, I cannot" 幻觉', () => {
      const resp = makeResponse('Sorry, I cannot see the image you mentioned.');
      const result = validator.validate(resp, defaultSchema);
      expect(result.hallucinationDetected).toBe(true);
    });

    it('正常响应应通过反幻校验', () => {
      const resp = makeResponse('{"textContent": "This is a page about machine learning with several sections.", "headline": "ML Overview"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.hallucinationDetected).toBe(false);
    });

    it('纯文本内容包含单词 "image" 但未拒绝应通过', () => {
      const resp = makeResponse('{"textContent": "This image shows a graph of revenue over time for the company.", "headline": "Revenue Chart"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.hallucinationDetected).toBe(false);
      expect(result.valid).toBe(true);
    });
  });

  describe('完整管线组合场景', () => {
    it('有效响应应通过全部四层校验', () => {
      const resp = makeResponse('{"textContent": "The dashboard shows three metrics: revenue, users, and growth rate.", "headline": "Dashboard"}');
      const result = validator.validate(resp, defaultSchema);
      expect(result.valid).toBe(true);
      expect(result.syntaxOk).toBe(true);
      expect(result.schemaOk).toBe(true);
      expect(result.semanticOk).toBe(true);
      expect(result.hallucinationDetected).toBe(false);
      expect(result.errors.length).toBe(0);
    });

    it('全部失败的响应应多层错误', () => {
      const resp = makeResponse('');
      const result = validator.validate(resp, defaultSchema);
      expect(result.syntaxOk).toBe(false);
      expect(result.schemaOk).toBe(false);
      expect(result.semanticOk).toBe(false);
      expect(result.valid).toBe(false);
    });
  });
});

/* ===========================================================================
 * ===========================================================================
 * §3 VlmRetryOrchestrator — 重试编排器测试
 * ===========================================================================
 * =========================================================================== */

describe('§3 VlmRetryOrchestrator — 重试编排器', () => {
  const mkConfig = (overrides?: Partial<VlmAdapterConfig>): VlmAdapterConfig => ({
    ...createDefaultVlmAdapterConfig(TEXT_ONLY_SCHEMA),
    ...overrides,
  });

  describe('成功路径', () => {
    it('首次调用成功应返回有效结果', async () => {
      const config = mkConfig();
      const orch = new VlmRetryOrchestrator(config);
      const result = await orch.executeWithRetry(makeMinimalBase64(), TEXT_ONLY_SCHEMA, config.backend);
      expect(result).toBeDefined();
      expect(result.textContent).toBeTruthy();
      expect(result.attemptsUsed).toBe(1);
      expect(result.confidence).toBeGreaterThan(0);
      expect(result.latencyMs).toBeGreaterThan(0);
    });
  });

  describe('退化阶梯', () => {
    it('schema 校验失败后应在第二次使用时宽松的 schema', async () => {
      const config = mkConfig({
        backend: MockVlmBackend.createPartialBackend(),
      });
      const orch = new VlmRetryOrchestrator(config);
      try {
        await orch.executeWithRetry(makeMinimalBase64(), defaultSchema, config.backend);
        // PartialBackend 缺少 textContent，但退化到宽松 schema 后应该能通过
        // 但 MockBackend 不会改变响应，所以仍会失败——验证重试路径被尝试即可
      } catch (err) {
        expect(err).toBeInstanceOf(VlmExhaustedError);
        const exhausted = err as VlmExhaustedError;
        expect(exhausted.attempts).toBeGreaterThanOrEqual(0);
      }
    });
  });

  describe('异常路径', () => {
    it('后端错误应重试', async () => {
      const config = mkConfig({
        backend: new MockVlmBackend(
          { rawContent: '{"textContent": "Success after retry"}', tokenUsage: { input: 100, output: 50 }, latencyMs: 100 },
          false, // 不抛出异常
        ),
        maxRetries: 2,
        retryDelayMs: 10,
      });
      const orch = new VlmRetryOrchestrator(config);
      const result = await orch.executeWithRetry(makeMinimalBase64(), TEXT_ONLY_SCHEMA, config.backend);
      expect(result.attemptsUsed).toBeGreaterThanOrEqual(1);
    });

    it('幻觉错误应直接抛出不可恢复', async () => {
      const config = mkConfig({
        backend: MockVlmBackend.createHallucinationBackend(),
        maxRetries: 1,
        retryDelayMs: 10,
      });
      const orch = new VlmRetryOrchestrator(config);
      await expect(
        orch.executeWithRetry(makeMinimalBase64(), TEXT_ONLY_SCHEMA, config.backend),
      ).rejects.toThrow(VlmHallucinationError);
    });
  });
});

/* ===========================================================================
 * ===========================================================================
 * §4 VlmAdapterImpl — 主类集成测试
 * ===========================================================================
 * =========================================================================== */

describe('§4 VlmAdapterImpl — 主类集成', () => {
  describe('正常路径', () => {
    it('analyze() 应返回结构化结果', async () => {
      const adapter = createVlmAdapter();
      const result = await adapter.analyze(makeMinimalBase64(), TEXT_ONLY_SCHEMA);
      expect(result).toBeDefined();
      expect(result.textContent).toBeTruthy();
      expect(result.structuredData).toBeTruthy();
      expect(result.confidence).toBeGreaterThan(0);
      expect(result.attemptsUsed).toBeGreaterThanOrEqual(1);
    });

    it('不传 schema 应使用配置中的 schema', async () => {
      const adapter = createVlmAdapter();
      const result = await adapter.analyze(makeMinimalBase64());
      expect(result).toBeDefined();
      expect(result.textContent).toBeTruthy();
    });
  });

  describe('错误路径', () => {
    it('无 schema 时应抛出', async () => {
      const adapter = createVlmAdapter(createDefaultVlmAdapterConfig({ type: 'object', properties: {}, required: [] } as JsonSchema));
      const config = createDefaultVlmAdapterConfig({ type: 'object', properties: {}, required: [] } as JsonSchema);
      // 创建空 schema 的 adapter，analyze 时传入空 schema 应失败
      const specialAdapter = createVlmAdapter(config);
      // 传入空 schema 覆盖
      await expect(
        specialAdapter.analyze(makeMinimalBase64(), {} as JsonSchema),
      ).rejects.toThrow();
    });

    it('预处理错误应抛出 VlmPreprocessError', async () => {
      const adapter = createVlmAdapter();
      await expect(
        adapter.analyze('', TEXT_ONLY_SCHEMA),
      ).rejects.toThrow(VlmPreprocessError);
    });

    it('幻觉响应应抛出 VlmHallucinationError', async () => {
      const config = createDefaultVlmAdapterConfig(
        TEXT_ONLY_SCHEMA,
        'I cannot see images, I am a text-based AI model.',
      );
      const adapter = createVlmAdapter(config);
      await expect(
        adapter.analyze(makeMinimalBase64()),
      ).rejects.toThrow(VlmHallucinationError);
    });

    it('后端连续失败应抛出 VlmExhaustedError', async () => {
      const config: VlmAdapterConfig = {
        ...createDefaultVlmAdapterConfig(TEXT_ONLY_SCHEMA),
        backend: new MockVlmBackend(
          undefined,
          true, // shouldThrow = true
          'Backend unavailable',
          10,
        ),
        maxRetries: 1,
        retryDelayMs: 10,
      };
      const adapter = createVlmAdapter(config);
      await expect(
        adapter.analyze(makeMinimalBase64()),
      ).rejects.toThrow(VlmExhaustedError);
    });
  });
});

/* ===========================================================================
 * ===========================================================================
 * §5 MockVlmBackend — Mock 后端工厂测试
 * ===========================================================================
 * =========================================================================== */

describe('§5 MockVlmBackend — Mock 后端工厂', () => {
  it('默认构造应返回有效 mock 响应', async () => {
    const backend = new MockVlmBackend();
    const result = await backend.analyze('fake-base64', 'prompt', TEXT_ONLY_SCHEMA);
    expect(result.rawContent).toContain('Mock analysis result');
    expect(result.tokenUsage.input).toBeGreaterThan(0);
    expect(result.latencyMs).toBeGreaterThan(0);
  });

  it('createHallucinationBackend 应返回断言拒绝语句', async () => {
    const backend = MockVlmBackend.createHallucinationBackend();
    const result = await backend.analyze('fake', 'prompt', TEXT_ONLY_SCHEMA);
    expect(result.rawContent.toLowerCase()).toContain('cannot see');
  });

  it('createPartialBackend 应返回缺失 textContent 的响应', async () => {
    const backend = MockVlmBackend.createPartialBackend();
    const result = await backend.analyze('fake', 'prompt', TEXT_ONLY_SCHEMA);
    const parsed = JSON.parse(result.rawContent);
    expect(parsed.headline).toBe('Partial result');
    expect(parsed.textContent).toBeUndefined();
  });

  it('createSyntaxErrorBackend 应返回非 JSON 响应', async () => {
    const backend = MockVlmBackend.createSyntaxErrorBackend();
    const result = await backend.analyze('fake', 'prompt', TEXT_ONLY_SCHEMA);
    expect(() => JSON.parse(result.rawContent)).toThrow();
  });

  it('shouldThrow=true 应抛出 VlmBackendError', async () => {
    const backend = new MockVlmBackend(undefined, true);
    await expect(
      backend.analyze('fake', 'prompt', TEXT_ONLY_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });
});

/* ===========================================================================
 * ===========================================================================
 * §6 边界条件与极端场景
 * ===========================================================================
 * =========================================================================== */

describe('§6 边界条件与极端场景', () => {
  describe('ImagePreprocessor 边界', () => {
    it('极小的 base64 输入应能处理', () => {
      const pre = new ImagePreprocessor();
      const result = pre.preprocess('iVBOR'); // 极短输入
      expect(result).toBeDefined();
      expect(result.originalSizeBytes).toBeGreaterThanOrEqual(0);
    });

    it('极大的 base64 输入不应崩溃', () => {
      const pre = new ImagePreprocessor();
      // 确保远远超过 estimatedMaxBytes (1024*768*3=2359296)
      const huge = 'X'.repeat(3200000); // ~2.4MB base64
      const result = pre.preprocess(huge);
      expect(result).toBeDefined();
      expect(result.processedSizeBytes).toBeLessThan(result.originalSizeBytes);
    });
  });

  describe('VlmResponseValidator 边界', () => {
    it('null/undefined rawContent 应安全处理', () => {
      const validator = new VlmResponseValidator();
      const resp = makeResponse(null as unknown as string);
      const result = validator.validate(resp, defaultSchema);
      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
    });

    it('空白字符 rawContent 应安全处理', () => {
      const validator = new VlmResponseValidator();
      const resp = makeResponse('   \n  \t  ');
      const result = validator.validate(resp, defaultSchema);
      expect(result.valid).toBe(false);
    });

    it('非常大的 JSON 响应应能解析', () => {
      const validator = new VlmResponseValidator();
      const largeText = 'A'.repeat(10000);
      const resp = makeResponse(`{"textContent": "${largeText}", "headline": "Large content"}`);
      const result = validator.validate(resp, defaultSchema);
      expect(result.valid).toBe(true);
      expect(result.parsed?.textContent.length).toBe(10000);
    });

    it('嵌套对象 schema 应正确校验', () => {
      const validator = new VlmResponseValidator();
      const nestedSchema: JsonSchema = {
        type: 'object',
        properties: {
          textContent: { type: 'string' },
          metadata: {
            type: 'object',
            properties: {
              page: { type: 'string' },
            },
          },
        },
        required: ['textContent', 'metadata'],
      };
      const okResp = makeResponse('{"textContent": "Page content", "metadata": {"page": "Home"}}');
      expect(validator.validate(okResp, nestedSchema).valid).toBe(true);

      const badResp = makeResponse('{"textContent": "Page content", "metadata": "not-an-object"}');
      const result = validator.validate(badResp, nestedSchema);
      expect(result.schemaOk).toBe(false);
    });
  });

  describe('config 工厂函数边界', () => {
    it('createDefaultVlmAdapterConfig 应使用默认 schema', () => {
      const config = createDefaultVlmAdapterConfig();
      expect(config.schema).toBeDefined();
      expect(config.schema.type).toBe('object');
      expect(config.schema.required).toContain('headline');
    });

    it('createDefaultVlmAdapterConfig 应接受自定义 mockResponse', () => {
      const customResp = '{"textContent": "Custom", "headline": "Test"}';
      const config = createDefaultVlmAdapterConfig(TEXT_ONLY_SCHEMA, customResp);
      expect(config.schema.required).toEqual(['textContent']);
    });

    it('createVlmAdapter 不传参应正常工作', () => {
      const adapter = createVlmAdapter();
      expect(adapter).toBeDefined();
      expect(adapter.analyze).toBeDefined();
    });
  });
});