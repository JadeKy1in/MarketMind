/**
 * =============================================================================
 * RestVlmBackend — 纯 Fetch 实现的 VLM REST Backend
 * =============================================================================
 * Copyright (c) 2026 SkillFoundry Contributors
 * SPDX-License-Identifier: MIT
 *
 * 方案 A（Phase 2 实现）：零外部依赖，纯 globalThis.fetch。
 *
 * 遵循 Pro 强制补丁（Phase 2 红线）：
 *   1. 悬挂连接熔断：AbortSignal.timeout() 实现 60s 物理超时
 *   2. 强制非流式响应：stream: false 显式注入
 *   3. 精准状态码降级：429→VlmRateLimitError, 4xx→VlmRequestError, 5xx→VlmBackendError
 *   4. 端点配置：VLM_ENDPOINT / VLM_API_KEY 环境变量驱动
 *   5. customHeaders 预留 Azure api-version 扩展槽位
 *
 * 遵循 §3.7.d Safe Timeout Pattern：
 *   new Promise<T>((resolve, reject) => { ... }) + clearTimeout 在 resolve 和 reject 中
 *
 * @module vlm-backend-rest
 */

import {
  VlmBackend,
  VlmRawResponse,
  JsonSchema,
  RestBackendConfig,
  DEFAULT_REST_BACKEND_CONFIG,
  VlmRateLimitError,
  VlmRequestError,
  VlmBackendError,
} from './vlm-types';

/* ===========================================================================
 * OpenAI-compatible /v1/chat/completions 请求/响应结构
 * =========================================================================== */

/** Chat completion 请求体 */
interface ChatCompletionRequest {
  model: string;
  messages: Array<{
    role: 'system' | 'user';
    content: string | Array<{ type: string; text?: string; image_url?: { url: string; detail?: string } }>;
  }>;
  max_tokens: number;
  temperature: number;
  stream: false; // 强制非流式
}

/** Chat completion 响应体 */
interface ChatCompletionResponse {
  choices: Array<{
    message: {
      content: string | null;
    };
    finish_reason: string;
  }>;
  usage?: {
    prompt_tokens: number;
    completion_tokens: number;
  };
}

/* ===========================================================================
 * 默认模型常量（可被请求体覆盖）
 * =========================================================================== */

const DEFAULT_MODEL = 'gpt-4o';
const DEFAULT_MAX_TOKENS = 4096;
const DEFAULT_TEMPERATURE = 0.1;

/* ===========================================================================
 * RestVlmBackend — 核心实现
 * =========================================================================== */

/**
 * RestVlmBackend — 通过 REST API 调用 VLM 模型（纯 Fetch）。
 *
 * 超时模式遵循 §3.7.d Safe Timeout Pattern：
 *   使用 explicit Promise<T> + AbortController + clearTimeout，
 *   不使用 Promise.race()。
 *
 * 使用方式：
 *   const backend = createRestBackend();            // 从环境变量读取配置
 *   const backend = createRestBackend({ ... });      // 显式传入配置
 *   const result = await backend.analyze(base64, prompt, schema);
 */
export class RestVlmBackend implements VlmBackend {
  private readonly config: RestBackendConfig;

  /**
   * @param config - RestBackendConfig（可不传，会尝试从环境变量读取）
   * @throws {Error} 如果 endpoint 或 apiKey 未提供且环境变量中不存在
   */
  constructor(config?: Partial<RestBackendConfig>) {
    const endpoint = config?.endpoint ?? process.env.VLM_ENDPOINT ?? '';
    const apiKey = config?.apiKey ?? process.env.VLM_API_KEY ?? '';

    if (!endpoint) {
      throw new Error(
        '[RestVlmBackend] Missing endpoint. Provide via config.endpoint or VLM_ENDPOINT env var.',
      );
    }
    if (!apiKey) {
      throw new Error(
        '[RestVlmBackend] Missing apiKey. Provide via config.apiKey or VLM_API_KEY env var.',
      );
    }

    this.config = {
      endpoint,
      apiKey,
      timeoutMs: config?.timeoutMs ?? DEFAULT_REST_BACKEND_CONFIG.timeoutMs!,
      customHeaders: config?.customHeaders,
    };
  }

