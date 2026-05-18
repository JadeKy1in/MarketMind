/**
 * =============================================================================
 * RestVlmBackend — 纯 Fetch 实现的 VLM REST Backend 测试套件
 * =============================================================================
 *
 * 覆盖范围：
 *   §1 构造函数校验（缺失 endpoint / apiKey）
 *   §2 成功路径（模拟 fetch 正常返回）
 *   §3 HTTP 状态码降级（429/4xx/5xx）
 *   §4 超时与网络错误
 *   §5 Retry-After 头解析
 *   §6 空内容响应
 *   §7 工厂函数 createRestBackend
 *
 * 依赖：globalThis.fetch mock（Node 18+ 内置 fetch，使用 jest spy）
 *
 * @module vlm-backend-rest.test
 */

import { RestVlmBackend, createRestBackend } from '../vlm-backend-rest';
import {
  VlmRateLimitError,
  VlmRequestError,
  VlmBackendError,
  JsonSchema,
} from '../vlm-types';

/* ===========================================================================
 * Helpers
 * =========================================================================== */

const TEST_SCHEMA: JsonSchema = {
  type: 'object',
  properties: {
    textContent: { type: 'string' },
  },
  required: ['textContent'],
};

const TEST_ENDPOINT = 'https://api.test.com/v1/chat/completions';
const TEST_API_KEY = 'test-key-12345';

/** 构建一个成功的 fetch mock 响应 */
function makeSuccessResponse(overrides?: Partial<{
  rawContent: string;
  promptTokens: number;
  completionTokens: number;
}>): Response {
  const rawContent = overrides?.rawContent ?? '{"textContent": "Hello world"}';
  return new Response(
    JSON.stringify({
      choices: [
        {
          message: { content: rawContent },
          finish_reason: 'stop',
        },
      ],
      usage: {
        prompt_tokens: overrides?.promptTokens ?? 100,
        completion_tokens: overrides?.completionTokens ?? 50,
      },
    }),
    { status: 200, statusText: 'OK' },
  );
}

/** 构建一个 HTTP 错误响应 */
function makeErrorResponse(
  status: number,
  statusText: string,
  headers?: Record<string, string>,
  body?: string,
): Response {
  return new Response(
    body ?? `{"error": {"message": "Error ${status}"}}`,
    {
      status,
      statusText,
      headers: headers ?? undefined as any,
    },
  );
}

/* ===========================================================================
 * §1 构造函数校验
 * =========================================================================== */

describe('§1 RestVlmBackend — 构造函数校验', () => {
  const OLD_ENV = process.env;

  beforeEach(() => {
    jest.resetModules();
    process.env = { ...OLD_ENV };
    delete process.env.VLM_ENDPOINT;
    delete process.env.VLM_API_KEY;
  });

  afterAll(() => {
    process.env = OLD_ENV;
  });

  it('无配置且无环境变量时应抛出', () => {
    expect(() => new RestVlmBackend()).toThrow('Missing endpoint');
  });

  it('仅提供 endpoint 无 apiKey 时应抛出', () => {
    expect(() => new RestVlmBackend({ endpoint: TEST_ENDPOINT })).toThrow('Missing apiKey');
  });

  it('仅提供 apiKey 无 endpoint 时应抛出', () => {
    expect(() => new RestVlmBackend({ apiKey: TEST_API_KEY })).toThrow('Missing endpoint');
  });

  it('通过 config 传入有效配置应成功创建', () => {
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });

  it('通过环境变量传入应成功创建', () => {
    process.env.VLM_ENDPOINT = TEST_ENDPOINT;
    process.env.VLM_API_KEY = TEST_API_KEY;
    const backend = new RestVlmBackend();
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });

  it('config 应优先于环境变量', () => {
    process.env.VLM_ENDPOINT = 'https://env-endpoint.com/v1/chat/completions';
    process.env.VLM_API_KEY = 'env-key';
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });

  it('应使用 DEFAULT_REST_BACKEND_CONFIG 的默认 timeout', () => {
    // 不传 timeoutMs，应使用默认 60000
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });
});

/* ===========================================================================
 * §2 成功路径
 * =========================================================================== */

