import type { TraceData } from '@pico/contracts/tracing'
import fs from 'node:fs'
import { readJsonlWindow } from './log-store.js'
function parseTime(value: any): any {
  const parsed = Date.parse(value || '')
  return Number.isFinite(parsed) ? parsed : 0
}

function durationMs(start: any, end: any): any {
  const a = parseTime(start)
  const b = parseTime(end)
  if (!a || !b) return 0
  return Math.max(0, b - a)
}

function compareSpansByTime(a: any, b: any): any {
  const timeDiff = parseTime(a.startTime) - parseTime(b.startTime)
  if (timeDiff !== 0) return timeDiff
  const rank = (span: any) => {
    if (span?.name === 'session.turn') return 0
    if (span?.name === 'llm.call') return 1
    if (span?.name === 'subagent.call') return 2
    return 3
  }
  const rankDiff = rank(a) - rank(b)
  if (rankDiff !== 0) return rankDiff
  return String(a?.spanId || '').localeCompare(String(b?.spanId || ''))
}

function pickMostFrequent(values: any): any {
  const counts = new Map()
  for (const value of values || []) {
    if (!value) continue
    counts.set(value, (counts.get(value) || 0) + 1)
  }
  return (
    [...counts.entries()].sort((a: any, b: any) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0]?.[0] ||
    null
  )
}

function parseJsonMaybe(value: any): any {
  if (value == null) return null
  if (typeof value === 'object') return value
  if (typeof value !== 'string') return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function readJsonFileMaybe(filePath: any): any {
  if (!filePath || typeof filePath !== 'string') return null
  if (!fs.existsSync(filePath)) return null
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'))
  } catch {
    return null
  }
}

function dedupeSpans(spans: any): any {
  const byId = new Map()
  for (const span of spans) {
    if (!span || !span.spanId) continue
    byId.set(span.spanId, span)
  }
  return [...byId.values()]
}

function isUuidLike(value: any): any {
  return typeof value === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
}

function buildSessionIdentityIndex(spans: any): any {
  const countsBySessionKey = new Map()
  const metaBySessionId = new Map()

  for (const span of spans) {
    if (span?.sessionKey) {
      if (!countsBySessionKey.has(span.sessionKey)) countsBySessionKey.set(span.sessionKey, new Map())
      const counts = countsBySessionKey.get(span.sessionKey)
      const sessionId = span.sessionId || ''
      counts.set(sessionId, (counts.get(sessionId) || 0) + 1)
    }

    if (span?.sessionId) {
      const current = metaBySessionId.get(span.sessionId) || {
        keyCounts: new Map(),
        agentCounts: new Map(),
        workspaceCounts: new Map()
      }
      if (span.sessionKey) current.keyCounts.set(span.sessionKey, (current.keyCounts.get(span.sessionKey) || 0) + 1)
      if (span.agentId) current.agentCounts.set(span.agentId, (current.agentCounts.get(span.agentId) || 0) + 1)
      if (span.workspaceDir)
        current.workspaceCounts.set(span.workspaceDir, (current.workspaceCounts.get(span.workspaceDir) || 0) + 1)
      metaBySessionId.set(span.sessionId, current)
    }
  }

  const canonicalIdBySessionKey = new Map()
  for (const [sessionKey, counts] of countsBySessionKey.entries()) {
    const entries = [...counts.entries()].filter(([sessionId]: any) => sessionId)
    if (!entries.length) continue
    entries.sort((a: any, b: any) => {
      const [idA, countA] = a
      const [idB, countB] = b
      const uuidBias = Number(isUuidLike(idB)) - Number(isUuidLike(idA))
      if (uuidBias !== 0) return uuidBias
      if (countB !== countA) return countB - countA
      return idA.localeCompare(idB)
    })
    canonicalIdBySessionKey.set(sessionKey, entries[0][0])
  }

  const preferredValue = (counts: any) =>
    [...counts.entries()].sort((a: any, b: any) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))[0]?.[0] ||
    null

  const sessionMetaById = new Map()
  for (const [sessionId, meta] of metaBySessionId.entries()) {
    sessionMetaById.set(sessionId, {
      sessionKey: preferredValue(meta.keyCounts),
      agentId: preferredValue(meta.agentCounts),
      workspaceDir: preferredValue(meta.workspaceCounts)
    })
  }

  return { canonicalIdBySessionKey, sessionMetaById }
}

