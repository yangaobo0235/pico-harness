import type { TraceData, Span } from '@pico/contracts/tracing'

export const span: Span = {
  spanId: 'span-1',
  traceId: 'trace-1',
  traceKey: 'session-1::span-1',
  name: 'llm.call',
  kind: 'model',
  startTime: new Date().toISOString(),
  endTime: new Date().toISOString(),
  durationMs: 100,
  status: { code: 'OK' },
  isFailed: false,
  failureLabel: '',
  attributes: {
    'llm.provider': 'provider-1',
    'llm.model': 'model-1',
    'llm.usage.input_tokens': 100,
    'llm.usage.total_tokens': 120
  },
  events: [],
  displayTitle: 'Model Call',
  displaySubtitle: 'model-1'
}
export const data: TraceData = {
  generatedAt: new Date().toISOString(),
  sessions: [
    {
      sessionId: 'session-1',
      sessionKey: 'cli:test',
      agentId: 'agent-1',
      workspaceDir: '/test',
      trigger: 'cli',
      channelId: 'cli',
      resumedFrom: null,
      resumedTo: null,
      startedAt: span.startTime,
      updatedAt: span.endTime || null,
      traceCount: 1,
      traces: [
        {
          traceKey: 'session-1::span-1',
          traceId: 'trace-1',
          sessionId: 'session-1',
          sessionKey: 'cli:test',
          agentId: 'agent-1',
          workspaceDir: '/test',
          trigger: 'cli',
          channelId: 'cli',
          startTime: span.startTime,
          endTime: span.endTime || null,
          durationMs: 100,
          spanCount: 1,
          visibleSpanCount: 1,
          spans: [span],
          tree: [{ ...span, depth: 0, children: [] }],
          events: []
        }
      ]
    }
  ],
  window: {
    truncated: false,
    spans: { truncated: false, bytesRead: 100, maxBytes: 1000, filesRead: 1, filesAvailable: 1, records: 1 },
    events: { truncated: false, bytesRead: 0, maxBytes: 1000, filesRead: 0, filesAvailable: 0, records: 0 }
  }
}
