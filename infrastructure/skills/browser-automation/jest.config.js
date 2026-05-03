/**
 * Jest Configuration — Browser Automation Skill (Standalone)
 *
 * 设计要点:
 *   1. rootDir 指向 src/，与项目根解耦
 *   2. 仅测试浏览器自动化相关代码
 *   3. 保持与根项目相同的测试范式（ESM-compatible, ts-jest）
 */

module.exports = {
  rootDir: 'src',
  testEnvironment: 'node',
  testMatch: [
    '**/__tests__/**/*.test.ts',
  ],
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      tsconfig: 'tsconfig.json',
    }],
  },
  moduleFileExtensions: ['ts', 'js', 'json'],
  collectCoverageFrom: [
    '!**/__tests__/**',
    '!**/node_modules/**',
    '*.ts',
  ],
  verbose: true,
  testTimeout: 30_000,
};