function projectSpanForDisplay(span: any, identityIndex: any): any {
  const { canonicalIdBySessionKey, sessionMetaById } = identityIndex
  const canonicalIdForKey = span.sessionKey ? canonicalIdBySessionKey.get(span.sessionKey) : null
  const canonicalMetaForSession = span.sessionId ? sessionMetaById.get(span.sessionId) || null : null
  const parentAliasSessionId =
    span.sessionId && !isUuidLike(span.sessionId) ? canonicalIdBySessionKey.get(span.sessionId) || null : null
  const resolvedSessionId = isUuidLike(span.sessionId)
    ? span.sessionId
    : span.sessionId || parentAliasSessionId || canonicalIdForKey || null

  if (span.name === 'subagent.call') {
    const parentSessionId = isUuidLike(span.sessionId)
      ? span.sessionId
      : parentAliasSessionId || canonicalIdForKey || span.sessionId || null
    const parentMeta = (parentSessionId && sessionMetaById.get(parentSessionId)) || canonicalMetaForSession || {}
    return {
      ...span,
      sessionId: parentSessionId,
      sessionKey: parentMeta.sessionKey || span.sessionKey || null,
      agentId: parentMeta.agentId || span.agentId || null,
      workspaceDir: parentMeta.workspaceDir || span.workspaceDir || null
    }
  }

  return {
    ...span,
    sessionId: resolvedSessionId,
    sessionKey: span.sessionKey || canonicalMetaForSession?.sessionKey || null,
    agentId: span.agentId || canonicalMetaForSession?.agentId || null,
    workspaceDir: span.workspaceDir || canonicalMetaForSession?.workspaceDir || null
  }
}

function normalizeSpan(span: any): any {
  const attrs = span.attributes || {}
  const kind = attrs['span.type'] || 'internal'
  const failure = detectSpanFailure(span, attrs)
  return {
    traceKey: null,
    traceId: span.traceId,
    spanId: span.spanId,
    parentSpanId: span.parentSpanId || null,
    name: span.name,
    kind,
    startTime: span.startTime,
    endTime: span.endTime,
    durationMs: durationMs(span.startTime, span.endTime),
    status: span.status || { code: 'OK', message: '' },
    isFailed: failure.isFailed,
    failureLabel: failure.failureLabel,
    attributes: attrs,
    events: span.events || [],
    sessionId: attrs['session.id'] || null,
    sessionKey: attrs['session.key'] || null,
    agentId: attrs['agent.id'] || null,
    workspaceDir: attrs['workspace.dir'] || null,
    runId: attrs['run.id'] || null,
    trigger: attrs.trigger || null,
    channelId: attrs['channel.id'] || null,
    displayTitle: buildSpanTitle(span.name, attrs),
    displaySubtitle: buildSpanSubtitle(span.name, attrs)
  }
}

