/**
 * Jest Configuration
 * Test runner setup for TypeScript + React application
 */

export default {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/src'],
  testMatch: ['**/__tests__/**/*.ts?(x)', '**/?(*.)+(spec|test).ts?(x)'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '^@domain/(.*)$': '<rootDir>/src/domain/$1',
    '^@application/(.*)$': '<rootDir>/src/application/$1',
    '^@infrastructure/(.*)$': '<rootDir>/src/infrastructure/$1',
    '^@presentation/(.*)$': '<rootDir>/src/presentation/$1',
    '^@shared/(.*)$': '<rootDir>/src/shared/$1'
  },
  setupFilesAfterEnv: ['<rootDir>/src/test/setup.ts'],
  collectCoverageFrom: [
    'src/infrastructure/http/api-contract.ts',
    'src/presentation/components/navigation/Sidebar.tsx',
    'src/presentation/pages/ForgotPassword.tsx'
  ],
  coverageThreshold: {
    global: {
      branches: 70,
      functions: 70,
      lines: 70,
      statements: 70
    }
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'mjs', 'json'],
  transform: {
    // Wrapper de ts-jest (allowJs + neutraliza import.meta) para poder
    // transpilar a CJS las dependencias ESM-only como react-router v8 (.js)
    // y cookie-es (.mjs).
    '^.+\\.(mjs|[jt]sx?)$': '<rootDir>/jest.ts-transformer.cjs'
  },
  // Por defecto Jest ignora node_modules. react-router v8 (+cookie-es) son ESM
  // puros, asi que hay que exceptuarlos para que el transform de arriba los tome.
  transformIgnorePatterns: ['/node_modules/(?!(react-router|cookie-es)/)']
}
