import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { Descriptor, Span } from '@pico/contracts/tracing'
import descriptors from '../../descriptors/pico.json'
import { App } from '../../src/web/app/App'
import { ViewerClient } from '../../src/web/api/client'
import { data } from './fixtures'

afterEach(cleanup)

it.each([
  {
    name: 'tool.call',
    attributes: { 'tool.input.artifact_path': '/input', 'tool.output.artifact_path': '/output' },
    expected: ['Tool Input', 'Tool Output', 'tool-result']
  },
  {
    name: 'memory.recall',
    attributes: { 'memory.query': 'project conventions', 'memory.recall.artifact_path': '/memory', 'memory.hits': 1 },
    expected: ['Recall · Input', 'Recall · Output', 'remembered convention']
  },
  {
    name: 'memory.store',
    attributes: { 'memory.store.artifact_path': '/store' },
    expected: ['Store · Input', 'Store · Output', 'saved message']
  },
  {
    name: 'skill.read',
    attributes: {
      'skill.name': 'example-skill',
      'skill.source': 'local',
      'skill.path': '/skills/example',
      'skill.result_preview': 'skill instructions'
    },
    expected: ['Skill Input', 'Skill Output', 'skill instructions']
  },
  {
    name: 'subagent.call',
    attributes: { 'subagent.task': 'inspect project', 'subagent.result.artifact_path': '/subagent' },
    expected: ['Subagent Input', 'Subagent Output', 'inspection complete']
  }
])(
  'keeps the built-in $name descriptor and artifact payload visible in React',
  async ({ name, attributes, expected }) => {
    localStorage.clear()
    const snapshot = structuredClone(data)
    const trace = snapshot.sessions[0].traces[0]
    const span: Span = { ...trace.spans[0], name, attributes, displayTitle: name }
    trace.spans = [span]
    trace.tree = [{ ...span, depth: 0, children: [] }]
    const payloads: Record<string, unknown> = {
      '/input': { params: { path: '/example' } },
      '/output': { result: 'tool-result' },
      '/memory': [{ text: 'remembered convention', score: 0.9 }],
      '/store': { messages: [{ role: 'user', content: 'saved message' }] },
      '/subagent': { result: 'inspection complete' }
    }
    const api = new ViewerClient()
    vi.spyOn(api, 'data').mockResolvedValue(snapshot)
    vi.spyOn(api, 'descriptors').mockResolvedValue({ descriptors: descriptors as Descriptor[] })
    vi.spyOn(api, 'artifact').mockImplementation(async path => ({ path, content: '', parsed: payloads[path] }))
    render(<App client={api} />)
    await screen.findByText('session-1')
    await waitFor(() => {
      const body = document.getElementById('detailsBody')!
      for (const value of expected) expect(body.textContent).toContain(value)
    })
  }
)

it('keeps model tool disclosures open across a snapshot refresh', async () => {
  localStorage.clear()
  const snapshot = structuredClone(data)
  snapshot.sessions[0].traces[0].spans[0].attributes['llm.input.artifact_path'] = '/model-input'
  const api = new ViewerClient()
  vi.spyOn(api, 'data').mockImplementation(async () => structuredClone(snapshot))
  vi.spyOn(api, 'descriptors').mockResolvedValue({ descriptors: descriptors as Descriptor[] })
  vi.spyOn(api, 'artifact').mockResolvedValue({
    path: '/model-input',
    content: '',
    parsed: {
      messages: [{ role: 'user', content: 'hello' }],
      tools: [{ type: 'function', function: { name: 'read_file', parameters: {} } }]
    }
  })
  render(<App client={api} />)
  const summary = await screen.findByText('Tools')
  const disclosure = summary.closest('details')!
  disclosure.open = true
  fireEvent(disclosure, new Event('toggle'))
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }))
  await waitFor(() => expect(api.data).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(document.querySelector('details')?.open).toBe(true))
  expect(document.getElementById('detailsBody')?.textContent).toContain('read_file')
})
