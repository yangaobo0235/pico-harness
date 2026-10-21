// @vitest-environment node
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { spawn, type ChildProcess } from 'node:child_process'
import { mkdtemp, mkdir, writeFile, appendFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import net from 'node:net'
import { once } from 'node:events'
import {
  validateTraceData,
  validateSearchResponse,
  validateArtifact,
  validateDescriptorsResponse,
  validateHealthResponse,
  validateShutdownResponse
} from '@pico/contracts/tracing/validation'

let process: ChildProcess
let directory: string
let base: string
let artifact: string
beforeAll(async () => {
  directory = await mkdtemp(path.join(tmpdir(), 'pico-viewer-'))
  artifact = path.join(directory, 'logs/audit-artifacts/input.json')
  await mkdir(path.dirname(artifact), { recursive: true })
  await writeFile(artifact, JSON.stringify({ messages: [{ role: 'user', content: 'needle in artifact' }] }))
  await writeFile(
    path.join(directory, 'logs/audit-spans.log'),
    JSON.stringify({
      spanId: 'span-1',
      traceId: 'trace-1',
      name: 'llm.call',
      startTime: '2026-10-20T00:00:00Z',
      endTime: '2026-10-20T00:00:01Z',
      status: { code: 'OK' },
      attributes: { 'session.id': 'session-1', 'llm.provider': 'custom', 'llm.input.artifact_path': artifact },
      events: []
    }) + '\n'
  )
  await appendFile(
    path.join(directory, 'logs/audit-spans.log'),
    [{ code: 1, message: null }, { description: 'legacy status without a code' }]
      .map((status, index) =>
        JSON.stringify({
          spanId: `legacy-${index}`,
          traceId: `legacy-${index}`,
          name: 'custom.span',
          startTime: '2026-10-20T00:00:00Z',
          endTime: '2026-10-20T00:00:01Z',
          status,
          attributes: { 'session.id': 'session-1', 'plugin.payload': { custom: [1, 'value'] } }
        })
      )
      .join('\n') + '\n'
  )
  const listener = net.createServer()
  listener.listen(0, '127.0.0.1')
  await once(listener, 'listening')
  const port = (listener.address() as net.AddressInfo).port
  await new Promise<void>(resolve => listener.close(() => resolve()))
  base = `http://127.0.0.1:${port}`
  // Exercise the same bundle and CLI state-directory argument that standalone users run.
  process = spawn(globalThis.process.execPath, ['dist/server.js', '--state-dir', directory], {
    cwd: path.resolve('.'),
    env: { ...globalThis.process.env, TRACING_UI_PORT: String(port) },
    windowsHide: true
  })
  let stderr = ''
  process.stderr?.on('data', chunk => {
    stderr += String(chunk)
  })
  for (let attempt = 0; attempt < 80; attempt++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) return
    } catch {
      /* Wait for listen. */
    }
    if (process.exitCode !== null) throw new Error(stderr)
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  throw new Error(`Viewer did not start: ${stderr}`)
})
afterAll(async () => {
  if (process && process.exitCode === null) {
    const exited = once(process, 'exit')
    process.kill()
    await exited
  }
  if (directory) await rm(directory, { recursive: true, force: true })
})

describe('standalone Trace service contracts', () => {
  it('serves the React entry and its JS/CSS without development dependencies', async () => {
    const page = await (await fetch(base)).text()
    expect(page).toContain('id="root"')
    expect(page).toContain('/app.js')
    expect(page).toContain('/app.css')
    for (const asset of ['app.js', 'app.css']) expect((await fetch(`${base}/${asset}`)).status).toBe(200)
  })
  it('preserves health, normalized history, window and ETag shapes', async () => {
    expect(validateHealthResponse(await (await fetch(`${base}/api/health`)).json())).toBe(true)
    const response = await fetch(`${base}/api/data`)
    const data = await response.json()
    expect(validateTraceData(data), JSON.stringify(validateTraceData.errors)).toBe(true)
    if (!validateTraceData(data)) throw new Error('Invalid history')
    expect(data.sessions[0].sessionId).toBe('session-1')
    const history = data.sessions.flatMap(session => session.traces.flatMap(trace => trace.spans))
    expect(history.find(span => span.spanId === 'legacy-0')?.status).toEqual({ code: 1, message: null })
    expect(history.find(span => span.spanId === 'legacy-1')?.status).toEqual({
      description: 'legacy status without a code'
    })
    expect(history.find(span => span.spanId === 'legacy-0')?.attributes['plugin.payload']).toEqual({
      custom: [1, 'value']
    })
    const unchanged = await fetch(`${base}/api/data`, { headers: { 'If-None-Match': response.headers.get('etag')! } })
    expect(unchanged.status).toBe(304)
  })
  it('searches complete artifact contents and preserves descriptor extensions', async () => {
    const result = await (await fetch(`${base}/api/search?q=needle%20artifact`)).json()
    expect(validateSearchResponse(result), JSON.stringify(validateSearchResponse.errors)).toBe(true)
    if (!validateSearchResponse(result)) throw new Error('Invalid search')
    expect(result.results[0].spanId).toBe('span-1')
    const descriptors = await (await fetch(`${base}/api/descriptors`)).json()
    expect(validateDescriptorsResponse(descriptors), JSON.stringify(validateDescriptorsResponse.errors)).toBe(true)
    if (!validateDescriptorsResponse(descriptors)) throw new Error('Invalid descriptors')
    expect(descriptors.descriptors.some((item: { type: string }) => item.type === 'llm.call')).toBe(true)
  })
  it('serves referenced artifacts while rejecting paths outside their directory', async () => {
    const response = await (await fetch(`${base}/api/artifact?path=${encodeURIComponent(artifact)}`)).json()
    expect(validateArtifact(response)).toBe(true)
    if (!validateArtifact(response)) throw new Error('Invalid artifact')
    expect(response.parsed).toEqual({ messages: [{ role: 'user', content: 'needle in artifact' }] })
    expect(
      (await fetch(`${base}/api/artifact?path=${encodeURIComponent(path.join(directory, 'logs/audit-spans.log'))}`))
        .status
    ).toBe(404)
  })
  it('rejects unguarded or foreign-origin shutdown and acknowledges an explicit local request', async () => {
    expect((await fetch(`${base}/api/shutdown`)).status).toBe(403)
    expect(
      (
        await fetch(`${base}/api/shutdown`, {
          method: 'POST',
          headers: { 'X-Pico-Viewer-Action': 'shutdown', Origin: 'https://example.com' }
        })
      ).status
    ).toBe(403)
    const exited = once(process, 'exit')
    const response = await fetch(`${base}/api/shutdown`, {
      method: 'POST',
      headers: { 'X-Pico-Viewer-Action': 'shutdown', Origin: base }
    })
    expect(validateShutdownResponse(await response.json())).toBe(true)
    await exited
  })
})