function detectSpanFailure(span: any, attrs: any): any {
  const statusCode = String(span?.status?.code || 'OK').toUpperCase()
  if (statusCode && statusCode !== 'OK') {
    return { isFailed: true, failureLabel: statusCode }
  }

  if (span?.name === 'llm.call') {
    const outputPreview = parseJsonMaybe(attrs['llm.output_preview'])
    const stopReason = outputPreview?.stopReason
    const errorMessage = outputPreview?.errorMessage
    if (stopReason && String(stopReason).toLowerCase() === 'error') {
      return { isFailed: true, failureLabel: errorMessage ? 'model error' : 'error' }
    }
    if (errorMessage) {
      return { isFailed: true, failureLabel: 'model error' }
    }
  }

  if (span?.name === 'tool.call') {
    const preview = parseJsonMaybe(attrs['tool.result_preview'])
    const toolError = attrs['tool.error']
    if (toolError) return { isFailed: true, failureLabel: 'tool error' }
    if (preview?.status && String(preview.status).toLowerCase() === 'error') {
      return { isFailed: true, failureLabel: preview.error ? 'tool error' : 'error result' }
    }
    if (preview?.error) return { isFailed: true, failureLabel: 'tool error' }
  }

  if (span?.name === 'subagent.call') {
    // 只有真实失败状态才算失败。OpenClaw 用 'accepted' 表示成功 spawn，Pico 使用
    // 'ok' / 'completed' / 'ended'。把所有非 'accepted' 状态标红会误伤成功的 Pico 子智能体；
    // 上方检查的跨度自身 status.code 才是权威值。
    const subagentStatus = String(attrs['subagent.status'] || '').toLowerCase()
    if (subagentStatus === 'error' || subagentStatus === 'failed') {
      return { isFailed: true, failureLabel: subagentStatus }
    }
  }

  if (span?.name === 'skill.read') {
    // OpenClaw 的 skill.read 通过 skill.read.* 字节/SHA 属性表示成功；Pico 的
    // read_file→skill.read 通过 skill.result_preview、skill.path、tool.output.artifact_bytes
    // 表示。任一属性族都可作为真实读取证据，避免成功的 Pico 读取仅因缺少 OpenClaw 属性而
    // 被误标为“读取失败”；其 status.code 在上方已为正常。
    const bytes = attrs['skill.read.file_bytes']
    const sha1 = attrs['skill.read.file_sha1']
    const preview = attrs['skill.read.preview'] || attrs['skill.result_preview']
    const artifactBytes = attrs['skill.read.artifact_bytes'] ?? attrs['tool.output.artifact_bytes']
    const artifactPath = attrs['skill.read.artifact_path'] || attrs['skill.path']
    if (
      (bytes == null || bytes === 0) &&
      !sha1 &&
      !String(preview || '').trim() &&
      !(artifactBytes > 0) &&
      !artifactPath
    ) {
      return { isFailed: true, failureLabel: 'read failed' }
    }
  }

  return { isFailed: false, failureLabel: '' }
}

function buildSpanTitle(name: any, _attrs: any): any {
  if (name === 'llm.call') return 'Model Call'
  if (name === 'tool.call') return 'Tool Call'
  if (name === 'subagent.call') return 'Subagent Dispatch'
  if (name === 'subagent.run') return 'Subagent Run'
  if (name === 'skills.cataloged') return 'Skills Cataloged'
  if (name === 'skills.catalog_read') return 'Skill Catalog Read'
  if (name === 'skill.read') return 'Skill'
  if (name === 'skills.scan') return 'Skills Scan'
  if (name === 'session.turn') return 'Turn'
  if (name === 'skill.inject') return 'Skill Inject'
  if (name === 'skill.rewrite') return 'Query Rewrite'
  if (name === 'skill.gate') return 'Skill Gate'
  if (name === 'context.curate') return 'Context Curation'
  if (name.startsWith('personalize.')) return 'Personalize ' + name.slice('personalize.'.length)
  if (name === 'memory.recall') return 'Memory Recall'
  if (name === 'memory.store') return 'Memory Store'
  if (name === 'memory.extract') return 'Memory Extract'
  if (name === 'memory.consolidate') return 'Memory Consolidate'
  if (name === 'memory.profile_refresh') return 'Profile Refresh'
  if (name === 'memory.feedback') return 'Memory Feedback'
  if (name === 'plugin.load') return 'Plugin Load'
  if (name === 'tracing.bootstrap') return 'Tracing Bootstrap'
  return name
}

