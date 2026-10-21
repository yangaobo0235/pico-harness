import type { Span, SpanNode, Trace, TraceSession, Artifact } from '@pico/contracts/tracing'

export interface ArtifactRef {
  label: string
  path: string
}
export interface LoadedArtifact extends ArtifactRef {
  artifact: Artifact & { error?: string }
}
export interface ApiCall {
  sessionId: string
  sessionKey: string | null
  sessionAgentId: string | null
  traceKey: string
  traceId: string
  traceStartTime: string
  traceEndTime: string | null
  span: Span
}
export interface Usage {
  input: number | null
  output: number | null
  total: number | null
  cacheRead: number | null
  cacheWrite: number | null
  costTotal: number | null
}
export interface ApiOverview {
  totalCalls: number
  failedCalls: number
  usageReportedCalls: number
  usageUnreportedCalls: number
  input: number
  output: number
  total: number
  cacheRead: number
  cacheWrite: number
  costTotal: number
  durationTotal: number
  avgDurationMs: number
  topModel: string | null
}
export interface ProviderModel {
  provider: string
  model: string
  total: number
  success: number
  failed: number
  reported: number
  unreported: number
  input: number
  cacheHit: number
  output: number
}
export interface Presentation {
  t(key: string, params?: Record<string, unknown>): string
  formatTime(value: unknown): string
  formatTimeOnly(value: unknown): string
  formatDuration(ms: number | null): string
  formatBytes(value: unknown): string
  shortId(value: unknown, len?: number): string
  sessionChainLabel(session: TraceSession | null): string
  traceRoundLabel(session: TraceSession, index: number): string
  allSessions(): TraceSession[]
  filteredSessions(): TraceSession[]
  allApiCalls(): ApiCall[]
  filteredApiCalls(): ApiCall[]
  aggregateApiOverview(calls: ApiCall[]): ApiOverview
  groupApiByProviderModel(calls: ApiCall[]): ProviderModel[]
  currentSession(): TraceSession | null
  currentTrace(): Trace | null
  currentSpan(): Span | null
  sortedTraces(session: TraceSession | null): Trace[]
  preferredSpan(trace?: Trace): Span | null
  traceSummary(trace: Trace): { modelCalls: number; toolCalls: number; subagents: number }
  visibleTraceTree(nodes: SpanNode[]): SpanNode[]
  collectArtifacts(span: Span): ArtifactRef[]
  renderContent(span: Span, trace: Trace, artifacts: LoadedArtifact[]): string
  renderMetadata(span: Span): string
  renderRaw(span: Span, artifacts: LoadedArtifact[]): string
  usageFromSpan(span: Span): Usage
  usageReported(usage: Usage): boolean
}
