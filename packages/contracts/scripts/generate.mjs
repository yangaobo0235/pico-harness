import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

for (const script of ['generate-rpc.mjs', 'generate-tracing.mjs']) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(script, import.meta.url)), ...process.argv.slice(2)], {
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