function buildSpanSubtitle(name: any, attrs: any): any {
  if (name === 'session.turn') {
    const q = attrs['turn.input_preview']
    return q ? String(q).replace(/\s+/g, ' ').trim() : ''
  }
  if (name === 'llm.call') return [attrs['llm.provider'], attrs['llm.model']].filter(Boolean).join(' / ')
  if (name === 'tool.call') return attrs['tool.name'] || ''
  if (name === 'subagent.call') {
    if (attrs['subagent.id']) return `named subagent / ${attrs['subagent.id']}`
    return attrs['subagent.label'] || 'derived subagent'
  }
  if (name === 'subagent.run') return attrs['subagent.label'] || attrs['subagent.task'] || 'subagent'
  if (name === 'skills.cataloged') return `${attrs['skills.cataloged.count'] || 0} skills`
  if (name === 'skills.catalog_read') return attrs['skills.catalog_read.skill_name'] || ''
  if (name === 'skill.read') {
    const label = attrs['skill.name'] || attrs['skill.id'] || ''
    return attrs['skill.scripts_dir'] ? `${label} + scripts`.trim() : label
  }
  if (name === 'skills.scan') return `${attrs['skills.scan.total_count'] || 0} skills`
  if (name === 'skill.rewrite') {
    const nr = attrs['skill.rewrite.need_retrieval']
    return nr === false ? 'no retrieval' : attrs['skill.rewrite.query_preview'] || ''
  }
  if (name === 'skill.gate') {
    return `${attrs['skill.gate.selected_count'] ?? 0}/${attrs['skill.gate.candidate_count'] ?? 0} selected`
  }
  if (name === 'context.curate') return attrs['context.curate.produced'] ? 'curated' : ''
  if (name.startsWith('personalize.')) return attrs['personalize.ok'] === false ? 'failed' : ''
  if (name === 'skill.inject') {
    const names = attrs['skill.inject.names']
    const label = Array.isArray(names) && names.length ? names.join(', ') : `${attrs['skill.inject.count'] || 0} skills`
    return attrs['skill.inject.via'] ? `${label} (${attrs['skill.inject.via']})` : label
  }
  if (name === 'memory.recall') {
    return [attrs['memory.scope'], attrs['memory.hits'] != null ? `${attrs['memory.hits']} hits` : null]
      .filter(Boolean)
      .join(' / ')
  }
  if (name === 'memory.store') {
    const base = attrs['memory.message_count'] != null ? `${attrs['memory.message_count']} msgs` : ''
    return base
  }
  if (name === 'memory.extract') return attrs['memory.surface'] || ''
  if (name === 'memory.consolidate')
    return attrs['memory.message_count'] != null ? `${attrs['memory.message_count']} msgs` : ''
  if (name === 'memory.profile_refresh')
    return attrs['memory.sections_rewritten'] != null ? `${attrs['memory.sections_rewritten']} sections` : ''
  if (name === 'memory.feedback') return attrs['memory.kind'] || ''
  if (name === 'plugin.load') return [attrs['plugin.name'], attrs['plugin.contribution']].filter(Boolean).join(' / ')
  if (name === 'tracing.bootstrap') return attrs['plugin.id'] || ''
  return attrs['hook.name'] || ''
}

function buildTraceTree(spans: any): any {
  const spanIds = new Set((spans || []).map((span: any) => span.spanId))
  const byParent = new Map()
  for (const span of spans) {
    const effectiveParentId = span.displayParentSpanId ?? span.parentSpanId
    const parentKey = effectiveParentId && spanIds.has(effectiveParentId) ? effectiveParentId : '__root__'
    if (!byParent.has(parentKey)) byParent.set(parentKey, [])
    byParent.get(parentKey).push(span)
  }

  for (const [key, children] of byParent.entries()) {
    children.sort(compareSpansByTime)
    byParent.set(key, dedupeSiblingSpans(children))
  }

  function visit(node: any, depth: any): any {
    return {
      ...node,
      depth,
      children: (byParent.get(node.spanId) || []).map((child: any) => visit(child, depth + 1))
    }
  }

  return (byParent.get('__root__') || []).map((root: any) => visit(root, 0))
}

function dedupeSiblingSpans(spans: any): any {
  const seen = new Set()
  const result: any[] = []
  for (const span of spans) {
    const attrs = span.attributes || {}
    const key = [
      span.name,
      span.displayParentSpanId || span.parentSpanId || '',
      attrs['skills.cataloged.artifact_sha1'] || '',
      attrs['skills.catalog_read.path'] || attrs['skills.load.path'] || '',
      attrs['skill.path'] || '',
      attrs['tool.call_id'] || '',
      attrs['llm.input.artifact_sha1'] || '',
      attrs['llm.output.artifact_sha1'] || '',
      span.startTime || ''
    ].join('|')
    if (seen.has(key)) continue
    seen.add(key)
    result.push(span)
  }
  return result
}

