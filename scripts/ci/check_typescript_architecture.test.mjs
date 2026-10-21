import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { tmpdir } from 'node:os';
import { boundaryError, checkArchitecture } from './check_typescript_architecture.mjs';

test('enforces browser, server, platform and shared contract boundaries', () => {
  for (const [source, target, specifier] of [
    ['apps/tracing-viewer/src/web/app.ts', 'node:fs', 'node:fs'],
    ['apps/tracing-viewer/src/web/app.ts', 'apps/tracing-viewer/src/server/main.ts', '../../server/main'],
    ['apps/tracing-viewer/src/server/main.ts', 'react-dom/client', 'react-dom/client'],
    ['packages/contracts/src/example.ts', 'apps/tui/src/app.tsx', '../../../apps/tui/src/app'],
    ['apps/tui/src/platform/clipboard.ts', 'apps/tui/src/features/chat/model.ts', '../features/chat/model'],
    ['apps/tui/src/ui/input.tsx', 'apps/tui/src/app/store.ts', '../app/store'],
  ]) assert.ok(boundaryError(source, target, specifier));
  assert.equal(boundaryError('apps/tui/src/features/chat/view.tsx', 'apps/tui/src/ui/input.tsx', '../../ui/input'), null);
});

test('walks static, re-export and literal dynamic imports including function bodies', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'pico-imports-'));
  try {
    const folder = path.join(root, 'apps/tracing-viewer/src/web'); mkdirSync(folder, { recursive: true });
    writeFileSync(path.join(folder, 'example.ts'), "import fs from 'node:fs'; export * from '../server/types'; function run() { return import('node:path') }");
    assert.equal(checkArchitecture(root).length, 3);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
