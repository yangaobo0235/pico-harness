import crypto from 'node:crypto'
import { logFingerprint } from './log-store.js'
import { buildSessions } from './sessions.js'
let cachedData: { fingerprint: string; etag: string; text: string } | null = null

export function dataSnapshot() {
  const fingerprint = logFingerprint()
  if (cachedData && cachedData.fingerprint === fingerprint) return cachedData

  const payload = buildSessions()
  const text = JSON.stringify(payload)
  const digest = crypto.createHash('sha1').update(fingerprint).digest('hex').slice(0, 20)
  cachedData = {
    fingerprint,
    etag: `"${digest}"`,
    text
  }
  return cachedData
}
