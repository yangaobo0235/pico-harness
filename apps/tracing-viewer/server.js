#!/usr/bin/env node
import { existsSync } from 'node:fs';
if (!existsSync(new URL('./dist/server.js', import.meta.url))) {
  console.error('Trace viewer bundle missing. Run npm ci && npm run build:tracing from the repository root.');
  process.exit(1);
}
await import('./dist/server.js');
