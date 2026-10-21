import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { App } from '../../src/web/app/App'
import { ViewerClient } from '../../src/web/api/client'
import { FormattedContent } from '../../src/web/ui/FormattedContent'
import { data } from './fixtures'
import styles from '../../src/web/styles.css?inline'

function client() {
  const api = new ViewerClient()
  vi.spyOn(api, 'data').mockResolvedValue(structuredClone(data))
  vi.spyOn(api, 'descriptors').mockResolvedValue({ descriptors: [] })
  vi.spyOn(api, 'search').mockResolvedValue({ results: [] })
  vi.spyOn(api, 'shutdown').mockResolvedValue({ ok: true, stopping: true })
  return api
}
beforeEach(() => {
  localStorage.clear()
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true
  }
  HTMLDialogElement.prototype.close = function () {
    this.open = false
  }
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
})
describe('React viewer lifecycle', () => {
  it('loads sessions, selects a span, switches tabs and persists language', async () => {
    render(<App client={client()} />)
    await screen.findByText('session-1')
    expect(screen.getByText('Connected')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Metadata' }))
    await waitFor(() => expect(document.querySelector('#detailsBody')?.textContent).toContain('span-1'))
    fireEvent.click(screen.getByRole('button', { name: 'Raw' }))
    await waitFor(() => expect(document.querySelector('#detailsBody')?.textContent).toContain('"spanId"'))
    fireEvent.click(screen.getByRole('button', { name: '中' }))
    expect(localStorage.getItem('tracing:lang')).toBe('zh')
    expect(document.documentElement.lang).toBe('zh-CN')
  })
  it('shows API usage, applies filters and jumps to the original trace', async () => {
    render(<App client={client()} />)
    await screen.findByText('session-1')
    fireEvent.click(screen.getByRole('button', { name: 'API Calls' }))
    const dashboard = within(document.getElementById('apiScene')!)
    expect(dashboard.getAllByText('100').length).toBeGreaterThan(0)
    fireEvent.change(dashboard.getByLabelText('Provider'), { target: { value: 'provider-1' } })
    fireEvent.click(dashboard.getByRole('button', { name: 'Traces span-1' }))
    expect(document.body.classList.contains('app-view-api')).toBe(false)
    expect(document.querySelector('.span-node.is-active')?.getAttribute('title')).toBe('span-1')
  })
  it('debounces content search, selects a full-text hit and highlights details', async () => {
    const api = client()
    vi.spyOn(api, 'search').mockResolvedValue({
      results: [
        {
          sessionId: 'session-1',
          traceKey: 'session-1::span-1',
          traceId: 'trace-1',
          spanId: 'span-1',
          name: 'llm.call',
          title: 'Match',
          field: 'attributes',
          snippet: 'needle payload',
          startTime: data.generatedAt
        }
      ]
    })
    const snapshot = structuredClone(data)
    snapshot.sessions[0].traces[0].spans[0].attributes.payload = 'needle'
    vi.spyOn(api, 'data').mockResolvedValue(snapshot)
    render(<App client={api} />)
    await screen.findByText('session-1')
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'needle' } })
    fireEvent.click(await screen.findByRole('button', { name: 'Match needle payload' }))
    await waitFor(() => expect(document.querySelector('#detailsBody mark')?.textContent).toBe('needle'))
    expect(document.querySelector('.content-hit-snippet mark')?.textContent).toBe('needle')
    expect(api.search).toHaveBeenCalledTimes(1)
  })
  it('confirms shutdown, stops polling and displays the preserved-files state', async () => {
    const api = client()
    const sheet = document.createElement('style')
    sheet.textContent = styles
    document.head.append(sheet)
    try {
      render(
        <div id="root">
          <App client={api} />
        </div>
      )
      await screen.findByText('session-1')
      fireEvent.click(screen.getAllByRole('button', { name: 'Stop viewer' })[0])
      const dialog = screen.getByRole('dialog')
      fireEvent.click(within(dialog).getByRole('button', { name: 'Stop viewer' }))
      await waitFor(() => expect(document.body.classList.contains('viewer-stopped')).toBe(true))
      expect(api.shutdown).toHaveBeenCalledOnce()
      expect(document.getElementById('shutdownState')?.hidden).toBe(false)
      expect(getComputedStyle(document.getElementById('shutdownState')!).visibility).toBe('visible')
      expect(dialog.hasAttribute('open')).toBe(false)
    } finally {
      sheet.remove()
    }
  })
  it('keeps the confirmation open when shutdown fails', async () => {
    const api = client()
    vi.spyOn(api, 'shutdown').mockRejectedValue(new Error('offline'))
    render(<App client={api} />)
    await screen.findByText('session-1')
    fireEvent.click(screen.getAllByRole('button', { name: 'Stop viewer' })[0])
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Stop viewer' }))
    expect((await screen.findByRole('alert')).textContent).toContain('offline')
    expect(document.body.classList.contains('viewer-stopped')).toBe(false)
  })
  it('pauses after three failures and clears the refresh timer on unmount', async () => {
    const api = client()
    vi.spyOn(api, 'data').mockRejectedValue(new Error('offline'))
    vi.useFakeTimers()
    const view = render(<App client={api} />)
    await act(async () => {
      await Promise.resolve()
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000)
    })
    expect(api.data).toHaveBeenCalledTimes(3)
    expect(screen.getByRole('button', { name: 'Paused' }).getAttribute('aria-pressed')).toBe('false')
    view.unmount()
    await vi.advanceTimersByTimeAsync(60000)
    expect(api.data).toHaveBeenCalledTimes(3)
  })
  it('aborts an outstanding snapshot when unmounted', async () => {
    const api = client()
    let signal: AbortSignal | undefined
    vi.spyOn(api, 'data').mockImplementation(input => {
      signal = input
      return new Promise(() => {})
    })
    const view = render(<App client={api} />)
    view.unmount()
    expect(signal?.aborted).toBe(true)
  })
})

it('renders descriptor text safely while preserving highlights and disclosure keys', () => {
  const toggle = vi.fn()
  render(
    <FormattedContent
      markup={
        '<article><script>evil()</script><img src=x onerror=evil()><pre>&lt;img onerror=evil()&gt; needle</pre><details data-detail-key="a"><summary>More</summary>body</details><button data-jump-trace-id="trace-2" onclick="evil()">Jump</button></article>'
      }
      query="needle"
      openKeys={new Set(['a'])}
      onToggle={toggle}
    />
  )
  expect(document.querySelector('script,img,[onclick]')).toBeNull()
  expect(document.querySelector('mark')?.textContent).toBe('needle')
  expect(document.querySelector('details')?.open).toBe(true)
  expect(document.querySelector('pre')?.textContent).toContain('<img onerror=evil()>')
  expect(document.querySelector('button')?.dataset.jumpTraceId).toBe('trace-2')
})
