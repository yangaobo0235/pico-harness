import type { Span, SpanNode, Trace, TraceSession } from '@pico/contracts/tracing'
import type { ViewerState } from '../../app/state'
import type { ApiCall, ApiOverview, ProviderModel, Usage } from '../details/types'

function numberOrNull(value: unknown): number | null {
  if (value == null || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}
export function usageFromSpan(span: Span): Usage {
  const attrs = span.attributes || {}
  return {
    input: numberOrNull(attrs['llm.usage.input_tokens']),
    output: numberOrNull(attrs['llm.usage.output_tokens']),
    total: numberOrNull(attrs['llm.usage.total_tokens']),
    cacheRead: numberOrNull(attrs['llm.usage.cache_read_tokens']),
    cacheWrite: numberOrNull(attrs['llm.usage.cache_write_tokens']),
    costTotal: numberOrNull(attrs['llm.usage.cost_total'])
  }
}
export function usageReported(usage: Usage): boolean {
  return Object.values(usage).some(value => value != null)
}

export function aggregateApiOverview(calls: ApiCall[]): ApiOverview {
  const summary: ApiOverview = {
    totalCalls: calls.length,
    failedCalls: 0,
    usageReportedCalls: 0,
    usageUnreportedCalls: 0,
    input: 0,
    output: 0,
    total: 0,
    cacheRead: 0,
    cacheWrite: 0,
    costTotal: 0,
    durationTotal: 0,
    avgDurationMs: 0,
    topModel: null
  }
  const counts = new Map<string, number>()
  for (const { span } of calls) {
    if (span.isFailed) summary.failedCalls++
    summary.durationTotal += span.durationMs || 0
    const usage = usageFromSpan(span)
    if (usageReported(usage)) {
      summary.usageReportedCalls++
      for (const key of ['input', 'output', 'total', 'cacheRead', 'cacheWrite', 'costTotal'] as const)
        summary[key] += usage[key] ?? 0
    } else summary.usageUnreportedCalls++
    const name = [span.attributes['llm.provider'], span.attributes['llm.model']].filter(Boolean).join(' / ')
    if (name) counts.set(name, (counts.get(name) || 0) + 1)
  }
  summary.avgDurationMs = calls.length ? Math.round(summary.durationTotal / calls.length) : 0
  summary.topModel = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || null
  return summary
}

export function groupApiByProviderModel(calls: ApiCall[]): ProviderModel[] {
  const groups = new Map<string, ProviderModel>()
  for (const { span } of calls) {
    const provider = String(span.attributes['llm.provider'] || '-')
    const model = String(span.attributes['llm.model'] || '-')
    const key = `${provider}::${model}`
    const bucket = groups.get(key) || {
      provider,
      model,
      total: 0,
      success: 0,
      failed: 0,
      reported: 0,
      unreported: 0,
      input: 0,
      cacheHit: 0,
      output: 0
    }
    groups.set(key, bucket)
    bucket.total++
    if (span.isFailed) bucket.failed++
    else bucket.success++
    const usage = usageFromSpan(span)
    if (usageReported(usage)) {
      bucket.reported++
      bucket.input += usage.input ?? 0
      bucket.cacheHit += usage.cacheRead ?? 0
      bucket.output += usage.output ?? 0
    } else bucket.unreported++
  }
  return [...groups.values()].sort((a, b) => b.total - a.total)
}

const hiddenNames = new Set(['skills.scan', 'skills.catalog_read', 'skills.cataloged'])
export function visibleTraceTree(nodes: SpanNode[]): SpanNode[] {
  return nodes
    .filter(node => !hiddenNames.has(node.name))
    .map(node => ({ ...node, children: visibleTraceTree(node.children || []) }))
}
export function sortedTraces(session: TraceSession | null): Trace[] {
  return [...(session?.traces || [])].sort((a, b) => Date.parse(b.startTime) - Date.parse(a.startTime))
}
export function preferredSpan(trace?: Trace): Span | null {
  return trace?.spans.find(span => span.name === 'llm.call') || trace?.spans[0] || null
}

/** Pure projections over a snapshot; selection and request ownership stay in React. */
export function createTraceModel(state: ViewerState) {
  const allSessions = (): TraceSession[] => state.data?.sessions || []
  const filteredSessions = (): TraceSession[] => {
    const query = state.search.trim().toLowerCase()
    return allSessions().filter(session => {
      if (state.agent !== 'all' && session.agentId !== state.agent) return false
      if (!query) return true
      const text = [
        session.agentId,
        session.sessionId,
        session.sessionKey,
        session.workspaceDir,
        ...session.traces.map(trace => `${trace.traceId} ${trace.traceKey || ''}`)
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
      return text.includes(query) || state.searchSessionIds.includes(session.sessionId)
    })
  }
  const allApiCalls = (): ApiCall[] =>
    allSessions()
      .flatMap(session =>
        session.traces.flatMap(trace =>
          trace.spans
            .filter(span => span.name === 'llm.call')
            .map(span => ({
              sessionId: session.sessionId,
              sessionKey: session.sessionKey,
              sessionAgentId: session.agentId,
              traceKey: trace.traceKey,
              traceId: trace.traceId,
              traceStartTime: trace.startTime,
              traceEndTime: trace.endTime,
              span
            }))
        )
      )
      .sort(
        (a, b) =>
          new Date(b.span.startTime || b.traceStartTime || 0).getTime() -
          new Date(a.span.startTime || a.traceStartTime || 0).getTime()
      )
  const filteredApiCalls = (): ApiCall[] => {
    const query = state.search.trim().toLowerCase()
    const now = Date.now()
    const windowMs =
      state.apiWindow === '1h'
        ? 3600000
        : state.apiWindow === '24h'
          ? 86400000
          : state.apiWindow === '7d'
            ? 604800000
            : null
    return allApiCalls().filter(entry => {
      const { span } = entry
      if (windowMs != null && now - new Date(span.startTime || entry.traceStartTime || 0).getTime() > windowMs)
        return false
      if (state.agent !== 'all' && entry.sessionAgentId !== state.agent) return false
      if (state.provider !== 'all' && span.attributes['llm.provider'] !== state.provider) return false
      if (state.model !== 'all' && span.attributes['llm.model'] !== state.model) return false
      if (!query) return true
      return [
        entry.sessionAgentId,
        entry.sessionId,
        entry.sessionKey,
        entry.traceId,
        span.spanId,
        span.displayTitle,
        span.attributes['llm.provider'],
        span.attributes['llm.model'],
        span.attributes['llm.input_preview'],
        span.attributes['llm.output_preview']
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(query)
    })
  }
  const currentSession = (): TraceSession | null =>
    allSessions().find(session => session.sessionId === state.selectedSessionId) || null
  const currentTrace = (): Trace | null => {
    const traces = sortedTraces(currentSession())
    return traces.find(trace => trace.traceKey === state.selectedTraceKey) || traces[0] || null
  }
  const currentSpan = (): Span | null => {
    const trace = currentTrace()
    return trace?.spans.find(span => span.spanId === state.selectedSpanId) || preferredSpan(trace || undefined)
  }
  const findSessionByIdentity = (id: string | null, key: string | null): TraceSession | null =>
    allSessions().find(session => (id && session.sessionId === id) || (key && session.sessionKey === key)) || null
  return {
    allSessions,
    filteredSessions,
    allApiCalls,
    filteredApiCalls,
    currentSession,
    currentTrace,
    currentSpan,
    findSessionByIdentity,
    sortedTraces,
    preferredSpan,
    usageFromSpan,
    usageReported,
    aggregateApiOverview,
    groupApiByProviderModel,
    visibleTraceTree
  }
}
