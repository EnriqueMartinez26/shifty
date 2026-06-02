// eslint.config.mjs
import js from '@eslint/js'
import tsParser from '@typescript-eslint/parser'
import typescriptPlugin from '@typescript-eslint/eslint-plugin'
import importPlugin from 'eslint-plugin-import'
import reactPlugin from 'eslint-plugin-react'
import reactHooksPlugin from 'eslint-plugin-react-hooks'

export default [
  {
    ignores: ['node_modules', 'dist', 'build', '.vite']
  },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 2023,
        sourceType: 'module',
        ecmaFeatures: {
          jsx: true
        }
      },
      globals: {
        console: 'readonly',
        document: 'readonly',
        window: 'readonly',
        localStorage: 'readonly',
        sessionStorage: 'readonly',
        fetch: 'readonly'
      }
    },
    plugins: {
      '@typescript-eslint': typescriptPlugin,
      'import': importPlugin,
      'react': reactPlugin,
      'react-hooks': reactHooksPlugin
    },
    rules: {
      // ============================================================================
      // CLEAN ARCHITECTURE ENFORCEMENT RULES
      // ============================================================================

      // Rule 1: Detect circular dependencies
      'import/no-cycle': ['error', { maxDepth: 2 }],

      // Rule 2: FORBIDDEN IMPORTS - Prevent going against Dependency Rule
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            // Domain cannot import from any layer
            {
              group: ['@domain/**/*'],
              importNames: ['*'],
              message:
                '❌ Domain layer cannot import from outside domain. ' +
                'Domain should only depend on itself. ' +
                'See docs: IMPORT_RULES.md'
            },
            // Infrastructure cannot import from application or presentation
            {
              group: ['@application/**/*', '@presentation/**/*'],
              message:
                '❌ Infrastructure cannot import from Application or Presentation layers. ' +
                'Infrastructure is the lowest layer. ' +
                'See docs: IMPORT_RULES.md'
            }
          ]
        }
      ],

      // Rule 3: Domain layer isolation - NO React or external libraries
      'no-restricted-modules': [
        'error',
        {
          paths: [
            {
              name: 'react',
              message:
                '❌ Domain layer cannot import React. ' +
                'Domain must be pure business logic without UI dependencies. ' +
                'If you need this in domain/, move to presentation/. ' +
                'See docs: IMPORT_RULES.md'
            },
            {
              name: '@tanstack/react-query',
              message:
                '❌ Domain layer cannot import React Query. ' +
                'React Query belongs in presentation/ or application/. ' +
                'See docs: IMPORT_RULES.md'
            },
            {
              name: 'axios',
              message:
                '❌ Domain layer cannot import Axios. ' +
                'HTTP client belongs in infrastructure/. ' +
                'See docs: IMPORT_RULES.md'
            }
          ]
        }
      ],

      // Rule 4: Enforce import ordering (external → domain → app → infra → presentation → shared)
      'import/order': [
        'warn',
        {
          groups: [
            ['builtin', 'external'],
            'internal',
            ['parent', 'sibling', 'index']
          ],
          pathGroups: [
            // External libraries first
            { pattern: 'react', group: 'external', position: 'before' },
            { pattern: 'react-dom', group: 'external', position: 'before' },
            { pattern: '@tanstack/**', group: 'external', position: 'before' },
            { pattern: 'axios', group: 'external', position: 'before' },

            // Domain layer
            { pattern: '@domain/**', group: 'internal', position: 'after' },

            // Application layer
            { pattern: '@application/**', group: 'internal', position: 'after' },

            // Infrastructure layer
            { pattern: '@infrastructure/**', group: 'internal', position: 'after' },

            // Presentation layer (lower priority)
            { pattern: '@presentation/**', group: 'internal', position: 'after' },

            // Shared utilities (lowest priority, comes last)
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

      // Rule 5: Require module.exports or named exports to enforce structure
      'import/prefer-default-export': 'off',
      'import/no-default-export': ['warn'],

      // Rule 6: Prevent unused imports
      'import/no-unused-modules': 'off', // Use TypeScript instead

      // ============================================================================
      // LAYER-SPECIFIC RULES
      // ============================================================================

      // Presentation layer rules
      '@typescript-eslint/no-unused-expressions': [
        'error',
        {
          allowShortCircuit: true,
          allowTernary: true,
          allowTaggedTemplates: true
        }
      ],

      // Domain & Application: no console logs in production
      'no-console': [
        'warn',
        {
          allow: ['warn', 'error'] // Allow warn/error
        }
      ],

      // ============================================================================
      // TYPESCRIPT RULES
      // ============================================================================

      '@typescript-eslint/explicit-function-return-types': [
        'warn',
        {
          allowExpressions: true,
          allowTypedFunctionExpressions: true
        }
      ],

      '@typescript-eslint/explicit-module-boundary-types': 'warn',

      '@typescript-eslint/no-explicit-any': [
        'error',
        {
          fixToUnknown: false,
          ignoreRestArgs: false
        }
      ],

      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_'
        }
      ],

      '@typescript-eslint/no-floating-promises': 'error',

      '@typescript-eslint/await-thenable': 'error',

      '@typescript-eslint/no-misused-promises': 'error',

      // ============================================================================
      // REACT RULES
      // ============================================================================

      'react/jsx-uses-react': 'off', // React 17+
      'react/react-in-jsx-scope': 'off', // React 17+
      'react/prop-types': 'off', // Using TypeScript

      'react/display-name': 'warn',
      'react/jsx-key': 'error',

      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      // ============================================================================
      // CODE QUALITY
      // ============================================================================

      'no-var': 'error',
      'prefer-const': 'error',
      'prefer-arrow-callback': 'warn',

      'eqeqeq': ['error', 'always'],
      'no-implicit-coercion': 'warn',

      'no-nested-ternary': 'warn',
      'no-unneeded-ternary': 'warn',

      'curly': ['error', 'multi-line'],
      'no-else-return': 'warn'
    }
  }
]
