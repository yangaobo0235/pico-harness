import js from '@eslint/js'
import parser from '@typescript-eslint/parser'
import ts from '@typescript-eslint/eslint-plugin'
import hooks from 'eslint-plugin-react-hooks'
import { typescriptBase } from '../../eslint.base.mjs'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  ...typescriptBase({ js, tsPlugin: ts, tsParser: parser }),
  {
    files: ['src/**/*.{ts,tsx}', 'tests/**/*.{ts,tsx}'],
    plugins: { 'react-hooks': hooks },
    rules: {
      'no-empty': ['error', { allowEmptyCatch: true }],
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'error',
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error'
    }
  },
  {
    // Existing multi-framework JSON projection and descriptor formatters are gradually typed.
    files: ['src/server/tracing/sessions.ts', 'src/web/features/details/presentation.ts', 'src/web/shared/i18n.ts'],
    rules: { '@typescript-eslint/no-explicit-any': 'off' }
  }
]