function extractSessionsSpawnPayload(span: any, identityIndex: any): any {
  const attrs = span?.attributes || {}
  if (
    String(attrs['tool.name'] || '')
      .trim()
      .toLowerCase() !== 'sessions_spawn'
  )
    return null

  const inputArtifact = readJsonFileMaybe(attrs['tool.input.artifact_path'])
  const outputArtifact = readJsonFileMaybe(attrs['tool.output.artifact_path'])
  const persistedArtifact = readJsonFileMaybe(attrs['tool.persisted.artifact_path'])

  const input =
    inputArtifact?.params ||
    inputArtifact?.input ||
    inputArtifact?.payload ||
    parseJsonMaybe(attrs['tool.args_preview']) ||
    null

  const persistedText = persistedArtifact?.message?.details?.status
    ? persistedArtifact.message.details
    : persistedArtifact?.message?.content?.find?.((part: any) => typeof part?.text === 'string')?.text ||
      persistedArtifact?.result?.content?.find?.((part: any) => typeof part?.text === 'string')?.text ||
      null

  const output =
    parseJsonMaybe(persistedText) ||
    persistedArtifact?.message?.details ||
    outputArtifact?.result?.details ||
    outputArtifact?.result ||
    parseJsonMaybe(attrs['tool.result_preview']) ||
    null

  if (!input || !output) return null
  if (
    String(input.runtime || '')
      .trim()
      .toLowerCase() !== 'subagent'
  )
    return null
  if (
    String(output.status || '')
      .trim()
      .toLowerCase() !== 'accepted'
  )
    return null

  const childSessionKey = output.childSessionKey || null
  const childSessionId =
    output.childSessionId ||
    (childSessionKey ? identityIndex.canonicalIdBySessionKey.get(childSessionKey) || null : null)

  return {
    input,
    output,
    childSessionKey,
    childSessionId
  }
}

function synthesizeSubagentCallSpans(spans: any, identityIndex: any): any {
  const existingToolCallIds = new Set(
    spans
      .filter((span: any) => span.name === 'subagent.call')
      .map((span: any) => span.attributes?.['subagent.tool_call_id'])
      .filter(Boolean)
  )
  const derived: any[] = []

  for (const span of spans) {
    if (span.name !== 'tool.call') continue
    const attrs = span.attributes || {}
    const toolCallId = attrs['tool.call_id'] || null
    if (toolCallId && existingToolCallIds.has(toolCallId)) continue
    const payload = extractSessionsSpawnPayload(span, identityIndex)
    if (!payload) continue
    const { input, output, childSessionKey, childSessionId } = payload
    derived.push({
      ...span,
      spanId: `${span.spanId}::subagent`,
      name: 'subagent.call',
      kind: 'subagent',
      startTime: span.startTime,
      endTime: span.endTime,
      durationMs: span.durationMs,
      displayTitle: 'Subagent Dispatch',
      displaySubtitle: input.agentId || input.label || '',
      parentSpanId: span.spanId,
      displayParentSpanId: span.spanId,
      attributes: {
        ...attrs,
        'subagent.id': input.agentId || null,
        'subagent.task': input.task || input.label || '',
        'subagent.label': input.label || '',
        'subagent.mode': input.mode || output.mode || null,
        'subagent.session_key': childSessionKey,
        'subagent.session_id': childSessionId,
        'subagent.run_id': output.runId || null,
        'subagent.status': 'accepted',
        'subagent.source': 'sessions_spawn',
        'subagent.tool_call_id': toolCallId
      },
      events: [...(span.events || []), { time: span.endTime || span.startTime, name: 'subagent_spawn_accepted' }]
    })
  }

  return [...spans, ...derived]
}

function chooseTraceRoot(groups: any, traceId: any, timestamp: any): any {
  const candidates = (groups || [])
    .filter((group: any) => group.root && (!traceId || group.traceId === traceId))
    .sort((a: any, b: any) => compareSpansByTime(a.root, b.root))
  if (!candidates.length) return null
  const targetTime = parseTime(timestamp)
  const before = candidates.filter((group: any) => parseTime(group.root.startTime) <= targetTime)
  return before[before.length - 1] || candidates[0]
}

