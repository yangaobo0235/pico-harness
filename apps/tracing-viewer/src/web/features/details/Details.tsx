import { useCallback, useEffect, useRef, useState } from 'react'
import type { Span, Trace } from '@pico/contracts/tracing'
import type { ViewerState } from '../../app/state'
import { ViewerClient } from '../../api/client'
import { FormattedContent } from '../../ui/FormattedContent'
import type { LoadedArtifact, Presentation } from './types'

export function Details({
  span,
  trace,
  state,
  presentation,
  client,
  revision,
  jump
}: {
  span: Span
  trace: Trace
  state: ViewerState
  presentation: Presentation
  client: ViewerClient
  revision: unknown
  jump(traceId: string, spanId?: string): void
}) {
  const [loaded, setLoaded] = useState<{ spanId: string; artifacts: LoadedArtifact[] } | null>(null)
  const [openKeys, setOpenKeys] = useState(new Set<string>())
  const body = useRef<HTMLDivElement>(null)
  const refs = JSON.stringify(presentation.collectArtifacts(span))
  useEffect(() => {
    const request = new AbortController()
    const entries: { label: string; path: string }[] = JSON.parse(refs)
    void Promise.all(
      entries.map(async entry => {
        try {
          return { ...entry, artifact: await client.artifact(entry.path, request.signal) }
        } catch (cause) {
          return { ...entry, artifact: { path: entry.path, parsed: null, content: '', error: String(cause) } }
        }
      })
    ).then(artifacts => {
      if (!request.signal.aborted) setLoaded({ spanId: span.spanId, artifacts })
    })
    return () => request.abort()
  }, [client, refs, span.spanId, revision])

  const onToggle = useCallback((key: string, open: boolean) => {
    setOpenKeys(previous => {
      if (previous.has(key) === open) return previous
      const next = new Set(previous)
      if (open) next.add(key)
      else next.delete(key)
      return next
    })
  }, [])
  useEffect(() => {
    if (state.search.trim().length >= 2) body.current?.querySelector('mark')?.scrollIntoView?.({ block: 'center' })
  }, [state.search, span.spanId, loaded])
  const artifacts = loaded?.spanId === span.spanId ? loaded.artifacts : []
  const markup =
    state.selectedTab === 'metadata'
      ? presentation.renderMetadata(span)
      : state.selectedTab === 'raw'
        ? presentation.renderRaw(span, artifacts)
        : presentation.renderContent(span, trace, artifacts)
  return (
    <div
      className="details-body"
      id="detailsBody"
      ref={body}
      onClick={event => {
        const button = (event.target as Element).closest<HTMLElement>('[data-jump-trace-id]')
        if (button?.dataset.jumpTraceId) jump(button.dataset.jumpTraceId, button.dataset.jumpSpanId)
      }}
    >
      <FormattedContent markup={markup} query={state.search} openKeys={openKeys} onToggle={onToggle} />
    </div>
  )
}
