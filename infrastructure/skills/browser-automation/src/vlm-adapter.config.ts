/**
 * =============================================================================
 * VLM Adapter — 配置工厂函数 & 默认 Schema 模板
 * =============================================================================
 * Copyright (c) 2026 SkillFoundry Contributors
 * SPDX-License-Identifier: MIT
 *
 * 本模块提供：
 *   1. createDefaultVlmAdapterConfig() — 构造带 MockBackend 的默认配置
 *   2. Default schemas — 预定义的 JSON Schema 模板
 *   3. createVlmAdapter() — 一站式创建 VlmAdapterImpl 实例
 *
 * @module vlm-adapter.config
 */

import {
  VlmAdapterConfig,
  JsonSchema,
  DEFAULT_VLM_ADAPTER_CONFIG,
} from './vlm-types';
import { VlmAdapterImpl, MockVlmBackend } from './vlm-adapter';

/* ===========================================================================
 * 1. 默认 Schema 模板
 * =========================================================================== */

/** 通用页面内容提取 Schema */
export const PAGE_CONTENT_SCHEMA: JsonSchema = {
  type: 'object',
  properties: {
    headline: { type: 'string', description: 'Main page headline or title text' },
    textContent: { type: 'string', description: 'Main body text content' },
    navigation_links: {
      type: 'array',
      items: { type: 'string', description: 'Navigation bar link text' },
      description: 'All navigation bar link texts',
    },
    key_actions: {
      type: 'array',
      items: { type: 'string', description: 'CTA button or key interactive element text' },
      description: 'CTA buttons and key interactive elements',
    },
    has_captcha: { type: 'boolean', description: 'Whether a CAPTCHA or challenge was detected' },
    layout_type: {
      type: 'string',
      enum: ['article', 'dashboard', 'login_form', 'ecommerce', 'unknown'],
      description: 'Detected page layout category',
    },
  },
  required: ['headline', 'textContent', 'has_captcha', 'layout_type'],
};

/** 轻量级文本提取 Schema（仅提取纯文本） */
export const TEXT_ONLY_SCHEMA: JsonSchema = {
  type: 'object',
  properties: {
    textContent: { type: 'string', description: 'All visible text extracted from the page' },
  },
  required: ['textContent'],
};

/** 表单检测 Schema */
export const FORM_DETECTION_SCHEMA: JsonSchema = {
  type: 'object',
  properties: {
    has_form: { type: 'boolean', description: 'Whether a form was detected on the page' },
    form_fields: {
      type: 'array',
      items: { type: 'string', description: 'Form field label or placeholder text' },
      description: 'All detected form field labels',
    },
    submit_button_text: { type: 'string', description: 'Text of the submit/primary button' },
    has_captcha: { type: 'boolean', description: 'Whether CAPTCHA was detected' },
  },
  required: ['has_form', 'has_captcha'],
};

/** 错误/异常页面检测 Schema */
export const ERROR_PAGE_SCHEMA: JsonSchema = {
  type: 'object',
  properties: {
    is_error_page: { type: 'boolean', description: 'Whether the page indicates an error or warning' },
    error_code: { type: 'string', description: 'HTTP error code or application error code if visible' },
    error_message: { type: 'string', description: 'Error message text displayed' },
    suggests_retry: { type: 'boolean', description: 'Whether the page suggests retrying the operation' },
  },
  required: ['is_error_page'],
};

/* ===========================================================================
 * 2. 工厂函数
 * =========================================================================== */

/**
 * 创建默认的 VLM Adapter 配置（使用 MockVlmBackend）。
 *
 * 开发/测试阶段使用 MockBackend，不消耗真实 API Token。
 * Phase 4 时替换为真实 VLM Backend。
 *
 * @param schema - 期望输出结构的 JSON Schema（默认 PAGE_CONTENT_SCHEMA）
 * @returns 完整的 VLM Adapter 配置
 */
export function createDefaultVlmAdapterConfig(
  schema: JsonSchema = PAGE_CONTENT_SCHEMA,
  mockResponse?: string,
): VlmAdapterConfig {
  const backend = mockResponse
    ? new MockVlmBackend({
        rawContent: mockResponse,
        tokenUsage: { input: 100, output: 50 },
        latencyMs: 200,
      })
    : new MockVlmBackend();

  return {
    backend,
    schema,
    systemPrompt: 'You are a precise screenshot analyzer. ' +
      'Extract text and structural information exactly as visible in the screenshot.',
    maxRetries: DEFAULT_VLM_ADAPTER_CONFIG.maxRetries ?? 3,
    retryDelayMs: DEFAULT_VLM_ADAPTER_CONFIG.retryDelayMs ?? 1000,
    temperature: DEFAULT_VLM_ADAPTER_CONFIG.temperature ?? 0.1,
    maxTokens: DEFAULT_VLM_ADAPTER_CONFIG.maxTokens ?? 4096,
    preprocessing: DEFAULT_VLM_ADAPTER_CONFIG.preprocessing,
  };
}

/**
 * 一站式创建 VlmAdapterImpl 实例。
 *
 * @param config - VLM Adapter 配置（可选，默认使用 MockBackend + PAGE_CONTENT_SCHEMA）
 * @returns VlmAdapterImpl 实例
 */
export function createVlmAdapter(
  config?: VlmAdapterConfig,
): VlmAdapterImpl {
  const effectiveConfig = config ?? createDefaultVlmAdapterConfig();
  return new VlmAdapterImpl(effectiveConfig);
}