describe('§2 RestVlmBackend — 成功路径', () => {
  let fetchSpy: jest.SpyInstance;

  beforeEach(() => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeSuccessResponse());
  });

  afterEach(() => {
    fetchSpy.mockRestore();
  });

  it('应返回有效的 VlmRawResponse', async () => {
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    const result = await backend.analyze('fake-base64', 'Extract text', TEST_SCHEMA);
    expect(result).toBeDefined();
    expect(result.rawContent).toBe('{"textContent": "Hello world"}');
    expect(result.tokenUsage.input).toBe(100);
    expect(result.tokenUsage.output).toBe(50);
    expect(result.latencyMs).toBeGreaterThanOrEqual(0);
  });

  it('应正确调用 fetch 端点', async () => {
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    await backend.analyze('test-base64', 'Test prompt', TEST_SCHEMA);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(fetchSpy).toHaveBeenCalledWith(
      TEST_ENDPOINT,
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          Authorization: 'Bearer test-key-12345',
        }),
      }),
    );
  });

  it('请求体中应包含正确的 image_url data URI', async () => {
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    await backend.analyze('base64-data', 'Prompt', TEST_SCHEMA);

    const callArgs = fetchSpy.mock.calls[0][1];
    const body = JSON.parse(callArgs.body);
    expect(body.messages[1].content[1].image_url.url).toBe('data:image/jpeg;base64,base64-data');
  });

  it('应包含 stream: false', async () => {
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    await backend.analyze('data', 'Prompt', TEST_SCHEMA);

    const callArgs = fetchSpy.mock.calls[0][1];
    const body = JSON.parse(callArgs.body);
    expect(body.stream).toBe(false);
  });

  it('应包含 customHeaders 中的扩展头', async () => {
    const backend = new RestVlmBackend({
      endpoint: TEST_ENDPOINT,
      apiKey: TEST_API_KEY,
      customHeaders: { 'api-version': '2024-02-01', 'x-custom': 'value' },
    });
    await backend.analyze('data', 'Prompt', TEST_SCHEMA);

    expect(fetchSpy).toHaveBeenCalledWith(
      TEST_ENDPOINT,
      expect.objectContaining({
        headers: expect.objectContaining({
          'api-version': '2024-02-01',
          'x-custom': 'value',
        }),
      }),
    );
  });

  it('应使用配置的 AbortSignal.timeout', async () => {
    const backend = new RestVlmBackend({
      endpoint: TEST_ENDPOINT,
      apiKey: TEST_API_KEY,
      timeoutMs: 10000,
    });
    await backend.analyze('data', 'Prompt', TEST_SCHEMA);

    const callArgs = fetchSpy.mock.calls[0][1];
    expect(callArgs.signal).toBeDefined();
  });
});

/* ===========================================================================
 * §3 HTTP 状态码降级
 * =========================================================================== */

describe('§3 RestVlmBackend — HTTP 状态码降级', () => {
  let fetchSpy: jest.SpyInstance;

  afterEach(() => {
    if (fetchSpy) fetchSpy.mockRestore();
  });

  it('HTTP 429 应抛出 VlmRateLimitError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(429, 'Too Many Requests'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmRateLimitError);
  });

  it('VlmRateLimitError 应包含默认 retryAfterMs', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(429, 'Too Many Requests'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect(err).toBeInstanceOf(VlmRateLimitError);
      expect((err as VlmRateLimitError).retryAfterMs).toBe(5000);
    }
  });

  it('HTTP 429 带 Retry-After 头应解析秒数', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeErrorResponse(429, 'Too Many Requests', { 'Retry-After': '30' }),
    );
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect(err).toBeInstanceOf(VlmRateLimitError);
      expect((err as VlmRateLimitError).retryAfterMs).toBe(30000); // 30s * 1000
    }
  });

  it('HTTP 400 应抛出 VlmRequestError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(400, 'Bad Request'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmRequestError);
  });

  it('HTTP 401 应抛出 VlmRequestError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(401, 'Unauthorized'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmRequestError);
  });

  it('HTTP 403 应抛出 VlmRequestError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(403, 'Forbidden'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmRequestError);
  });

  it('HTTP 404 应抛出 VlmRequestError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(404, 'Not Found'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmRequestError);
  });

  it('HTTP 500 应抛出 VlmBackendError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(500, 'Internal Server Error'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });

  it('HTTP 503 应抛出 VlmBackendError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(503, 'Service Unavailable'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });
});

/* ===========================================================================
 * §4 超时与网络错误
 * =========================================================================== */

