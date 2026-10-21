import { defineConfig } from 'vitest/config'

export default defineConfig({
  esbuild: { jsx: 'automatic' },
  server: { proxy: { '/api': 'http://127.0.0.1:4318' } },
  build: {
    outDir: 'dist/ui',
    rollupOptions: { output: { entryFileNames: 'app.js', assetFileNames: 'app[extname]' } }
  },
  test: { environment: 'jsdom', include: ['tests/**/*.test.{ts,tsx}'], restoreMocks: true }
})