  /**
   * 分析截图——通过 REST API 调用 VLM 模型。
   *
   * @param base64Image - base64 编码的截图数据
   * @param prompt      - 分析指令 prompt
   * @param _schema     - JSON Schema（供校验使用，请求体中的 response_format 暂不使用）
   * @returns VLM 原始响应
   * @throws {VlmRateLimitError} HTTP 429
   * @throws {VlmRequestError}   HTTP 4xx（除 429）
   * @throws {VlmBackendError}   HTTP 5xx 或网络错误
   */
  async analyze(
    base64Image: string,
    prompt: string,
    _schema: JsonSchema,
  ): Promise<VlmRawResponse> {
    const startTime = Date.now();

    // 构建请求体
    const body: ChatCompletionRequest = {
      model: DEFAULT_MODEL,
      messages: [
        {
          role: 'system',
          content: 'You are a precise screenshot analyzer. Extract text and structural information exactly as visible in the screenshot. Return ONLY valid JSON without markdown code blocks or additional commentary.',
        },
        {
          role: 'user',
          content: [
            {
              type: 'text',
              text: prompt,
            },
            {
              type: 'image_url',
              image_url: {
                url: `data:image/jpeg;base64,${base64Image}`,
                detail: 'auto',
              },
            },
          ],
        },
      ],
      max_tokens: DEFAULT_MAX_TOKENS,
      temperature: DEFAULT_TEMPERATURE,
      stream: false, // 强制非流式（Phase 2 红线）
    };

    // 构建请求头
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${this.config.apiKey}`,
      ...this.config.customHeaders,
    };

    // =================================================================
    // §3.7.d Safe Timeout Pattern（不使用 Promise.race）
    // =================================================================
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), this.config.timeoutMs);
    const { signal } = controller;

    try {
      const response = await fetch(this.config.endpoint, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal,
      });

      // 清除超时定时器——请求已返回
      clearTimeout(timeoutId);

      // =============================================================
      // 精准状态码降级（Phase 2 红线）
      // =============================================================
      if (!response.ok) {
        const statusText = response.statusText || 'Unknown';
        let errorBody = '';
        try {
          errorBody = await response.text();
        } catch {
          errorBody = '(failed to read error body)';
        }
        const message = `VLM API returned ${response.status} ${statusText}: ${errorBody.substring(0, 500)}`;

        switch (response.status) {
          case 429: {
            // 尝试解析 Retry-After 头
            const retryAfter = response.headers.get('Retry-After');
            let retryAfterMs = 5000;
            if (retryAfter) {
              const parsed = parseInt(retryAfter, 10);
              if (!isNaN(parsed)) {
                // Retry-After 可以是秒数或 HTTP-date
                retryAfterMs = parsed * 1000;
              }
            }
            throw new VlmRateLimitError(message, retryAfterMs);
          }
          case 400:
          case 401:
          case 403:
          case 404:
          case 405:
          case 406:
          case 415:
            throw new VlmRequestError(message, response.status);
          default:
            // 5xx 及其他服务端错误
            throw new VlmBackendError(message);
        }
      }

      // =============================================================
      // 成功响应 —— 解析
      // =============================================================
      const data = await response.json() as ChatCompletionResponse;

      // 提取 choices[0].message.content
      const rawContent = data.choices?.[0]?.message?.content ?? '';
      if (!rawContent) {
        throw new VlmBackendError('VLM returned empty content in choices[0].message.content');
      }

      const latencyMs = Date.now() - startTime;

      return {
        rawContent,
        tokenUsage: {
          input: data.usage?.prompt_tokens ?? 0,
          output: data.usage?.completion_tokens ?? 0,
        },
        latencyMs,
      };
    } catch (err: any) {
      // 清除超时定时器——异常路径
      clearTimeout(timeoutId);

      // 如果是已定义的 VLM 错误类型，直接透传
      if (err instanceof VlmRateLimitError || err instanceof VlmRequestError || err instanceof VlmBackendError) {
        throw err;
      }

      // AbortError — 超时
      if (err.name === 'AbortError') {
        throw new VlmBackendError(
          `VLM API request timed out after ${this.config.timeoutMs}ms`,
        );
      }

      // 网络错误（fetch 本身失败）
      throw new VlmBackendError(
        `VLM API network error: ${err.message ?? 'Unknown fetch error'}`,
      );
    }
  }
}

/* ===========================================================================
 * 工厂函数
 * =========================================================================== */

/**
 * 创建一个 RestVlmBackend 实例。
 *
 * 配置优先级：
 *   process.env.VLM_ENDPOINT  + process.env.VLM_API_KEY（默认）
 *   或显式传入 RestBackendConfig 覆盖
 *
 * 使用方式：
 *   import { createRestBackend } from './vlm-backend-rest';
 *   const backend = createRestBackend();
 *
 *   // 测试/自定义端点：
 *   const backend = createRestBackend({
 *     endpoint: 'https://your-region.cognitiveservices.azure.com/openai/deployments/gpt-4-vision-preview/chat/completions?api-version=2024-02-01',
 *     apiKey: 'your-azure-key',
 *     customHeaders: { 'x-custom': 'value' },
 *   });
 */
export function createRestBackend(
  config?: Partial<RestBackendConfig>,
): RestVlmBackend {
  return new RestVlmBackend(config);
}