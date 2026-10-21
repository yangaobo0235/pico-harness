import path from 'node:path'
import os from 'node:os'
import { getLogsDir } from '../tracing/log-store.js'
export const PORT = Number(process.env.TRACE_UI_PORT || process.env.TRACING_UI_PORT || 4318)
export const STATE_DIR =
  process.env.TRACING_STATE_DIR || process.env.OPENCLAW_STATE_DIR || path.join(os.homedir(), '.openclaw')
const LOGS_DIR = getLogsDir()
export const ARTIFACTS_DIR = path.join(LOGS_DIR, 'audit-artifacts')
export const STATIC_DIR = path.join(__dirname, 'ui')

export const BUNDLED_DESCRIPTORS_DIR = path.join(__dirname, 'descriptors')
export const STATE_DESCRIPTORS_DIR = path.join(STATE_DIR, 'descriptors')
export const CLI_DESCRIPTORS = (() => {
  const argv = process.argv
  const i = argv.indexOf('--descriptors')
  if (i !== -1 && argv[i + 1]) return argv[i + 1]
  const eq = argv.find((a: string) => a.startsWith('--descriptors='))
  return eq ? eq.slice('--descriptors='.length) : null
})()
export const SHUTDOWN_HEADER = 'x-pico-viewer-action'
