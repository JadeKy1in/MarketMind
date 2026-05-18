/**
 * Jest Configuration — Browser Automation Skill (Standalone)
 * Placed in src/ for correct root resolution
 */
module.exports = {
  rootDir: '.',
  testEnvironment: 'node',
  testMatch: [
    '**/__tests__/**/*.test.ts',
  ],
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      tsconfig: '<rootDir>/tsconfig.json',
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