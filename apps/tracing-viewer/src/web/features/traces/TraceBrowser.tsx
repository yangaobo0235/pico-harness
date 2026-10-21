import type { SpanNode, TraceSession } from '@pico/contracts/tracing'
import { Fragment } from 'react'
import type { ViewerState } from '../../app/state'
import type { Presentation } from '../details/types'
import { Empty } from '../../ui/Empty'

export interface Selection {
  selectedSessionId: string | null
  selectedTraceKey: string | null
  selectedSpanId: string | null
}
export function resolveSelection(state: ViewerState, presentation: Presentation): Selection {
  const session =
    presentation.filteredSessions().find(item => item.sessionId === state.selectedSessionId) ||
    presentation.filteredSessions()[0]
  const traces = presentation.sortedTraces(session || null)
  const trace = traces.find(item => item.traceKey === state.selectedTraceKey) || traces[0]
  const span = trace?.spans.find(item => item.spanId === state.selectedSpanId) || presentation.preferredSpan(trace)
  return {
    selectedSessionId: session?.sessionId || null,
    selectedTraceKey: trace?.traceKey || null,
    selectedSpanId: span?.spanId || null
  }
}

export function SessionList({
  sessions,
  state,
  p,
  select
}: {
  sessions: TraceSession[]
  state: ViewerState
  p: Presentation
  select(value: Selection): void
}) {
  if (!sessions.length) return <Empty title={p.t('empty.title')} copy={p.t('empty.copy')} />
  return sessions.map(session => (
    <button
      type="button"
      key={session.sessionId}
      className={`session-card${session.sessionId === state.selectedSessionId ? ' is-active' : ''}`}
      title={`${session.sessionId}\n${session.sessionKey || ''}`}
      onClick={() => {
        const trace = p.sortedTraces(session)[0]
        select({
          selectedSessionId: session.sessionId,
          selectedTraceKey: trace?.traceKey || null,
          selectedSpanId: p.preferredSpan(trace)?.spanId || null
        })
      }}
    >
      <div className="session-card-head">
        <span className="session-pill">{session.agentId || 'agent'}</span>
        <span className="session-badge">{session.traceCount} traces</span>
      </div>
      <div className="session-title-row">
        <div className="session-id">{p.shortId(session.sessionId, 18)}</div>
        <div className="session-channel">{session.channelId || 'local'}</div>
      </div>
      <div className="session-meta">
        <div>{p.t('session.startedAt', { time: p.formatTime(session.startedAt) })}</div>
        <div>{p.t('session.updatedAt', { time: p.formatTime(session.updatedAt) })}</div>
      </div>
      {p.sessionChainLabel(session) && <div className="session-chain">{p.sessionChainLabel(session)}</div>}
    </button>
  ))
}

function SpanTree({
  nodes,
  state,
  p,
  select
}: {
  nodes: SpanNode[]
  state: ViewerState
  p: Presentation
  select(value: Selection): void
}) {
  return nodes.map(node => (
    <Fragment key={node.spanId}>
      <button
        type="button"
        title={node.spanId}
        data-kind={node.kind}
        className={`span-node depth-${Math.min(node.depth, 5)}${node.spanId === state.selectedSpanId ? ' is-active' : ''}${node.isFailed ? ' is-failed' : ''}`}
        onClick={() =>
          select({
            selectedSessionId: state.selectedSessionId,
            selectedTraceKey: node.traceKey || state.selectedTraceKey,
            selectedSpanId: node.spanId
          })
        }
      >
        <div className="span-node-main">
          <div className="span-node-time">{p.formatTimeOnly(node.startTime)}</div>
          <div className="span-node-body">
            <div className="span-node-header">
              <div className="span-node-title">
                <strong>{node.displayTitle}</strong>
                {node.isFailed && <span className="summary-chip summary-chip-error">Error</span>}
              </div>
              <span className="span-chip">{p.formatDuration(node.durationMs)}</span>
            </div>
            <div className="span-node-subtitle">
              <span>{String(node.displaySubtitle || node.kind || '')}</span>
            </div>
          </div>
        </div>
      </button>
      <SpanTree nodes={node.children || []} state={state} p={p} select={select} />
    </Fragment>
  ))
}

export function TraceList({
  session,
  state,
  p,
  select
}: {
  session: TraceSession | null
  state: ViewerState
  p: Presentation
  select(value: Selection): void
}) {
  if (!session) return <Empty title={p.t('empty.title')} copy={p.t('empty.copy')} />
  return p.sortedTraces(session).map((trace, index) => {
    const summary = p.traceSummary(trace)
    const tree = p.visibleTraceTree(trace.tree || [])
    return (
      <section
        key={trace.traceKey}
        title={trace.traceKey}
        className={`trace-group${trace.traceKey === state.selectedTraceKey ? ' is-active' : ''}`}
      >
        <div className="trace-header">
          <div className="trace-title">
            <div className="trace-topline">
              <span className="trace-pill">{p.traceRoundLabel(session, index)}</span>
              <span className="span-chip trace-mini-id">{p.shortId(trace.traceId, 10)}</span>
              <span className="trace-status">{p.formatDuration(trace.durationMs)}</span>
            </div>
            <div className="trace-meta">
              <div>
                {p.formatTime(trace.startTime)} → {p.formatTime(trace.endTime)}
              </div>
              <div>{trace.spanCount} spans</div>
            </div>
          </div>
        </div>
        <div className="trace-summary">
          <span className="summary-chip">{summary.modelCalls} model</span>
          <span className="summary-chip">{summary.toolCalls} tool</span>
          <span className="summary-chip">{summary.subagents} subagent</span>
        </div>
        <div className="trace-tree">
          {tree.length ? (
            <SpanTree nodes={tree} state={state} p={p} select={select} />
          ) : (
            <div className="trace-tree-note">{p.t('trace.noNodes')}</div>
          )}
        </div>
      </section>
    )
  })
}
