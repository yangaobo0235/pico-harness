import { useCallback, useEffect, useRef, useState } from 'react'
import type { SearchHit } from '@pico/contracts/tracing'
import { ViewerClient } from '../api/client'
import { useViewer } from '../api/useViewer'
import { createPresentation } from '../features/details/presentation'
import { Details } from '../features/details/Details'
import { ApiDashboard } from '../features/api-usage/ApiDashboard'
import { resolveSelection, SessionList, TraceList, type Selection } from '../features/traces/TraceBrowser'
import { Empty } from '../ui/Empty'
import { HighlightedText } from '../ui/HighlightedText'
import { initialState, type ViewerState } from './state'

export function App({ client: suppliedClient }: { client?: ViewerClient }) {
  const [client] = useState(() => suppliedClient || new ViewerClient())
  const [state, setState] = useState(initialState)
  const [stopped, setStopped] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [shutdownError, setShutdownError] = useState('')
  const [results, setResults] = useState<SearchHit[] | null>(null)
  const [artifactRevision, setArtifactRevision] = useState(0)
  const dialog = useRef<HTMLDialogElement>(null)
  const shutdownRequest = useRef<AbortController | null>(null)
  const viewer = useViewer(client, stopped)
  const patch = useCallback((value: Partial<ViewerState>) => setState(previous => ({ ...previous, ...value })), [])
  const withData = { ...state, data: viewer.data }
  const selection = resolveSelection(withData, createPresentation(withData))
  const current = { ...withData, ...selection }
  const p = createPresentation(current)
  const { t } = p
  const session = p.currentSession()
  const trace = p.currentTrace()
  const span = p.currentSpan()
  useEffect(() => {
    if (
      selection.selectedSessionId !== state.selectedSessionId ||
      selection.selectedTraceKey !== state.selectedTraceKey ||
      selection.selectedSpanId !== state.selectedSpanId
    )
      patch({
        selectedSessionId: selection.selectedSessionId,
        selectedTraceKey: selection.selectedTraceKey,
        selectedSpanId: selection.selectedSpanId
      })
  }, [
    selection.selectedSessionId,
    selection.selectedTraceKey,
    selection.selectedSpanId,
    state.selectedSessionId,
    state.selectedTraceKey,
    state.selectedSpanId,
    patch
  ])
  const refresh = () => {
    setArtifactRevision(value => value + 1)
    void viewer.refresh(true)
  }
  const select = (value: Selection) => patch({ ...value, appView: 'trace' })
  const jump = (traceId: string, spanId?: string) => {
    const ordered = session ? [session, ...p.allSessions().filter(item => item !== session)] : p.allSessions()
    for (const candidate of ordered) {
      const target = candidate.traces.find(item => item.traceId === traceId)
      if (target) {
        patch({
          appView: 'trace',
          search: '',
          agent: 'all',
          selectedSessionId: candidate.sessionId,
          selectedTraceKey: target.traceKey,
          selectedSpanId: spanId || target.tree[0]?.spanId || target.spans[0]?.spanId || null
        })
        return
      }
    }
  }

  useEffect(() => {
    const request = new AbortController()
    if (!stopped)
      void client
        .descriptors(request.signal)
        .then(payload => patch({ descriptors: Object.fromEntries(payload.descriptors.map(item => [item.type, item])) }))
        .catch(() => {
          /* Unknown nodes retain fallback cards. */
        })
    return () => request.abort()
  }, [client, patch, stopped])
  useEffect(() => {
    const request = new AbortController()
    const query = state.search.trim()
    if (query.length < 2 || stopped) return
    const timer = window.setTimeout(() => {
      void client
        .search(query, request.signal)
        .then(payload => {
          if (!request.signal.aborted) {
            setResults(payload.results)
            patch({ searchSessionIds: payload.results.map(hit => hit.sessionId) })
          }
        })
        .catch(() => {
          if (!request.signal.aborted) setResults([])
        })
    }, 250)
    return () => {
      window.clearTimeout(timer)
      request.abort()
    }
  }, [client, state.search, stopped, patch])
  useEffect(() => {
    document.documentElement.lang = state.lang === 'zh' ? 'zh-CN' : 'en'
    document.documentElement.dataset.lang = state.lang
    try {
      localStorage.setItem('tracing:lang', state.lang)
    } catch {
      /* Private mode. */
    }
  }, [state.lang])
  useEffect(() => {
    document.body.classList.toggle('app-view-api', state.appView === 'api')
    document.body.classList.toggle('viewer-stopped', stopped)
    return () => document.body.classList.remove('app-view-api', 'viewer-stopped')
  }, [state.appView, stopped])
  useEffect(() => () => shutdownRequest.current?.abort(), [])

  async function stop() {
    if (stopping) return
    const request = new AbortController()
    shutdownRequest.current = request
    setStopping(true)
    setShutdownError('')
    try {
      await client.shutdown(request.signal)
      if (request.signal.aborted) return
      viewer.setAuto(false)
      setStopped(true)
      dialog.current?.close()
    } catch (cause) {
      if (!request.signal.aborted) {
        setShutdownError(String(cause))
        setStopping(false)
      }
    }
  }

  return (
    <>
      <header className="app-header">
        <div className="app-brand">
          <div className="app-logo" aria-hidden="true">
            ◆
          </div>
          <div className="app-brand-copy">
            <div className="app-brand-line">
              <h1>Pico</h1>
              <span className="app-product">Tracing</span>
              <span className="app-product-meta">local viewer</span>
            </div>
            <p>{t('header.subtitle')}</p>
          </div>
        </div>
        <div className="app-status">
          <span id="connectionStatus" className={`status-pill is-${viewer.status}`}>
            {t(
              viewer.status === 'connected'
                ? 'status.connected'
                : viewer.status === 'loading'
                  ? 'status.loading'
                  : 'status.disconnected'
            )}
          </span>
          {viewer.data?.window.truncated && (
            <span className="window-pill" title={t('window.title')}>
              {t('window.recent', {
                size: p.formatBytes(viewer.data.window.spans.bytesRead),
                count: viewer.data.window.spans.records
              })}
            </span>
          )}
          <span className="status-text">
            {t('header.updated')}: <strong>{p.formatTimeOnly(viewer.checkedAt)}</strong>
          </span>
          <div className="lang-switch" role="group" aria-label="Language">
            {(['en', 'zh'] as const).map(lang => (
              <button
                type="button"
                key={lang}
                className={`lang-pill${state.lang === lang ? ' is-active' : ''}`}
                onClick={() => patch({ lang })}
              >
                {lang === 'en' ? 'EN' : '中'}
              </button>
            ))}
          </div>
          <button
            type="button"
            className={`ghost-button auto-refresh-button${viewer.auto ? '' : ' is-paused'}`}
            aria-pressed={viewer.auto}
            disabled={stopped}
            onClick={() => viewer.setAuto(value => !value)}
          >
            <span className="auto-refresh-dot" aria-hidden="true" />
            {t(viewer.auto ? 'auto.on' : 'auto.off')}
          </button>
          <button
            type="button"
            className="ghost-button app-action"
            disabled={viewer.loading || stopped}
            onClick={refresh}
          >
            {t(viewer.loading ? 'action.refreshing' : 'action.refresh')}
          </button>
          <button
            type="button"
            id="shutdownButton"
            className="ghost-button danger-button"
            disabled={stopped}
            onClick={() => {
              setShutdownError('')
              dialog.current?.showModal()
            }}
          >
            {t('action.stop')}
          </button>
        </div>
      </header>
      <nav className="workspace-tabs">
        {(['api', 'trace'] as const).map(view => (
          <button
            key={view}
            type="button"
            className={`workspace-tab${state.appView === view ? ' is-active' : ''}`}
            onClick={() => patch({ appView: view })}
          >
            {t(`view.${view}`)}
          </button>
        ))}
      </nav>
      <div id="traceScene" className="scene scene-trace shell" hidden={state.appView !== 'trace'}>
        <aside className="pane pane-sessions">
          <div className="pane-head">
            <h1>{t('sessions.title')}</h1>
          </div>
          <div className="controls">
            <label className="field">
              <span>Agent</span>
              <select value={state.agent} onChange={event => patch({ agent: event.target.value })}>
                <option value="all">{t('filter.allAgent')}</option>
                {[
                  ...new Set(
                    p
                      .allSessions()
                      .map(item => item.agentId)
                      .filter((value): value is string => !!value)
                  )
                ].map(value => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="field field-search">
              <span>{t('field.search')}</span>
              <input
                type="search"
                value={state.search}
                placeholder={t('search.placeholder')}
                onChange={event => {
                  setResults(null)
                  patch({ search: event.target.value, searchSessionIds: [] })
                }}
              />
            </label>
          </div>
          {state.search.trim().length >= 2 && results !== null && (
            <div className="content-search-results">
              <div className="content-hit-head">
                {t('search.contentHits', { n: results.length, more: results.length >= 50 })}
              </div>
              {results.map(hit => (
                <button
                  type="button"
                  className="content-hit-item"
                  key={`${hit.traceKey}:${hit.spanId}`}
                  onClick={() => {
                    patch({
                      appView: 'trace',
                      agent: 'all',
                      selectedSessionId: hit.sessionId,
                      selectedTraceKey: hit.traceKey,
                      selectedSpanId: hit.spanId
                    })
                  }}
                >
                  <span className="content-hit-title">
                    {hit.title || hit.name}
                    {hit.subtitle ? <span className="content-hit-sub"> {String(hit.subtitle)}</span> : null}
                  </span>
                  <span className="content-hit-snippet">
                    <HighlightedText text={hit.snippet} query={state.search} />
                  </span>
                </button>
              ))}
              {!results.length && <div className="content-hit-empty">{t('search.noContentHits')}</div>}
            </div>
          )}
          <div className="session-list">
            {viewer.error && <Empty title={t('error.loadFailed')} copy={viewer.error} />}
            <SessionList sessions={p.filteredSessions()} state={current} p={p} select={select} />
          </div>
        </aside>
        <main className="pane pane-traces">
          <div className="pane-head">
            <h2>
              {session
                ? `${session.agentId || 'agent'} / ${p.shortId(session.sessionId, 18)}`
                : t('trace.selectSession')}
            </h2>
            <div className="head-meta">
              {session?.workspaceDir && <div>{session.workspaceDir}</div>}
              {session && <div>{session.traceCount} traces</div>}
              {p.sessionChainLabel(session)}
            </div>
          </div>
          <div className="trace-list">
            <TraceList session={session} state={current} p={p} select={select} />
          </div>
        </main>
        <section className="pane pane-details">
          <div className="pane-head">
            <h2>
              {span
                ? `${span.displayTitle}${span.name !== 'llm.call' && span.displaySubtitle ? ` / ${String(span.displaySubtitle)}` : ''}`
                : t('details.selectSpan')}
            </h2>
            <div className="tabs">
              {(['content', 'metadata', 'raw'] as const).map(tab => (
                <button
                  type="button"
                  key={tab}
                  className={`tab${state.selectedTab === tab ? ' is-active' : ''}`}
                  onClick={() => patch({ selectedTab: tab })}
                >
                  {t(`detailtab.${tab}`)}
                </button>
              ))}
            </div>
          </div>
          {span && trace ? (
            <Details
              span={span}
              trace={trace}
              state={current}
              presentation={p}
              client={client}
              revision={artifactRevision}
              jump={jump}
            />
          ) : (
            <Empty title={t('empty.title')} copy={t('empty.copy')} />
          )}
        </section>
      </div>
      <main id="apiScene" className="scene scene-api" hidden={state.appView !== 'api'}>
        <ApiDashboard
          state={current}
          p={p}
          patch={patch}
          refresh={refresh}
          loading={viewer.loading || stopped}
          select={call =>
            patch({
              appView: 'trace',
              search: '',
              agent: 'all',
              selectedSessionId: call.sessionId,
              selectedTraceKey: call.traceKey,
              selectedSpanId: call.span.spanId
            })
          }
        />
      </main>
      <dialog
        ref={dialog}
        className="shutdown-dialog"
        id="shutdownDialog"
        aria-labelledby="shutdownTitle"
        onCancel={event => {
          if (stopping) event.preventDefault()
        }}
        onClick={event => {
          if (event.target === dialog.current && !stopping) dialog.current?.close()
        }}
      >
        <div className="dialog-mark" aria-hidden="true">
          ◆
        </div>
        <div className="dialog-copy">
          <p className="dialog-kicker">{t('shutdown.kicker')}</p>
          <h2 id="shutdownTitle">{t('shutdown.title')}</h2>
          <p>{t('shutdown.copy')}</p>
          {shutdownError && (
            <p className="dialog-error" role="alert">
              {t('shutdown.failed')} {shutdownError}
            </p>
          )}
        </div>
        <div className="dialog-actions">
          <button type="button" className="ghost-button" disabled={stopping} onClick={() => dialog.current?.close()}>
            {t('action.cancel')}
          </button>
          <button
            type="button"
            className="ghost-button danger-button is-solid"
            disabled={stopping}
            onClick={() => void stop()}
          >
            {t(stopping ? 'action.stopping' : 'action.confirmStop')}
          </button>
        </div>
      </dialog>
      <div className="shutdown-state" id="shutdownState" hidden={!stopped}>
        <div className="shutdown-state-mark" aria-hidden="true">
          ◇
        </div>
        <p className="shutdown-state-kicker">{t('shutdown.stoppedKicker')}</p>
        <h2>{t('shutdown.stoppedTitle')}</h2>
        <p>{t('shutdown.stoppedCopy')}</p>
      </div>
    </>
  )
}
