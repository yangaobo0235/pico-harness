import fs from 'node:fs'
import path from 'node:path'
import type { Descriptor } from '@pico/contracts/tracing'
import { BUNDLED_DESCRIPTORS_DIR, STATE_DESCRIPTORS_DIR, CLI_DESCRIPTORS } from '../config/viewer.js'
function readDescriptorDir(dir: string): Descriptor[] {
  const out: Descriptor[] = []
  let names
  try {
    names = fs.readdirSync(dir)
  } catch {
    return out
  }
  for (const name of names) {
    if (!name.endsWith('.json')) continue
    try {
      const parsed = JSON.parse(fs.readFileSync(path.join(dir, name), 'utf8'))
      if (Array.isArray(parsed)) out.push(...parsed)
      else if (parsed && typeof parsed === 'object') out.push(parsed)
    } catch {
      // 跳过格式错误的描述符文件。
    }
  }
  return out
}

export function loadDescriptors(): Descriptor[] {
  const sources: Descriptor[] = [
    ...readDescriptorDir(BUNDLED_DESCRIPTORS_DIR),
    ...readDescriptorDir(STATE_DESCRIPTORS_DIR),
    ...(CLI_DESCRIPTORS ? readDescriptorDir(CLI_DESCRIPTORS) : [])
  ]
  const byType = new Map<string, Descriptor>()
  for (const desc of sources) {
    if (desc && typeof desc.type === 'string') byType.set(desc.type, desc)
  }
  return [...byType.values()]
}
