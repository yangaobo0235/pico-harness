import { build as buildWeb } from 'vite'
import { build } from 'esbuild'
import { mkdir, cp, writeFile } from 'node:fs/promises'

await buildWeb()
await mkdir('dist', { recursive: true })
await build({
  entryPoints: { server: 'src/server/main.ts', 'log-store': 'src/server/tracing/log-store.ts' },
  bundle: true,
  platform: 'node',
  target: 'node22',
  format: 'cjs',
  outdir: 'dist'
})
await writeFile('dist/package.json', '{"type":"commonjs"}\n')
await cp('descriptors', 'dist/descriptors', { recursive: true })