function buildTraceGroups(sessionSpans: any): any {
  const spans = [...(sessionSpans || [])].sort(compareSpansByTime)
  const spanById = new Map(spans.map((span: any) => [span.spanId, span]))
  const childrenByParent = new Map()

  for (const span of spans) {
    if (!span.parentSpanId || !spanById.has(span.parentSpanId)) continue
    if (!childrenByParent.has(span.parentSpanId)) childrenByParent.set(span.parentSpanId, [])
    childrenByParent.get(span.parentSpanId).push(span)
  }

  for (const children of childrenByParent.values()) {
    children.sort(compareSpansByTime)
  }

  // session.turn 是主追踪根；subagent.run 是子智能体自身追踪的根。Pico 子智能体作为独立追踪
  // 运行，并通过分发节点的 subagent.trace_id 关联。两者都是一等追踪根。
  let rootCandidates = spans.filter(
    (span: any) =>
      (span.name === 'session.turn' || span.name === 'subagent.run') &&
      (!span.parentSpanId || !spanById.has(span.parentSpanId))
  )
  if (!rootCandidates.length) {
    rootCandidates = spans.filter((span: any) => !span.parentSpanId || !spanById.has(span.parentSpanId))
  }

  const groups = rootCandidates.sort(compareSpansByTime).map((root: any) => ({
    id: root.spanId,
    root,
    traceId: root.traceId,
    spans: [] as any[],
    events: [] as any[]
  }))

  const assignedGroupIdBySpanId = new Map()
  const assignDescendants = (group: any, span: any) => {
    if (!span || assignedGroupIdBySpanId.has(span.spanId)) return
    assignedGroupIdBySpanId.set(span.spanId, group.id)
    group.spans.push({ ...span })
    for (const child of childrenByParent.get(span.spanId) || []) {
      assignDescendants(group, child)
    }
  }

  for (const group of groups) {
    assignDescendants(group, group.root)
  }

  const keptGroups: any[] = []
  for (const group of groups) {
    const hasMeaningfulDescendant = group.spans.some(
      (span: any) => span.spanId !== group.root.spanId && span.name !== 'session.turn'
    )
    const richerSiblingExists = groups.some(
      (candidate: any) =>
        candidate !== group &&
        candidate.traceId === group.traceId &&
        candidate.root.sessionKey === group.root.sessionKey &&
        candidate.root.agentId === group.root.agentId &&
        candidate.spans.length > group.spans.length
    )
    if (!hasMeaningfulDescendant && richerSiblingExists) {
      for (const span of group.spans) {
        assignedGroupIdBySpanId.delete(span.spanId)
      }
      continue
    }
    keptGroups.push(group)
  }

  const syntheticGroups: any[] = []
  const unassignedSpans = spans.filter((span: any) => !assignedGroupIdBySpanId.has(span.spanId))
  for (const span of unassignedSpans) {
    if (
      span.name === 'session.turn' &&
      keptGroups.some(
        (group: any) =>
          group.root &&
          group.traceId === span.traceId &&
          group.root.sessionId === span.sessionId &&
          group.root.sessionKey === span.sessionKey
      )
    ) {
      continue
    }
    let group = chooseTraceRoot(keptGroups, span.traceId, span.startTime)
    if (!group) {
      group = {
        id: `synthetic::${span.spanId}`,
        root: null,
        traceId: span.traceId,
        spans: [] as any[],
        events: [] as any[]
      }
      syntheticGroups.push(group)
      keptGroups.push(group)
    }
    assignedGroupIdBySpanId.set(span.spanId, group.id)
    group.spans.push({
      ...span,
      displayParentSpanId: group.root ? group.root.spanId : null
    })
  }

  return keptGroups.map((group: any) => {
    const spanIds = new Set(group.spans.map((span: any) => span.spanId))
    const normalizedSpans = group.spans
      .map((span: any) => {
        const effectiveParent = span.displayParentSpanId ?? span.parentSpanId
        const displayParentSpanId =
          effectiveParent && spanIds.has(effectiveParent)
            ? effectiveParent
            : group.root && span.spanId !== group.root.spanId
              ? group.root.spanId
              : null
        return {
          ...span,
          displayParentSpanId
        }
      })
      .sort(compareSpansByTime)

    return {
      id: group.id,
      root: group.root,
      traceId: group.traceId,
      startTime: normalizedSpans[0]?.startTime || group.root?.startTime || null,
      endTime:
        normalizedSpans.map((span: any) => span.endTime).sort((a: any, b: any) => parseTime(b) - parseTime(a))[0] ||
        group.root?.endTime ||
        null,
      spans: normalizedSpans,
      events: [] as any[]
    }
  })
}

