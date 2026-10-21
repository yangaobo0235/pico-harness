import { afterEach, describe, expect, it, vi } from 'vitest'
import { ViewerClient } from '../../src/web/api/client'
import { data } from './fixtures'

afterEach(() => vi.unstubAllGlobals())
describe('Trace API client', () => {
  it('sends ETags and preserves the previous snapshot on 304', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(data), { headers: { ETag: '"v1"' } }))
      .mockResolvedValueOnce(new Response(null, { status: 304 }))
    vi.stubGlobal('fetch', fetcher)
    const client = new ViewerClient()
    const signal = new AbortController().signal
    expect(await client.data(signal)).toEqual(data)
    expect(await client.data(signal)).toBeNull()
    expect(fetcher.mock.calls[1][1].headers).toEqual({ 'If-None-Match': '"v1"' })
  })
  it('rejects invalid responses without remembering their ETag', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"sessions":"invalid"}', { headers: { ETag: '"bad"' } }))
    vi.stubGlobal('fetch', fetcher)
    const client = new ViewerClient()
    await expect(client.data(new AbortController().signal)).rejects.toThrow('Invalid API response')
    fetcher.mockResolvedValueOnce(new Response(null, { status: 304 }))
    await client.data(new AbortController().signal)
    expect(fetcher.mock.calls[1][1].headers).toEqual({})
  })
  it('caches artifacts until manual refresh and encodes paths', async () => {
    const artifact = { path: 'D:/a&b.json', content: '{"x":1}', parsed: { x: 1 } }
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(artifact))))
    vi.stubGlobal('fetch', fetcher)
    const client = new ViewerClient()
    const signal = new AbortController().signal
    await client.artifact(artifact.path, signal)
    await client.artifact(artifact.path, signal)
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0][0]).toBe('/api/artifact?path=D%3A%2Fa%26b.json')
    client.clearArtifacts()
    await client.artifact(artifact.path, signal)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
  it('requires the server to acknowledge shutdown', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('{"ok":true,"stopping":false}'))
    vi.stubGlobal('fetch', fetcher)
    await expect(new ViewerClient().shutdown(new AbortController().signal)).rejects.toThrow()
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'POST', headers: { 'X-Pico-Viewer-Action': 'shutdown' } })
  })
})
