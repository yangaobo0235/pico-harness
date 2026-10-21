import type { ValidateFunction } from 'ajv'
import type {
  Artifact,
  DescriptorsResponse,
  SearchResponse,
  ShutdownResponse,
  TraceData
} from '@pico/contracts/tracing'
import {
  validateArtifact,
  validateDescriptorsResponse,
  validateSearchResponse,
  validateShutdownResponse,
  validateTraceData
} from '@pico/contracts/tracing/validation'

async function read<T>(response: Response, validate: ValidateFunction<T>): Promise<T> {
  if (!response.ok) throw new Error(`API failed with status ${response.status}`)
  const payload: unknown = await response.json()
  if (!validate(payload)) throw new Error(`Invalid API response: ${validate.errors?.[0]?.instancePath || '/'}`)
  return payload
}

/** One client per mounted viewer: ETags and artifact caching never leak between instances. */
export class ViewerClient {
  private etag: string | null = null
  private artifacts = new Map<string, Artifact>()

  async data(signal: AbortSignal): Promise<TraceData | null> {
    const response = await fetch('/api/data', {
      signal,
      cache: 'no-store',
      headers: this.etag ? { 'If-None-Match': this.etag } : {}
    })
    if (response.status === 304) return null
    const data = await read(response, validateTraceData)
    this.etag = response.headers.get('ETag')
    return data
  }

  async descriptors(signal: AbortSignal): Promise<DescriptorsResponse> {
    return read(await fetch('/api/descriptors', { signal }), validateDescriptorsResponse)
  }

  async search(query: string, signal: AbortSignal): Promise<SearchResponse> {
    return read(await fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal }), validateSearchResponse)
  }

  async artifact(path: string, signal: AbortSignal): Promise<Artifact> {
    const cached = this.artifacts.get(path)
    if (cached) return cached
    const data = await read(await fetch(`/api/artifact?path=${encodeURIComponent(path)}`, { signal }), validateArtifact)
    if (!signal.aborted) this.artifacts.set(path, data)
    return data
  }

  clearArtifacts() {
    this.artifacts.clear()
  }

  async shutdown(signal: AbortSignal): Promise<ShutdownResponse> {
    return read(
      await fetch('/api/shutdown', {
        method: 'POST',
        headers: { 'X-Pico-Viewer-Action': 'shutdown' },
        signal
      }),
      validateShutdownResponse
    )
  }
}
