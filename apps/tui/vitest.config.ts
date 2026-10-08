import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    maxWorkers: 4,
    exclude: ['dist/**', 'node_modules/**']
  }
})
