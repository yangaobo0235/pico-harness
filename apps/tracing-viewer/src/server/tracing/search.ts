import fs from 'node:fs'
import type { SearchHit } from '@pico/contracts/tracing'
import { isSafeArtifactPath } from './artifacts.js'
import { buildSessions } from './sessions.js'
const MAX_SEARCH_RESULTS = 50
const MAX_ARTIFACT_SEARCH_BYTES = 512 * 1024

function artifactTextForSearch(filePath: string) {
  if (!filePath || !isSafeArtifactPath(filePath)) return ''
  try {
    const stat = fs.statSync(filePath)
    if (!stat.isFile() || stat.size > MAX_ARTIFACT_SEARCH_BYTES) return ''
    return fs.readFileSync(filePath, 'utf8')
  } catch {
    return ''
  }
}

function makeSnippet(text: string, term: string, radius = 60) {
  const idx = text.toLowerCase().indexOf(term)
  if (idx < 0) return ''
  const start = Math.max(0, idx - radius)
  const end = Math.min(text.length, idx + term.length + radius)
  const head = start > 0 ? '…' : ''
  const tail = end < text.length ? '…' : ''
  return (head + text.slice(start, end) + tail).replace(/\s+/g, ' ').trim()
}

export function searchSpans(query: string): SearchHit[] {
  const terms = String(query || '')
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
  if (!terms.length) return []
  const results: SearchHit[] = []
  const data = buildSessions()
  for (const session of data.sessions) {
    for (const trace of session.traces || []) {
      for (const span of trace.spans || []) {
        const attrs = span.attributes || {}
        // pieces 结构为 [标签, 文本]；产物携带完整节点输入/输出。
        const pieces: [string, string][] = [
          ['title', [span.displayTitle, span.displaySubtitle, span.name].filter(Boolean).join(' ')],
          ['attributes', JSON.stringify(attrs)]
        ]
        for (const [key, value] of Object.entries(attrs)) {
          if (key.endsWith('artifact_path') && typeof value === 'string') {
            const text = artifactTextForSearch(value)
            if (text) pieces.push([key.replace('.artifact_path', ''), text])
          }
        }
        const combined = pieces
          .map(([, text]) => text)
          .join('\n')
          .toLowerCase()
        if (!terms.every((term: string) => combined.includes(term))) continue
        // 从首个搜索词命中的最具体片段生成摘要，并优先使用产物。
        let snippet = ''
        let field = ''
        for (const [label, text] of pieces.slice(2).concat([pieces[1], pieces[0]])) {
          snippet = makeSnippet(text, terms[0])
          if (snippet) {
            field = label
            break
          }
        }
        results.push({
          sessionId: session.sessionId,
          traceKey: trace.traceKey,
          traceId: trace.traceId,
          spanId: span.spanId,
          name: span.name,
          title: span.displayTitle,
          subtitle: span.displaySubtitle,
          startTime: span.startTime,
          field,
          snippet
        })
        if (results.length >= MAX_SEARCH_RESULTS * 4) break
      }
    }
  }
  results.sort((a: SearchHit, b: SearchHit) => parseTime(b.startTime) - parseTime(a.startTime))
  return results.slice(0, MAX_SEARCH_RESULTS)
}

// 加载节点类型描述符，按优先级递增并以 `type` 合并：内置、状态目录附加文件、
// --descriptors CLI。后来源覆盖前来源，见 TRACING_STANDARD.md 第 7 节。绝不抛错，坏文件跳过。

function parseTime(value: string) {
  const time = Date.parse(value || '')
  return Number.isFinite(time) ? time : 0
}
