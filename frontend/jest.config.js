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
  // Todo src, no una lista a mano: antes el 70% global media solo cinco
  // archivos (F9-08, F12-02). runtime-env y
  // shared/utils/env leen import.meta y ts-jest no los puede instrumentar.
  collectCoverageFrom: [
    'src/**/*.{ts,tsx}',
    '!src/**/*.test.{ts,tsx}',
    '!src/**/*.d.ts',
    '!src/test/**',
    '!src/main.tsx',
    '!src/infrastructure/http/runtime-env.ts',
    '!src/shared/utils/env.ts'
  ],
  // Trinquete por capa: el piso es lo medido el 2026-09-24 (redondeado hacia
  // abajo). Solo se sube; bajarlo exige justificarlo en el PR.
  coverageThreshold: {
    './src/domain/': { statements: 88, branches: 77, functions: 79, lines: 88 },
    // F9-08 (2026-09-30): medido con solo los tests de application (67/74/59/66)
    // menos 2 puntos; la corrida completa de CI solo puede dar mas.
    './src/application/': { statements: 65, branches: 72, functions: 57, lines: 64 },
    './src/infrastructure/': { statements: 71, branches: 68, functions: 59, lines: 69 },
    './src/shared/': { statements: 89, branches: 67, functions: 84, lines: 90 },
    './src/presentation/': { statements: 45, branches: 41, functions: 30, lines: 45 }
  },
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'mjs', 'json'],
  transform: {
    // Wrapper de ts-jest (allowJs + neutraliza import.meta) para poder
    // transpilar a CJS las dependencias ESM-only como react-router v8 (.js)
    // y cookie-es (.mjs).
    '^.+\\.(mjs|[jt]sx?)$': '<rootDir>/jest.ts-transformer.cjs'
  },
  // Por defecto Jest ignora node_modules. react-router v8, su dependencia
  // @remix-run/route-pattern y cookie-es son ESM puros: el transform de arriba
  // tiene que convertirlos a CommonJS para Jest.
  transformIgnorePatterns: ['/node_modules/(?!(react-router|cookie-es|@remix-run/route-pattern)/)']
}
