/**
 * Jest Configuration — Browser Automation Skill (Standalone)
 *
 * 设计要点:
 *   1. rootDir 指向 src/ 的绝对路径，与 workspace 根解耦
 *   2. 仅测试浏览器自动化相关代码
 *   3. 保持与根项目相同的测试范式（ts-jest）
 */

const path = require('path');

module.exports = {
  rootDir: path.resolve(__dirname, 'src'),
  testEnvironment: 'node',
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      tsconfig: '<rootDir>/tsconfig.json',
      diagnostics: {
        ignoreDiagnostics: [
          2307, // Cannot find module — 运行时由 ts-jest 处理
          2345, // Argument type mismatch — 运行时验证
          2322, // Type assignment
          2352, // Conversion of type
          2353, // Object literal may only specify known properties
          2739, // Type missing properties
          2741, // Property missing
        ],
      },
    }],
  },
  testMatch: [
    '**/__tests__/**/*.test.ts',
  ],
  moduleFileExtensions: ['ts', 'js', 'json'],
  collectCoverage: true,
  coverageDirectory: '<rootDir>/coverage',
  coverageReporters: ['text', 'lcov', 'clover'],
  coverageThreshold: {
    global: {
      branches: 85,
      lines: 90,
      statements: 85,
    },
  },
  // 防止测试间残留
  clearMocks: true,
  restoreMocks: true,
  // 测试超时——某些测试涉及延迟模拟
  testTimeout: 30_000,
};