export function buildSessions(): TraceData {
  const spanWindow = readJsonlWindow('spans')
  const eventWindow = readJsonlWindow('events')
  const rawSpans = dedupeSpans(spanWindow.records).map(normalizeSpan)
  const identityIndex = buildSessionIdentityIndex(rawSpans)
  const projectedSpans = rawSpans.map((span: any) => projectSpanForDisplay(span, identityIndex)).filter(Boolean)
  const spans = synthesizeSubagentCallSpans(projectedSpans, identityIndex)
  // Historical framework events have extensible fields; normalize at this boundary.
  const events: any[] = eventWindow.records
  const spansBySessionId = new Map()
  for (const span of spans) {
    if (!span.sessionId) continue
    if (!spansBySessionId.has(span.sessionId)) spansBySessionId.set(span.sessionId, [])
    spansBySessionId.get(span.sessionId).push(span)
  }

  const sessions: any[] = []
  for (const [sessionId, sessionSpans] of spansBySessionId.entries()) {
    const traceGroups = buildTraceGroups(sessionSpans)
    const sessionKey = pickMostFrequent(sessionSpans.map((span: any) => span.sessionKey))
    const agentId = pickMostFrequent(sessionSpans.map((span: any) => span.agentId))
    const workspaceDir = pickMostFrequent(sessionSpans.map((span: any) => span.workspaceDir))
    const trigger = pickMostFrequent(sessionSpans.map((span: any) => span.trigger))
    const channelId = pickMostFrequent(sessionSpans.map((span: any) => span.channelId))
    const sessionEvents = events.filter((event: any) => {
      if (event.sessionId && event.sessionId === sessionId) return true
      if (sessionKey && event.sessionKey === sessionKey) return true
      return false
    })
    const sessionStartEvent = sessionEvents.find(
      (event: any) => event.type === 'session_start' && event.sessionId === sessionId
    )
    const resumedFrom = sessionStartEvent?.event?.resumedFrom || null

    for (const event of sessionEvents.sort((a: any, b: any) => parseTime(a.timestamp) - parseTime(b.timestamp))) {
      const group = chooseTraceRoot(traceGroups, event.traceId, event.timestamp)
      if (group) group.events.push(event)
    }

    const hiddenSpanNames = new Set(['skills.scan', 'skills.catalog_read', 'skills.cataloged'])
    const traces = traceGroups
      .map((trace: any) => {
        const traceKey = `${sessionId}::${trace.root?.spanId || trace.id}`
        const normalizedSpans = trace.spans.map((span: any) => ({ ...span, traceKey }))
        const meaningfulVisibleSpans = normalizedSpans.filter(
          (span: any) => !hiddenSpanNames.has(span.name) && span.name !== 'session.turn'
        )
        return {
          traceKey,
          traceId: trace.traceId,
          sessionId,
          sessionKey,
          agentId,
          workspaceDir,
          trigger,
          channelId,
          startTime: trace.startTime,
          endTime: trace.endTime,
          durationMs: durationMs(trace.startTime, trace.endTime),
          spanCount: normalizedSpans.length,
          visibleSpanCount: meaningfulVisibleSpans.length,
          spans: normalizedSpans,
          tree: buildTraceTree(normalizedSpans),
          events: trace.events.sort((a: any, b: any) => parseTime(a.timestamp) - parseTime(b.timestamp))
        }
      })
      .filter((trace: any) => trace.visibleSpanCount > 0)
      .sort((a: any, b: any) => parseTime(b.startTime) - parseTime(a.startTime))

    sessions.push({
      sessionId,
      sessionKey,
      agentId,
      workspaceDir,
      trigger,
      channelId,
      resumedFrom,
      resumedTo: null,
      startedAt:
        sessionSpans.map((span: any) => span.startTime).sort((a: any, b: any) => parseTime(a) - parseTime(b))[0] ||
        null,
      updatedAt:
        sessionSpans.map((span: any) => span.endTime).sort((a: any, b: any) => parseTime(b) - parseTime(a))[0] || null,
      traceCount: traces.length,
      traces
    })
  }

  const sessionById = new Map(sessions.map((session: any) => [session.sessionId, session]))
  for (const session of sessions) {
    if (!session.resumedFrom) continue
    const parent = sessionById.get(session.resumedFrom)
    if (parent) parent.resumedTo = session.sessionId
  }

  sessions.sort((a: any, b: any) => parseTime(b.updatedAt) - parseTime(a.updatedAt))

  return {
    generatedAt: new Date().toISOString(),
    sessions,
    window: {
      truncated: spanWindow.window.truncated || eventWindow.window.truncated,
      spans: { ...spanWindow.window, records: spanWindow.records.length },
      events: { ...eventWindow.window, records: eventWindow.records.length }
    }
  }
}
