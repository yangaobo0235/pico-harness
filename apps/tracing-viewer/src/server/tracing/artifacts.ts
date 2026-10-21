import fs from 'node:fs'
import path from 'node:path'
import type { Artifact } from '@pico/contracts/tracing'
import { ARTIFACTS_DIR } from '../config/viewer.js'
export function isSafeArtifactPath(filePath: string) {
  const resolved = path.resolve(filePath)
  return resolved.startsWith(path.resolve(ARTIFACTS_DIR) + path.sep) || resolved === path.resolve(ARTIFACTS_DIR)
}

export function readArtifact(filePath: string | null): Artifact | null {
  if (!filePath || !isSafeArtifactPath(filePath)) return null
  if (!fs.existsSync(filePath)) return null
  const content = fs.readFileSync(filePath, 'utf8')
  let parsed: unknown = null
  try {
    parsed = JSON.parse(content)
  } catch {}
  return {
    path: filePath,
    content,
    parsed
  }
}
