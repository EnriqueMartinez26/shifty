import path from 'node:path'
import { fileURLToPath } from 'node:url'

import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'
import typescriptPlugin from '@typescript-eslint/eslint-plugin'
import importPlugin from 'eslint-plugin-import'
import reactPlugin from 'eslint-plugin-react'
import reactHooksPlugin from 'eslint-plugin-react-hooks'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const commonLanguageOptions = {
  parser: tsParser,
  parserOptions: {
    ecmaVersion: 2023,
    sourceType: 'module',
    project: './tsconfig.json',
    tsconfigRootDir: __dirname,
    ecmaFeatures: {
      jsx: true
    }
  },
  globals: {
    confirm: 'readonly',
    console: 'readonly',
    crypto: 'readonly',
    document: 'readonly',
    fetch: 'readonly',
    localStorage: 'readonly',
    performance: 'readonly',
    sessionStorage: 'readonly',
    setTimeout: 'readonly',
    window: 'readonly'
  }
}

const commonPlugins = {
  '@typescript-eslint': typescriptPlugin,
  import: importPlugin,
  react: reactPlugin,
  'react-hooks': reactHooksPlugin
}

export default [
  {
    ignores: ['node_modules', 'dist', 'build', '.vite']
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: commonLanguageOptions,
    plugins: commonPlugins,
    settings: {
      react: {
        version: 'detect'
      },
      'import/resolver': {
        typescript: {
          project: './tsconfig.json'
        },
        node: true
      }
    },
    rules: {
      ...js.configs.recommended.rules,

      'import/no-cycle': ['error', { maxDepth: 2 }],
      'import/no-default-export': 'off',
      'import/no-unused-modules': [
        'error',
        {
          unusedExports: true,
          missingExports: false,
          ignoreExports: ['src/main.tsx', 'src/test/**', 'src/**/*.test.ts']
        }
      ],
      'import/order': [
        'warn',
        {
          groups: [['builtin', 'external'], 'internal', ['parent', 'sibling', 'index']],
          pathGroups: [
            { pattern: 'react', group: 'external', position: 'before' },
            { pattern: 'react-dom', group: 'external', position: 'before' },
            { pattern: '@tanstack/**', group: 'external', position: 'before' },
            { pattern: 'axios', group: 'external', position: 'before' },
            { pattern: '@domain/**', group: 'internal', position: 'after' },
            { pattern: '@application/**', group: 'internal', position: 'after' },
            { pattern: '@infrastructure/**', group: 'internal', position: 'after' },
            { pattern: '@presentation/**', group: 'internal', position: 'after' },
            { pattern: '@shared/**', group: 'internal', position: 'after' }
          ],
          pathGroupsExcludedImportTypes: ['react'],
          'newlines-between': 'always',
          alphabetize: {
            order: 'asc',
            caseInsensitive: true
          }
        }
      ],
      'import/prefer-default-export': 'off',

      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/explicit-function-return-type': 'off',
      '@typescript-eslint/explicit-module-boundary-types': 'off',
      '@typescript-eslint/no-explicit-any': [
        'warn',
        {
          fixToUnknown: false,
          ignoreRestArgs: false
        }
      ],
      '@typescript-eslint/no-floating-promises': 'warn',
      '@typescript-eslint/no-misused-promises': 'warn',
      '@typescript-eslint/no-unused-expressions': [
        'error',
        {
          allowShortCircuit: true,
          allowTernary: true,
          allowTaggedTemplates: true
        }
      ],
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_'
        }
      ],

      curly: ['error', 'multi-line'],
      eqeqeq: ['error', 'always'],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      'no-else-return': 'warn',
      'no-implicit-coercion': 'warn',
      'no-nested-ternary': 'off',
      'no-unneeded-ternary': 'warn',
      'no-unused-vars': 'off',
      'no-var': 'error',
      'prefer-arrow-callback': 'warn',
      'prefer-const': 'error',

      'react/display-name': 'warn',
      'react/jsx-key': 'error',
      'react/jsx-uses-react': 'off',
      'react/prop-types': 'off',
      'react/react-in-jsx-scope': 'off',
      'react-hooks/exhaustive-deps': 'warn',
      'react-hooks/rules-of-hooks': 'error'
    }
  },
  {
    files: ['src/**/*.test.ts', 'src/test/**/*.{ts,tsx}'],
    languageOptions: {
      globals: {
        afterEach: 'readonly',
        beforeAll: 'readonly',
        beforeEach: 'readonly',
        describe: 'readonly',
        expect: 'readonly',
        it: 'readonly',
        jest: 'readonly'
      }
    },
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      'import/no-unused-modules': 'off'
    }
  },
  {
    files: ['src/domain/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@application/**', '@infrastructure/**', '@presentation/**'],
              message: 'Domain cannot depend on application, infrastructure, or presentation.'
            }
          ],
          paths: [
            {
              name: 'react',
              message: 'Domain must stay free of React dependencies.'
            },
            {
              name: '@tanstack/react-query',
              message: 'React Query belongs outside the domain layer.'
            },
            {
              name: 'axios',
              message: 'HTTP clients belong outside the domain layer.'
            }
          ]
        }
      ]
    }
  },
  {
    files: ['src/infrastructure/**/*.{ts,tsx}'],
    rules: {
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@presentation/**'],
              message: 'Infrastructure cannot depend on presentation.'
            }
          ]
        }
      ]
    }
  }
]
