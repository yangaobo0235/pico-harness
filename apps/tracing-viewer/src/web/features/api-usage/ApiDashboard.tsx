import type { ViewerState } from '../../app/state'
import type { ApiCall, Presentation } from '../details/types'

export function ApiDashboard({
  state,
  p,
  patch,
  refresh,
  loading,
  select
}: {
  state: ViewerState
  p: Presentation
  patch(value: Partial<ViewerState>): void
  refresh(): void
  loading: boolean
  select(call: ApiCall): void
}) {
  const calls = p.filteredApiCalls()
  const details = calls.filter(({ span }) =>
    state.apiStatus === 'error'
      ? span.isFailed
      : state.apiStatus === 'ok'
        ? !span.isFailed
        : state.apiStatus === 'unreported'
          ? !p.usageReported(p.usageFromSpan(span))
          : true
  )
  const overview = p.aggregateApiOverview(calls)
  const groups = p.groupApiByProviderModel(calls)
  const all = p.allApiCalls()
  const filters: { key: 'agent' | 'provider' | 'model'; label: string; values: string[] }[] = [
    { key: 'agent', label: 'Agent', values: all.map(call => call.sessionAgentId || '').filter(Boolean) },
    {
      key: 'provider',
      label: 'Provider',
      values: all.map(call => String(call.span.attributes['llm.provider'] || '')).filter(Boolean)
    },
    {
      key: 'model',
      label: 'Model',
      values: all.map(call => String(call.span.attributes['llm.model'] || '')).filter(Boolean)
    }
  ]
  const stats: [string, number, string?][] = [
    ['api.stat.totalCalls', overview.totalCalls],
    ['common.success', overview.totalCalls - overview.failedCalls, 'success'],
    ['common.failure', overview.failedCalls, 'error'],
    ['api.stat.reportedToken', overview.usageReportedCalls],
    ['api.stat.unreportedToken', overview.usageUnreportedCalls, 'warning'],
    ['api.stat.inputUncached', overview.input],
    ['api.stat.inputCached', overview.cacheRead],
    ['api.stat.output', overview.output]
  ]
  return (
    <section className="api-dashboard">
      <section className="api-dashboard-board api-scope-panel">
        <div className="api-dashboard-inner api-board-scope">
          <div className="api-toolbar">
            <div className="api-toolbar-groups">
              <div className="api-window-switch" role="tablist" aria-label={p.t('api.window.aria')}>
                {['all', '7d', '24h', '1h'].map(value => (
                  <button
                    type="button"
                    role="tab"
                    aria-selected={state.apiWindow === value}
                    key={value}
                    className={`api-window-pill${state.apiWindow === value ? ' is-active' : ''}`}
                    onClick={() => patch({ apiWindow: value })}
                  >
                    {p.t(`win.${value}`)}
                  </button>
                ))}
              </div>
              <div className="api-select-group">
                {filters.map(({ key, label, values }) => (
                  <label className="api-inline-field" key={key}>
                    <span>{label}</span>
                    <select value={state[key]} onChange={event => patch({ [key]: event.target.value })}>
                      <option value="all">{p.t(key === 'agent' ? 'filter.allAgent' : 'filter.all')}</option>
                      {[...new Set(values)].map(value => (
                        <option key={value}>{value}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
            <div className="api-toolbar-side">
              <div className="api-filter-summary">
                <span className="summary-chip">{p.t('api.callCount', { n: calls.length })}</span>
              </div>
              <button type="button" className="ghost-button" disabled={loading} onClick={refresh}>
                {p.t(loading ? 'action.refreshing' : 'action.refresh')}
              </button>
            </div>
          </div>
        </div>
        {calls.length ? (
          <div className="api-board-main">
            <section className="api-board-section api-overview-panel">
              <div className="api-panel-head">
                <div className="api-panel-title">
                  <h3>{p.t('api.keyMetrics')}</h3>
                </div>
              </div>
              <div className="api-dashboard-inner">
                <section className="api-overview">
                  {stats.map(([label, value, tone]) => (
                    <article key={label} className={`api-stat-card${tone ? ` api-stat-card-${tone}` : ''}`}>
                      <div className="api-stat-label">{p.t(label)}</div>
                      <div className="api-stat-value">{value}</div>
                    </article>
                  ))}
                </section>
              </div>
            </section>
            <section className="api-board-section api-provider-panel">
              <div className="api-panel-head">
                <div className="api-panel-title">
                  <h3>{p.t('api.byProviderModel')}</h3>
                </div>
              </div>
              <div className="api-dashboard-inner">
                <div className="api-table-wrap">
                  <table className="api-table">
                    <thead>
                      <tr>
                        {[
                          'provider',
                          'model',
                          'totalCalls',
                          'success',
                          'failure',
                          'reportedToken',
                          'inputUncached',
                          'inputCached',
                          'output'
                        ].map(key => (
                          <th key={key}>{p.t(`col.${key}`)}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {groups.map(row => (
                        <tr key={`${row.provider}:${row.model}`}>
                          {[
                            row.provider,
                            row.model,
                            row.total,
                            row.success,
                            row.failed,
                            row.reported,
                            row.input,
                            row.cacheHit,
                            row.output
                          ].map((value, i) => (
                            <td key={i}>{value}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </div>
        ) : (
          <div className="api-board-empty">
            <h3>{p.t('api.noCallsTitle')}</h3>
            <p>{p.t('api.noCallsCopy')}</p>
          </div>
        )}
      </section>
      <section className="api-dashboard-panel api-detail-panel">
        <div className="api-panel-head">
          <div className="api-panel-title">
            <h3>{p.t('api.detailTitle', { n: Math.min(details.length, 500) })}</h3>
          </div>
          <div className="overview-tags">
            {[
              ['all', 'filter.all'],
              ['ok', 'common.success'],
              ['error', 'common.failure'],
              ['unreported', 'status.unreported']
            ].map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={`api-status-pill${state.apiStatus === value ? ' is-active' : ''}`}
                onClick={() => patch({ apiStatus: value })}
              >
                {p.t(label)}
              </button>
            ))}
          </div>
        </div>
        <div className="api-dashboard-inner">
          <div className="api-table-wrap">
            <table className="api-table api-call-detail-table">
              <thead>
                <tr>
                  {[
                    'time',
                    'status',
                    'provider',
                    'model',
                    'inputUncached',
                    'inputCachedShort',
                    'outputShort',
                    'totalOrError'
                  ].map(key => (
                    <th key={key}>{p.t(`col.${key}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {details.map(call => {
                  const span = call.span
                  const usage = p.usageFromSpan(span)
                  return (
                    <tr
                      key={`${call.traceKey}:${span.spanId}`}
                      className={`api-table-row${span.isFailed ? ' is-failed' : ''}`}
                      onClick={() => select(call)}
                      onKeyDown={event => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          select(call)
                        }
                      }}
                      tabIndex={0}
                      role="button"
                      aria-label={`${p.t('view.trace')} ${span.spanId}`}
                    >
                      <td>{p.formatTime(span.startTime)}</td>
                      <td>
                        <span className={`summary-chip summary-chip-${span.isFailed ? 'error' : 'success'}`}>
                          {p.t(span.isFailed ? 'common.failure' : 'common.success')}
                        </span>
                      </td>
                      <td>{String(span.attributes['llm.provider'] || '-')}</td>
                      <td>{String(span.attributes['llm.model'] || '-')}</td>
                      <td>{usage.input ?? 0}</td>
                      <td>{usage.cacheRead ?? 0}</td>
                      <td>{usage.output ?? 0}</td>
                      <td>
                        {p.usageReported(usage) ? (usage.total ?? 0) : span.failureLabel || p.t('usage.unreported')}
                      </td>
                    </tr>
                  )
                })}
                {!details.length && (
                  <tr>
                    <td className="api-table-empty" colSpan={8}>
                      {p.t('api.table.empty')}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </section>
  )
}
