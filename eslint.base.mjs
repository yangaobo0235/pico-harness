// 仓库 TypeScript/Node 包共享的扁平配置基线，不包含 React。
//
// 由各工作区传入插件，避免共享配置绑定某一应用的插件解析位置。
// 浏览器与终端复用 TS 基线，各自追加环境、React 和展示风格规则。

export function typescriptBase({ js, tsPlugin, tsParser }) {
  return [
    js.configs.recommended,
    {
      files: ['**/*.{ts,tsx}'],
      languageOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
        parser: tsParser,
        parserOptions: {
          ecmaFeatures: { jsx: true }
        }
      },
      plugins: {
        '@typescript-eslint': tsPlugin
      },
      rules: {
        ...tsPlugin.configs['flat/recommended'].reduce((acc, cfg) => ({ ...acc, ...(cfg.rules ?? {}) }), {}),
        'no-undef': 'off',
        'no-unused-vars': 'off'
      }
    }
  ]
}

export default function base({ js, tsPlugin, tsParser, unusedImports, perfectionist }) {
  return [
    ...typescriptBase({ js, tsPlugin, tsParser }),
    {
      files: ['**/*.{ts,tsx}'],
      plugins: { 'unused-imports': unusedImports, perfectionist },
      rules: {
        '@typescript-eslint/consistent-type-imports': 'error',
        '@typescript-eslint/no-explicit-any': 'warn',
        '@typescript-eslint/no-unused-vars': 'off',
        'unused-imports/no-unused-imports': 'error',
        'perfectionist/sort-imports': 'error',
        curly: ['error', 'all'],
        'no-fallthrough': 'error',
        'no-unused-expressions': 'off',
        '@typescript-eslint/no-unused-expressions': 'warn',
        'no-undef': 'off',
        'no-unused-vars': 'off'
      }
    }
  ]
}