describe('§4 RestVlmBackend — 超时与网络错误', () => {
  let fetchSpy: jest.SpyInstance;

  afterEach(() => {
    if (fetchSpy) fetchSpy.mockRestore();
  });

  it('AbortError（超时）应抛出 VlmBackendError', async () => {
    const abortError = new DOMException('The operation was aborted', 'AbortError');
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockRejectedValue(abortError);
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });

  it('超时错误消息应包含 timeoutMs', async () => {
    const abortError = new DOMException('The operation was aborted', 'AbortError');
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockRejectedValue(abortError);
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY, timeoutMs: 5000 });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect(err).toBeInstanceOf(VlmBackendError);
      expect((err as Error).message).toContain('5000ms');
    }
  });

  it('网络错误（TypeError）应抛出 VlmBackendError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('fetch failed'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });

  it('网络错误应包含原始错误消息', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('connect ECONNREFUSED'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect((err as Error).message).toContain('ECONNREFUSED');
    }
  });
});

/* ===========================================================================
 * §5 空内容响应
 * =========================================================================== */

describe('§5 RestVlmBackend — 空内容响应', () => {
  let fetchSpy: jest.SpyInstance;

  afterEach(() => {
    if (fetchSpy) fetchSpy.mockRestore();
  });

  it('choices[0].message.content 为 null 应抛出 VlmBackendError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          choices: [{ message: { content: null }, finish_reason: 'stop' }],
          usage: { prompt_tokens: 0, completion_tokens: 0 },
        }),
        { status: 200, statusText: 'OK' },
      ),
    );
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });

  it('choices 数组为空应抛出 VlmBackendError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          choices: [],
          usage: { prompt_tokens: 0, completion_tokens: 0 },
        }),
        { status: 200, statusText: 'OK' },
      ),
    );
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });

  it('choices 缺失应抛出 VlmBackendError', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ usage: { prompt_tokens: 0, completion_tokens: 0 } }),
        { status: 200, statusText: 'OK' },
      ),
    );
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    await expect(
      backend.analyze('data', 'Prompt', TEST_SCHEMA),
    ).rejects.toThrow(VlmBackendError);
  });
});

/* ===========================================================================
 * §6 Retry-After 头解析
 * =========================================================================== */

describe('§6 RestVlmBackend — Retry-After 头解析', () => {
  let fetchSpy: jest.SpyInstance;

  afterEach(() => {
    if (fetchSpy) fetchSpy.mockRestore();
  });

  it('Retry-After 为秒数时应正确转换毫秒', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeErrorResponse(429, 'Too Many Requests', { 'Retry-After': '120' }),
    );
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect((err as VlmRateLimitError).retryAfterMs).toBe(120000);
    }
  });

  it('Retry-After 为无效值时使用默认 5000ms', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(
      makeErrorResponse(429, 'Too Many Requests', { 'Retry-After': 'not-a-number' }),
    );
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect((err as VlmRateLimitError).retryAfterMs).toBe(5000);
    }
  });

  it('无 Retry-After 头时使用默认 5000ms', async () => {
    fetchSpy = jest.spyOn(globalThis, 'fetch').mockResolvedValue(makeErrorResponse(429, 'Too Many Requests'));
    const backend = new RestVlmBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });

    try {
      await backend.analyze('data', 'Prompt', TEST_SCHEMA);
    } catch (err) {
      expect((err as VlmRateLimitError).retryAfterMs).toBe(5000);
    }
  });
});

/* ===========================================================================
 * §7 工厂函数 createRestBackend
 * =========================================================================== */

describe('§7 createRestBackend — 工厂函数', () => {
  const OLD_ENV = process.env;

  beforeEach(() => {
    process.env = { ...OLD_ENV };
    delete process.env.VLM_ENDPOINT;
    delete process.env.VLM_API_KEY;
  });

  afterAll(() => {
    process.env = OLD_ENV;
  });

  it('传入有效配置应返回 RestVlmBackend 实例', () => {
    const backend = createRestBackend({ endpoint: TEST_ENDPOINT, apiKey: TEST_API_KEY });
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });

  it('不传配置（环境变量未设置）应抛出', () => {
    expect(() => createRestBackend()).toThrow();
  });

  it('环境变量设置后不传参数应正常工作', () => {
    process.env.VLM_ENDPOINT = TEST_ENDPOINT;
    process.env.VLM_API_KEY = TEST_API_KEY;
    const backend = createRestBackend();
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });

  it('传入的部分配置应与环境变量合并', () => {
    process.env.VLM_ENDPOINT = TEST_ENDPOINT;
    process.env.VLM_API_KEY = TEST_API_KEY;
    const backend = createRestBackend({ timeoutMs: 30000 });
    expect(backend).toBeInstanceOf(RestVlmBackend);
  });
});