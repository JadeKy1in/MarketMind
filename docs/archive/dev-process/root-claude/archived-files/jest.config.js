/**
 * Jest 配置 — ts-jest 环境
 * 对齐 src/tsconfig.json 的 TypeScript 配置
 */
module.exports = {
  rootDir: 'src',
  testEnvironment: 'node',
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      tsconfig: '<rootDir>/tsconfig.json',
      isolatedModules: true,
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