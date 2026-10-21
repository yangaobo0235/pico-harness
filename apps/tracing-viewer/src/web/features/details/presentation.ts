import { createTraceModel } from '../traces/model'
import type { Presentation } from './types'
import { I18N } from '../../shared/i18n'
import type { ViewerState } from '../../app/state'
const jsonEntries = (value: object): [string, any][] => Object.entries(value)

/** Pure formatters retained for descriptor compatibility. No DOM, requests or mutable global state.
 * Dynamic JSON parameters preserve third-party attributes and artifact payloads. */
export function createPresentation(state: ViewerState): Presentation {
  const {
    allSessions,
    filteredSessions,
    allApiCalls,
    filteredApiCalls,
    currentSession,
    currentTrace,
    currentSpan,
    findSessionByIdentity,
    sortedTraces,
    preferredSpan,
    usageFromSpan,
    usageReported,
    aggregateApiOverview,
    groupApiByProviderModel,
    visibleTraceTree
  } = createTraceModel(state)
  function t(key: any, params?: any): any {
    const table = I18N[state.lang] || I18N.en
    const value = key in table ? table[key] : I18N.en[key]
    if (value == null) return key
    return typeof value === 'function' ? value(params || {}) : value
  }

  function escapeHtml(text: any): any {
    return String(text)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;')
  }

  function timeLocale(): any {
    return state.lang === 'zh' ? 'zh-CN' : 'en-US'
  }

  function formatTime(value: any): any {
    if (!value) return '-'
    return new Intl.DateTimeFormat(timeLocale(), {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    }).format(new Date(value))
  }

  function formatTimeOnly(value: any): any {
    if (!value) return '--:--:--'
    return new Intl.DateTimeFormat(timeLocale(), {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    }).format(new Date(value))
  }

  function formatDuration(ms: any): any {
    if (ms == null) return '-'
    if (ms < 1000) return `${ms}ms`
    if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`
    const mins = Math.floor(ms / 60000)
    const secs = Math.round((ms % 60000) / 1000)
    return `${mins}m ${secs}s`
  }

  function formatBytes(bytes: any): any {
    const value = Number(bytes || 0)
    if (value < 1024) return `${value} B`
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
    return `${(value / (1024 * 1024)).toFixed(1)} MB`
  }

  function shortId(value: any, len: any = 12): any {
    if (!value) return '-'
    const text = String(value)
    return text.length <= len ? text : `${text.slice(0, len)}...`
  }

  function detailKey(span: any, key: any): any {
    return `${span?.spanId || 'span'}::${key}`
  }

  function sessionChainLabel(session: any): any {
    if (!session) return ''
    if (session.resumedFrom) return t('session.resumedFrom', { id: shortId(session.resumedFrom, 12) })
    if (session.resumedTo) return t('session.resumedTo', { id: shortId(session.resumedTo, 12) })
    return ''
  }

  function traceRoundLabel(session: any, index: any): any {
    if (!session) return t('round.nth', { n: index + 1 })
    const total = sortedTraces(session).length
    if (index === 0) return t('round.latest')
    return t('round.nth', { n: total - index })
  }

  function promptSkills(span: any): any {
    return span?.attributes?.['skills.prompt.names'] || []
  }

  function usageChipsFromUsage(usage: any): any {
    if (!usageReported(usage)) return [{ text: t('usage.unreported'), soft: true }]
    const chips: any[] = []
    if (usage.input != null) chips.push({ text: `${usage.input} ${t('usage.input')}` })
    if (usage.output != null) chips.push({ text: `${usage.output} ${t('usage.output')}` })
    if (usage.total != null) chips.push({ text: `${usage.total} ${t('usage.total')}` })
    if (usage.cacheRead != null) chips.push({ text: `${usage.cacheRead} ${t('usage.cacheHit')}` })
    if (usage.cacheWrite != null) chips.push({ text: `${usage.cacheWrite} ${t('usage.cacheWrite')}` })
    if (usage.costTotal != null) chips.push({ text: `${t('usage.cost')} ${usage.costTotal}` })
    return chips
  }

  function aggregateTraceUsage(trace: any): any {
    const llmSpans = (trace?.spans || []).filter((span: any) => span.name === 'llm.call')
    const aggregate: any = {
      input: 0,
      output: 0,
      total: 0,
      cacheRead: 0,
      cacheWrite: 0,
      costTotal: 0,
      reportedCalls: 0,
      unreportedCalls: 0
    }

    for (const span of llmSpans) {
      const usage = usageFromSpan(span)
      if (!usageReported(usage)) {
        aggregate.unreportedCalls += 1
        continue
      }
      aggregate.reportedCalls += 1
      if (usage.input != null) aggregate.input += usage.input
      if (usage.output != null) aggregate.output += usage.output
      if (usage.total != null) aggregate.total += usage.total
      if (usage.cacheRead != null) aggregate.cacheRead += usage.cacheRead
      if (usage.cacheWrite != null) aggregate.cacheWrite += usage.cacheWrite
      if (usage.costTotal != null) aggregate.costTotal += usage.costTotal
    }

    return aggregate
  }

  function traceReadSkills(trace: any): any {
    return [
      ...new Set(
        (trace?.spans || [])
          .filter((span: any) => span.name === 'skill.read')
          .map((span: any) => span.attributes?.['skill.name'])
          .filter(Boolean)
      )
    ]
  }

  function sortedTraceSpans(trace: any): any {
    return [...(trace?.spans || [])].sort(
      (a: any, b: any) => new Date(a.startTime).getTime() - new Date(b.startTime).getTime()
    )
  }

  function buildSkillEvidence(trace: any): any {
    const spans = sortedTraceSpans(trace)
    const visibleNames = new Set(['llm.call', 'tool.call', 'subagent.call'])
    const promptedSet = new Set(tracePromptSkills(trace))
    return spans
      .filter((span: any) => span.name === 'skill.read')
      .map((readSpan: any) => {
        const readTime = new Date(readSpan.endTime || readSpan.startTime).getTime()
        const readCallId = readSpan.attributes?.['skill.read.tool_call_id']
        const followUps = spans
          .filter((candidate: any) => {
            if (candidate.spanId === readSpan.spanId) return false
            if (!visibleNames.has(candidate.name)) return false
            if (candidate.name === 'tool.call') {
              const sameReadTool =
                String(candidate.attributes?.['tool.name'] || '').toLowerCase() === 'read' &&
                candidate.attributes?.['tool.call_id'] === readCallId
              if (sameReadTool) return false
            }
            return new Date(candidate.startTime).getTime() > readTime
          })
          .slice(0, 5)
        return {
          skillName: readSpan.attributes?.['skill.name'] || '-',
          source: readSpan.attributes?.['skill.source'] || '-',
          path: readSpan.attributes?.['skill.path'] || '',
          prompted: promptedSet.has(readSpan.attributes?.['skill.name']),
          readSpan,
          followUps,
          status: followUps.length ? 'follow-up seen' : 'read only'
        }
      })
  }

  function tracePromptSkills(trace: any): any {
    return [
      ...new Set(
        (trace?.spans || [])
          .filter((span: any) => span.name === 'llm.call')
          .flatMap((span: any) => promptSkills(span))
          .filter(Boolean)
      )
    ]
  }

  function traceSummary(trace: any): any {
    const spans = trace?.spans || []
    return {
      modelCalls: spans.filter((span: any) => span.name === 'llm.call').length,
      toolCalls: spans.filter((span: any) => span.name === 'tool.call').length,
      subagents: spans.filter((span: any) => span.name === 'subagent.call').length,
      readSkills: traceReadSkills(trace),
      promptSkills: tracePromptSkills(trace),
      usage: aggregateTraceUsage(trace)
    }
  }

  function collectArtifacts(span: any): any {
    const attrs = span?.attributes || {}
    const entries: any[] = []
    const push = (label: any, filePath: any) => {
      if (!filePath) return
      entries.push({ label, path: filePath })
    }
    push('Model Input', attrs['llm.input.artifact_path'])
    push('Model Output', attrs['llm.output.artifact_path'])
    push('Tool Input', attrs['tool.input.artifact_path'])
    push('Tool Output', attrs['tool.output.artifact_path'])
    push('Tool Persisted', attrs['tool.persisted.artifact_path'])
    push('Skill Read', attrs['skill.read.artifact_path'])
    push('Skill Injected', attrs['skill.inject.artifact_path'])
    push('Memory Recall', attrs['memory.recall.artifact_path'])
    push('Memory Store', attrs['memory.store.artifact_path'])
    push('Subagent Result', attrs['subagent.result.artifact_path'])
    if (span?.name === 'skill.read' && span?.parentSpanId) {
      const parentTool = currentTrace()?.spans?.find((candidate: any) => candidate.spanId === span.parentSpanId) || null
      const parentAttrs = parentTool?.attributes || {}
      push('Read Request', parentAttrs['tool.input.artifact_path'])
      push('Read Content', parentAttrs['tool.output.artifact_path'])
    }
    return entries
  }

  function artifactByLabel(artifacts: any, label: any): any {
    return artifacts.find((entry: any) => entry.label === label)?.artifact || null
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

  function prettyValue(value: any, fallback: any = '(empty)'): any {
    if (value == null || value === '') return fallback
    if (typeof value === 'string') return value
    try {
      return JSON.stringify(value, null, 2)
    } catch {
      return String(value)
    }
  }

  function renderModelInputCard(span: any, artifacts: any): any {
    if (span.name !== 'llm.call') return ''
    const inp = artifactByLabel(artifacts, 'Model Input')?.parsed
    if (!inp) return ''
    // 展示实际发送给模型的请求：工具加原始消息列表，inp.messages 是权威值，而非拆分后的系统/
    // 历史。模型、提供商和令牌用量已在顶部主信息块中展示，不再重复。
    const messages = Array.isArray(inp.messages) ? inp.messages : []
    const tools = Array.isArray(inp.tools) ? inp.tools : []
    const note = `${messages.length} Messages${tools.length ? ` · ${tools.length} Tools` : ''}`
    const toolsBlock = tools.length
      ? `
      <details class="model-diagnostic-details" data-detail-key="${escapeHtml(detailKey(span, 'req-tools'))}">
        <summary class="model-panel-head"><strong>Tools</strong> <span class="summary-chip">${tools.length}</span></summary>
        <pre class="structured-pre">${escapeHtml(
          tools
            .map((t: any) => {
              const fn = (t && t.function) || t || {}
              return `- ${fn.name || '?'}${fn.description ? `: ${fn.description}` : ''}`
            })
            .join('\n')
        )}</pre>
      </details>`
      : ''
    return `
    <article class="content-card wide-card">
      <header><h4>Model Input</h4><span class="card-note">${escapeHtml(note)}</span></header>
      ${toolsBlock}
      ${renderMessages(messages)}
    </article>`
  }

  function assistantContentText(message: any): any {
    if (!message) return ''
    if (typeof message === 'string') return message
    const content = Array.isArray(message.content) ? message.content : []
    return content
      .map((part: any) => {
        if (!part || typeof part !== 'object') return ''
        if (part.type === 'text') return part.text || ''
        if (part.type === 'toolCall') {
          return `[toolCall] ${part.name || 'unknown'}`
        }
        return ''
      })
      .filter(Boolean)
      .join('\n')
      .trim()
  }

  function llmUsageSummary(span: any): any {
    return usageChipsFromUsage(usageFromSpan(span))
  }

  function renderModelOutputCard(span: any, artifacts: any): any {
    if (span.name !== 'llm.call') return ''
    const llmOutput = artifactByLabel(artifacts, 'Model Output')?.parsed
    if (!llmOutput) return ''

    // OpenClaw 方言使用 assistantTexts / lastAssistant；Pico 方言使用 output/content 加顶层
    // tool_calls 数组。工具调用轮次的文本常为空，全部内容在 tool_calls 中，因此必须同时渲染，
    // 否则卡片会收缩成“无助手输出”并彻底丢掉参数。
    const assistantTexts = Array.isArray(llmOutput.assistantTexts) ? llmOutput.assistantTexts : []
    const finalMessage =
      assistantContentText(llmOutput.lastAssistant) ||
      llmOutput.output ||
      llmOutput.content ||
      assistantTexts[assistantTexts.length - 1] ||
      ''

    // 将 Pico 的扁平 {id,name,arguments} 规范化为 messageBodyText 渲染的
    // {function:{name,arguments}} 结构，同时兼容已嵌套的 OpenAI 结构。
    const toolCalls = (Array.isArray(llmOutput.tool_calls) ? llmOutput.tool_calls : []).map((tc: any) => ({
      function: {
        name: (tc && (tc.name ?? tc.function?.name)) || '?',
        arguments: (tc && (tc.arguments ?? tc.function?.arguments)) ?? {}
      }
    }))

    const steps = assistantTexts.length ? assistantTexts : finalMessage ? [finalMessage] : []
    let body
    if (steps.length || toolCalls.length) {
      const msgs = steps.map((t: any) => ({ role: 'assistant', content: t }))
      if (toolCalls.length) {
        if (msgs.length) msgs[msgs.length - 1].tool_calls = toolCalls
        else msgs.push({ role: 'assistant', content: '', tool_calls: toolCalls })
      }
      body = renderMessages(msgs)
    } else {
      body = preBody('(no assistant output)')
    }

    const reasoning = typeof llmOutput.reasoning_content === 'string' ? llmOutput.reasoning_content : ''
    const reasoningBlock = reasoning
      ? `<details class="model-diagnostic-details"><summary class="model-panel-head"><strong>Reasoning</strong></summary><pre class="structured-pre">${escapeHtml(reasoning)}</pre></details>`
      : ''

    const finish = llmOutput.finish_reason || span.attributes?.['llm.finish_reason'] || ''
    const note = [
      steps.length > 1 ? `${steps.length} steps` : '',
      toolCalls.length ? `${toolCalls.length} tool call${toolCalls.length > 1 ? 's' : ''}` : '',
      finish
    ]
      .filter(Boolean)
      .join(' · ')
    // 推理在时间上先于答案（模型先思考再响应），因此折叠后渲染在正文上方；其内容较长且用于诊断。
    return `
    <article class="content-card wide-card">
      <header><h4>Model Output</h4>${note ? `<span class="card-note">${escapeHtml(note)}</span>` : ''}</header>
      ${reasoningBlock}
      ${body}
    </article>`
  }

  function latestChildOutput(session: any): any {
    if (!session) return null
    const traces = sortedTraces(session)
    for (const trace of traces) {
      const llmSpans = [...(trace.spans || [])]
        .filter((item: any) => item.name === 'llm.call')
        .sort(
          (a: any, b: any) =>
            new Date(b.endTime || b.startTime).getTime() - new Date(a.endTime || a.startTime).getTime()
        )
      const latest = llmSpans[0]
      if (!latest) continue
      const preview = latest.attributes?.['llm.output_preview'] || ''
      if (preview) {
        return {
          text: preview,
          time: latest.endTime || latest.startTime || null,
          source: 'child_session'
        }
      }
    }
    return null
  }

  function renderSubagentCallCard(span: any, artifacts: any): any {
    if (span.name !== 'subagent.call') return ''
    const attrs = span.attributes || {}
    const toolOutput = artifactByLabel(artifacts, 'Tool Output')?.parsed
    const task = attrs['subagent.task'] || attrs['subagent.label'] || ''
    const dispatchInput = task || ''
    const dispatchOutput = toolOutput?.result ?? toolOutput?.output ?? null
    // Pico 把子智能体最终返回持久化在跨度本身：`Subagent Result` 产物（{task, result}）加
    // `subagent.result_preview` 属性，而不是像下方 OpenClaw 模型那样存为独立子会话。若不处理，
    // 卡片只检查子会话/spawn 工具路径，在 Pico 中找不到内容并回退到空结果占位，尽管结果就在跨度上。
    const subagentResult = artifactByLabel(artifacts, 'Subagent Result')?.parsed
    const resultText = subagentResult?.result ?? attrs['subagent.result_preview'] ?? null
    const childSession = findSessionByIdentity(
      attrs['subagent.session_id'] || null,
      attrs['subagent.session_key'] || null
    )
    const childOutcome = latestChildOutput(childSession)
    const outputText = childOutcome?.text || resultText || null

    // 前向链接：Pico 将子智能体作为独立追踪运行，当前分发节点仅作摘要；提供跳转到完整追踪树的入口。
    const subTraceId = attrs['subagent.trace_id'] || null
    const jumpCard = subTraceId
      ? `
    <article class="content-card wide-card">
      <button type="button" class="jump-link" data-jump-trace-id="${escapeHtml(subTraceId)}">
        → ${t('subagent.openFullTrace')}
      </button>
    </article>`
      : ''

    return `
    ${jumpCard}
    <article class="content-card wide-card">
      <header>
        <h4>Subagent Input</h4>
      </header>
      <pre class="structured-pre">${escapeHtml(prettyValue(dispatchInput))}</pre>
    </article>
    <article class="content-card wide-card">
      <header>
        <h4>Subagent Output</h4>
      </header>
      <pre class="structured-pre">${escapeHtml(prettyValue(outputText ?? dispatchOutput, outputText || dispatchOutput ? '(empty)' : t('subagent.noResult')))}</pre>
    </article>
  `
  }

  function renderSubagentRunCard(span: any): any {
    if (span.name !== 'subagent.run') return ''
    const attrs = span.attributes || {}
    const parentTraceId = attrs['subagent.parent_trace_id'] || null
    const parentSpanId = attrs['subagent.parent_span_id'] || null
    const task = attrs['subagent.task'] || attrs['subagent.label'] || ''
    // 返回链接：当前追踪是一次子智能体运行，返回启动它的轮次。
    const backCard = parentTraceId
      ? `
    <article class="content-card wide-card">
      <button type="button" class="jump-link" data-jump-trace-id="${escapeHtml(parentTraceId)}"${parentSpanId ? ` data-jump-span-id="${escapeHtml(parentSpanId)}"` : ''}>
        ← ${t('subagent.backToMain')}
      </button>
    </article>`
      : ''
    return `
    ${backCard}
    <article class="content-card wide-card">
      <header>
        <h4>Subagent Task</h4>
      </header>
      <pre class="structured-pre">${escapeHtml(prettyValue(task))}</pre>
    </article>
  `
  }

  function renderMetadata(span: any): any {
    if (span.name === 'session.turn') {
      const trace = currentTrace()
      const summary = traceSummary(trace)
      const attrs = span.attributes || {}
      const traceStart = trace?.startTime || span.startTime
      const traceEnd = trace?.endTime || span.endTime
      const traceDuration = trace?.durationMs ?? span.durationMs
      const rows = [
        ['Span ID', span.spanId],
        ['Trace ID', span.traceId],
        ['Span Type', span.kind],
        ['Status', span.isFailed ? span.failureLabel || span.status?.code || 'FAILED' : span.status?.code || 'OK'],
        ['Failed', span.isFailed ? 'yes' : 'no'],
        ['Duration', formatDuration(traceDuration)],
        ['Started', formatTime(traceStart)],
        ['Ended', formatTime(traceEnd)],
        ['Agent', span.agentId],
        ['Session ID', span.sessionId],
        ['Session Key', span.sessionKey],
        ['Run ID', span.runId],
        ['Trigger', triggerLabel(span.trigger || attrs['trigger'])],
        ['Model Calls', summary.modelCalls],
        ['Tool Calls', summary.toolCalls],
        ['Subagent Calls', summary.subagents],
        ['Skill Reads', summary.readSkills.length]
      ].filter(([, value]: any) => value || value === 0)

      const events = (span.events || [])
        .map(
          (event: any) => `<li><span>${formatTime(event.time)}</span><strong>${escapeHtml(event.name)}</strong></li>`
        )
        .join('')

      return `
      <div class="detail-grid">
        <section class="detail-panel">
          <div class="detail-panel-head">
            <h3>${t('section.metadata')}</h3>
            <span class="meta-tag">${escapeHtml(span.kind)}</span>
          </div>
          <dl class="metadata-grid">
            ${rows
              .map(
                ([label, value]: any) => `
                  <div class="meta-row">
                    <dt>${escapeHtml(label)}</dt>
                    <dd>${escapeHtml(String(value))}</dd>
                  </div>
                `
              )
              .join('')}
          </dl>
        </section>
        <section class="detail-panel">
          <div class="detail-panel-head">
            <h3>Span Events</h3>
            <span class="meta-tag">${span.events?.length || 0} events</span>
          </div>
          <div class="events-list">
            ${events ? `<ul>${events}</ul>` : `<div class="trace-tree-note">${t('span.noEvents')}</div>`}
          </div>
        </section>
      </div>
    `
    }
    const attrs = span.attributes || {}
    const rows = [
      ['Span ID', span.spanId],
      ['Trace ID', span.traceId],
      ['Parent Span', span.parentSpanId],
      ['Span Type', span.kind],
      ['Status', span.isFailed ? span.failureLabel || span.status?.code || 'FAILED' : span.status?.code || 'OK'],
      ['Failed', span.isFailed ? 'yes' : 'no'],
      ['Duration', formatDuration(span.durationMs)],
      ['Started', formatTime(span.startTime)],
      ['Ended', formatTime(span.endTime)],
      ['Session ID', span.sessionId],
      ['Session Key', span.sessionKey],
      ['Run ID', span.runId],
      ['Agent', span.agentId],
      ['Workspace', span.workspaceDir],
      ['Trigger', span.trigger],
      ['Provider', attrs['llm.provider']],
      ['Provider Class', attrs['llm.provider_class']],
      ['Model', attrs['llm.model']],
      ['Tool', attrs['tool.name']],
      ['Tool Call ID', attrs['tool.call_id']],
      [
        'Subagent Kind',
        attrs['subagent.id'] ? 'named subagent' : span.name === 'subagent.call' ? 'derived subagent' : null
      ],
      ['Subagent ID', attrs['subagent.id']],
      ['Subagent Label', attrs['subagent.label']],
      ['Subagent Session Key', attrs['subagent.session_key']],
      ['Subagent Run ID', attrs['subagent.run_id']],
      ['Subagent Status', attrs['subagent.status']],
      ['Skills In This Prompt', attrs['skills.prompt.count']],
      ['Read Skill', attrs['skill.name']],
      ['Read Skill Source', attrs['skill.source']],
      ['Read Skill Path', attrs['skill.path']]
    ].filter(([, value]: any) => value || value === 0)

    const events = (span.events || [])
      .map((event: any) => `<li><span>${formatTime(event.time)}</span><strong>${escapeHtml(event.name)}</strong></li>`)
      .join('')

    return `
    <div class="detail-grid">
      <section class="detail-panel">
        <div class="detail-panel-head">
          <h3>${t('section.metadata')}</h3>
          <span class="meta-tag">${escapeHtml(span.kind)}</span>
        </div>
        <dl class="metadata-grid">
          ${rows
            .map(
              ([label, value]: any) => `
                <div class="meta-row">
                  <dt>${escapeHtml(label)}</dt>
                  <dd>${escapeHtml(String(value))}</dd>
                </div>
              `
            )
            .join('')}
        </dl>
      </section>
      <section class="detail-panel">
        <div class="detail-panel-head">
          <h3>Span Events</h3>
          <span class="meta-tag">${span.events?.length || 0} events</span>
        </div>
        <div class="events-list">
          ${events ? `<ul>${events}</ul>` : `<div class="trace-tree-note">${t('span.noEvents')}</div>`}
        </div>
      </section>
    </div>
  `
  }

  function prettyArtifactContent(artifact: any): any {
    if (!artifact) return ''
    if (artifact.parsed) return JSON.stringify(artifact.parsed, null, 2)
    return artifact.content || ''
  }

  function renderSkillReadCard(trace: any, span: any, artifacts: any): any {
    if (span.name !== 'skill.read') return ''
    const evidence = buildSkillEvidence(trace).find((item: any) => item.readSpan.spanId === span.spanId)
    if (!evidence) return ''
    const attrs = span.attributes || {}
    const skillReadArtifact = artifactByLabel(artifacts, 'Skill Read')
    const readContent = artifactByLabel(artifacts, 'Read Content')
    const readRequest = artifactByLabel(artifacts, 'Read Request')
    // Pico 的 read_file→skill.read 把内容/参数放在重新标型工具跨度自身的 Tool Input/Output
    // 产物和 skill.result_preview 中，而非 OpenClaw 的 Skill Read / Read Content / Read Request
    // 产物。需回退到 Pico 数据，避免卡片为空。
    const toolInput = artifactByLabel(artifacts, 'Tool Input')
    const toolOutput = artifactByLabel(artifacts, 'Tool Output')
    const readInputValue: any = {
      skill: attrs['skill.name'] || evidence.skillName || '-',
      path: attrs['skill.path'] || evidence.path || '-',
      resolvedPath: attrs['skill.resolved_path'] || skillReadArtifact?.parsed?.resolvedFilePath || '-',
      source: attrs['skill.source'] || evidence.source || '-',
      // 按内容区分：存在已实体化脚本包表示智能体拉取了可运行文件；不存在表示只加载了指令正文。
      scriptsDir: attrs['skill.scripts_dir'] || '(instructions only)',
      request: readRequest?.parsed?.params ?? toolInput?.parsed?.params ?? null
    }
    const readContentValue =
      readContent?.parsed?.result ??
      readContent?.parsed?.output ??
      readContent?.content ??
      skillReadArtifact?.parsed?.fileInfo?.preview ??
      toolOutput?.parsed?.result ??
      attrs['skill.result_preview'] ??
      ''
    return `
    <article class="content-card wide-card">
      <header>
        <h4>Skill Input</h4>
      </header>
      <pre class="structured-pre">${escapeHtml(prettyValue(readInputValue))}</pre>
    </article>
    <article class="content-card wide-card">
      <header>
        <h4>Skill Output</h4>
      </header>
      <pre class="structured-pre">${escapeHtml(prettyValue(readContentValue, t('read.noContent')))}</pre>
      ${
        evidence.followUps.length
          ? `
            <details class="model-diagnostic-details" data-detail-key="${escapeHtml(detailKey(span, 'follow-up'))}">
              <summary class="model-panel-head"><strong>Follow-up</strong> <span class="summary-chip">${evidence.followUps.length} spans</span></summary>
              <pre class="structured-pre">${escapeHtml(
                evidence.followUps
                  .map(
                    (follow: any) =>
                      `${formatTime(follow.startTime)}  ${follow.displayTitle}${
                        follow.displaySubtitle ? `  ·  ${follow.displaySubtitle}` : ''
                      }`
                  )
                  .join('\n')
              )}</pre>
            </details>
          `
          : ''
      }
    </article>
  `
  }

  function triggerLabel(value: any): any {
    if (!value) return 'unknown'
    if (value === 'user') return 'user'
    return String(value)
  }

  function renderSessionTurnCard(trace: any, span: any): any {
    if (span.name !== 'session.turn') return ''
    const summary = traceSummary(trace)
    const attrs = span.attributes || {}
    const session = currentSession()
    const start = trace?.startTime ? formatTime(trace.startTime) : span.startTime ? formatTime(span.startTime) : '-'
    const end = trace?.endTime ? formatTime(trace.endTime) : span.endTime ? formatTime(span.endTime) : '-'
    const duration =
      trace?.durationMs != null
        ? formatDuration(trace.durationMs)
        : span.durationMs != null
          ? formatDuration(span.durationMs)
          : '-'
    const trigger = triggerLabel(span.trigger || attrs['trigger'])
    const agent = span.agentId || 'agent'
    // “本轮已加载”：插件在轮次跨度上捕获的工具、插件后端及工具、技能。早于该字段的旧追踪省略整块。
    const tools = Array.isArray(attrs['turn.tools']) ? attrs['turn.tools'] : []
    const pluginBackend = attrs['turn.plugin.backend'] || null
    const pluginTools = Array.isArray(attrs['turn.plugin.tools']) ? attrs['turn.plugin.tools'] : []
    const skills = Array.isArray(attrs['turn.skills']) ? attrs['turn.skills'] : []
    const skillCount = attrs['turn.skill_count'] != null ? attrs['turn.skill_count'] : skills.length
    const hasCaps =
      attrs['turn.tools'] !== undefined ||
      attrs['turn.skills'] !== undefined ||
      attrs['turn.plugin.backend'] !== undefined
    const overview = [
      `summary   ${agent} · ${trigger} triggered turn`,
      `session   ${span.sessionId || '-'}`,
      span.sessionKey && span.sessionKey !== span.sessionId ? `key       ${span.sessionKey}` : null,
      sessionChainLabel(session) ? `chain     ${sessionChainLabel(session)}` : null,
      span.runId ? `run       ${span.runId}` : null,
      `time      ${start}  →  ${end}   (${duration})`
    ]
      .filter(Boolean)
      .join('\n')
    const callChips = [
      `${summary.modelCalls} model`,
      `${summary.toolCalls} tool`,
      `${summary.subagents} subagent`,
      `${summary.readSkills.length} skill.read`
    ]
      .map((c: any) => `<span class="summary-chip">${escapeHtml(c)}</span>`)
      .join('')
    const capsBlock = hasCaps
      ? `<details class="model-diagnostic-details" data-detail-key="${escapeHtml(detailKey(span, 'turn-caps'))}">
        <summary class="model-panel-head"><strong>Loaded This Turn</strong> <span class="summary-chip">${tools.length} Tools · ${skillCount} Skills</span></summary>
        <pre class="structured-pre">${escapeHtml(
          `plugin backend: ${pluginBackend || 'none'}\n` +
            `plugin tools:   ${pluginTools.length ? pluginTools.join(', ') : '(none)'}\n` +
            `tools (${tools.length}): ${tools.join(', ') || '(none)'}\n` +
            `skills (${skillCount}): ${skills.join(', ') || '(none)'}`
        )}</pre>
      </details>`
      : ''
    return `
    <article class="content-card wide-card">
      <header><h4>Turn Overview</h4><div class="chip-row">${callChips}</div></header>
      <pre class="structured-pre">${escapeHtml(overview)}</pre>
      ${capsBlock}
    </article>`
  }

  const CUSTOM_RENDERERS: any = {
    sessionTurn: (span: any, trace: any) => renderSessionTurnCard(trace, span),
    llmCall: (span: any, trace: any, artifacts: any) =>
      renderModelInputCard(span, artifacts) + renderModelOutputCard(span, artifacts),
    subagentCall: (span: any, trace: any, artifacts: any) =>
      renderSubagentCallCard(span, artifacts) + renderSubagentRunCard(span),
    skillRead: (span: any, trace: any, artifacts: any) => renderSkillReadCard(trace, span, artifacts),
    memoryRecall: (span: any, trace: any, artifacts: any) => renderMemoryRecallCard(span, artifacts),
    memoryStore: (span: any, trace: any, artifacts: any) => renderMemoryStoreCard(span, artifacts),
    memoryFeedback: (span: any) => renderMemoryFeedbackCard(span)
  }

  function descriptorFor(name: any): any {
    return (state.descriptors && state.descriptors[name]) || null
  }

  function resolveCustom(id: any, span: any, trace: any, artifacts: any): any {
    const fn = CUSTOM_RENDERERS[id]
    return fn ? fn(span, trace, artifacts) : ''
  }

  function applyTemplate(tmpl: any, obj: any): any {
    return String(tmpl).replace(/\{([^}]+)\}/g, (_: any, k: any) => {
      const v = obj?.[k.trim()]
      return v == null ? '' : String(v)
    })
  }

  function topLevelPayload(io: any, artifacts: any): any {
    if (!io) return undefined
    if (io.artifact_path) {
      const found = (artifacts || []).find((a: any) => a.artifact?.path === io.artifact_path)
      if (found) return found.artifact?.parsed ?? found.artifact?.content
    }
    return io.preview
  }

  function resolveSource(span: any, source: any, pick: any, artifacts: any): any {
    if (!source) return undefined
    let value
    if (source === 'input') value = topLevelPayload(span.input, artifacts)
    else if (source === 'output') value = topLevelPayload(span.output, artifacts)
    else if (source.startsWith('attr:')) value = span.attributes?.[source.slice(5)]
    else if (source.startsWith('artifact:')) {
      const p = span.attributes?.[`${source.slice('artifact:'.length)}.artifact_path`]
      const found = (artifacts || []).find((a: any) => a.artifact?.path === p)
      value = found?.artifact?.parsed ?? found?.artifact?.content
    }
    if (pick && value && typeof value === 'object') value = value[pick]
    return value
  }

  function renderByKind(value: any, kind: any, panel?: any): any {
    if (kind === 'list' && Array.isArray(value)) {
      const text = value
        .map((it: any, i: any) => {
          if (panel?.item) return `${i + 1}. ${applyTemplate(panel.item, it)}`
          if (it && typeof it === 'object') return `${i + 1}. ${it.text ?? JSON.stringify(it)}`
          return `${i + 1}. ${it}`
        })
        .join('\n\n')
      return preBody(text)
    }
    if (kind === 'messages' && Array.isArray(value)) {
      return preBody(value.map((m: any) => `[${(m && m.role) || '?'}]\n${(m && m.content) || ''}`).join('\n\n'))
    }
    if (kind === 'kv' && value && typeof value === 'object') {
      const lines = jsonEntries(value).map(([k, v]: any) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`)
      return preBody(lines.join('\n'))
    }
    if (kind === 'text') return preBody(typeof value === 'string' ? value : prettyValue(value))
    return `<pre class="structured-pre">${escapeHtml(prettyValue(value))}</pre>`
  }

  function renderPanel(span: any, panel: any, artifacts: any, trace: any): any {
    if (panel.render && panel.render.startsWith('custom:')) {
      return resolveCustom(panel.render.slice('custom:'.length), span, trace, artifacts)
    }
    const value = resolveSource(span, panel.source, panel.pick, artifacts)
    return memoryIoCard(panel.title || '', '', renderByKind(value, panel.render || 'json', panel))
  }

  function renderFallbackBody(span: any, artifacts: any): any {
    const cards: any[] = []
    if (span.input) {
      cards.push(
        memoryIoCard(
          'Input',
          span.input.kind || '',
          renderByKind(topLevelPayload(span.input, artifacts), span.input.kind || 'json')
        )
      )
    }
    if (span.output) {
      cards.push(
        memoryIoCard(
          'Output',
          span.output.kind || '',
          renderByKind(topLevelPayload(span.output, artifacts), span.output.kind || 'json')
        )
      )
    }
    if (cards.length) return cards.join('')
    const arts = artifacts || []
    if (arts.length) {
      return arts
        .map(
          ({ label, artifact }: any) => `
          <article class="content-card">
            <header><h4>${escapeHtml(label)}</h4>
              <span class="card-note">${escapeHtml(shortId(artifact?.path || '-', 46))}</span></header>
            <pre>${escapeHtml(prettyArtifactContent(artifact))}</pre>
          </article>`
        )
        .join('')
    }
    return `
    <article class="content-card"><header><h4>Attributes</h4></header>
      <pre class="structured-pre">${escapeHtml(JSON.stringify(span.attributes || {}, null, 2))}</pre></article>`
  }

  function renderNodeBody(span: any, trace: any, artifacts: any): any {
    const desc = descriptorFor(span.name)
    if (desc) {
      if (desc.render && desc.render.startsWith('custom:')) {
        return resolveCustom(desc.render.slice('custom:'.length), span, trace, artifacts)
      }
      if (Array.isArray(desc.panels)) {
        return desc.panels.map((panel: any) => renderPanel(span, panel, artifacts, trace)).join('')
      }
    }
    return renderFallbackBody(span, artifacts)
  }

  function renderContent(span: any, trace: any, artifacts: any): any {
    const heroSubtitle = span.displaySubtitle || ''
    const heroModelInfo =
      span.name === 'llm.call'
        ? [span.attributes?.['llm.provider'], span.attributes?.['llm.model']].filter(Boolean).join(' / ')
        : ''
    const usageChips = span.name === 'llm.call' ? llmUsageSummary(span) : []
    const heroStatusText = span.isFailed
      ? span.failureLabel || span.status?.code || 'FAILED'
      : span.status?.code || 'OK'
    const heroStatusClass = span.isFailed ? 'summary-chip summary-chip-error' : 'summary-chip'
    return `
    <div class="content-stack">
      <article class="content-card hero-card">
        <header>
          <h4>${escapeHtml(span.displayTitle)}</h4>
          ${heroSubtitle ? `<span class="card-note">${escapeHtml(heroSubtitle)}</span>` : ''}
        </header>
        <div class="hero-metrics">
          <span class="summary-chip">${formatDuration(span.durationMs)}</span>
          <span class="${heroStatusClass}">${escapeHtml(heroStatusText)}</span>
          ${heroModelInfo ? `<span class="summary-chip">${escapeHtml(heroModelInfo)}</span>` : ''}
          ${usageChips.map((chip: any) => `<span class="summary-chip${chip.soft ? ' summary-chip-soft' : ''}">${escapeHtml(chip.text)}</span>`).join('')}
        </div>
      </article>
      ${renderNodeBody(span, trace, artifacts)}
    </div>
  `
  }

  function memoryIoCard(title: any, note: any, bodyHtml: any): any {
    return `
    <article class="content-card wide-card">
      <header><h4>${escapeHtml(title)}</h4>${note ? `<span class="card-note">${escapeHtml(note)}</span>` : ''}</header>
      ${bodyHtml}
    </article>`
  }

  function preBody(text: any): any {
    const t = text == null ? '' : String(text)
    return `<pre class="structured-pre">${escapeHtml(t.length ? t : '(empty)')}</pre>`
  }

  function messageBodyText(m: any): any {
    let body = ''
    const c = m && m.content
    if (typeof c === 'string') body = c
    else if (Array.isArray(c))
      body = c
        .map((b: any) =>
          b && typeof b === 'object' ? (b.type === 'text' ? b.text || '' : `[${b.type || 'block'}]`) : String(b)
        )
        .join('\n')
    else if (c != null) body = JSON.stringify(c)
    if (Array.isArray(m && m.tool_calls) && m.tool_calls.length) {
      body +=
        (body ? '\n' : '') +
        m.tool_calls
          .map((tc: any) => {
            const fn = (tc && tc.function) || {}
            const args = typeof fn.arguments === 'string' ? fn.arguments : JSON.stringify(fn.arguments || {})
            return `→ ${fn.name || '?'}(${args})`
          })
          .join('\n')
    }
    return body
  }

  function renderMessages(messages: any): any {
    const list = Array.isArray(messages) ? messages : []
    if (!list.length) return preBody('(no messages)')
    return `<div class="msg-list">${list
      .map((m: any) => {
        const role = (m && m.role) || '?'
        const name = m && m.name ? ` · ${escapeHtml(m.name)}` : ''
        const body = messageBodyText(m)
        const bodyHtml = escapeHtml(body || '(empty)')
        const collapse = role === 'system' || body.length > 800
        const inner = collapse
          ? `<details class="msg-collapse"><summary><span class="msg-role">${escapeHtml(role)}${name}</span><span class="msg-len">${body.length} chars</span></summary><div class="msg-body">${bodyHtml}</div></details>`
          : `<div class="msg-role">${escapeHtml(role)}${name}</div><div class="msg-body">${bodyHtml}</div>`
        return `<div class="msg msg-${escapeHtml(role)}">${inner}</div>`
      })
      .join('')}</div>`
  }

  function renderMemoryRecallCard(span: any, artifacts: any): any {
    const attrs = span.attributes || {}
    const query = attrs['memory.query'] || ''
    const inNote = [
      attrs['memory.scope'] ? `scope=${attrs['memory.scope']}` : null,
      attrs['memory.user_id'] ? `user=${attrs['memory.user_id']}` : null,
      attrs['memory.top_k'] != null ? `top_k=${attrs['memory.top_k']}` : null
    ]
      .filter(Boolean)
      .join(' · ')
    const recalled = artifactByLabel(artifacts, 'Memory Recall')?.parsed
    const list = Array.isArray(recalled) ? recalled : []
    const hits = attrs['memory.hits']
    let outText
    if (list.length) {
      outText = list
        .map((m: any, i: any) => {
          const score = m && m.score != null ? ` (score ${Number(m.score).toFixed(4)})` : ''
          return `${i + 1}.${score}\n${(m && m.text) || ''}`
        })
        .join('\n\n')
    } else {
      outText = hits === 0 ? 'No memories recalled (0 hits).' : 'No recalled-memory artifact captured.'
    }
    return (
      memoryIoCard('Recall · Input', inNote, preBody(query || '(empty query)')) +
      memoryIoCard('Recall · Output', hits != null ? `${hits} hit${hits === 1 ? '' : 's'}` : '', preBody(outText))
    )
  }

  function renderMemoryStoreCard(span: any, artifacts: any): any {
    const attrs = span.attributes || {}
    const stored = artifactByLabel(artifacts, 'Memory Store')?.parsed
    const messages = stored && Array.isArray(stored.messages) ? stored.messages : []
    const inBody = messages.length ? renderMessages(messages) : preBody('No stored-messages artifact captured.')
    const inNote = [
      attrs['memory.message_count'] != null ? `${attrs['memory.message_count']} msgs` : null,
      attrs['memory.session_id'] || null
    ]
      .filter(Boolean)
      .join(' · ')

    return (
      memoryIoCard('Store · Input', inNote, inBody) +
      memoryIoCard('Store · Output', '', preBody(span.isFailed ? 'Store failed.' : 'Store completed.'))
    )
  }

  function renderMemoryFeedbackCard(span: any): any {
    const attrs = span.attributes || {}
    const norm = (v: any) => {
      if (typeof v === 'string') {
        const parsed = parseJsonMaybe(v)
        if (parsed !== undefined && parsed !== null) v = parsed
      }
      if (v == null) return '(none)'
      if (Array.isArray(v)) return v.length ? v.join(', ') : '(none)'
      return String(v)
    }
    const inText = `injected skills: ${norm(attrs['memory.injected'])}\nused skills: ${norm(attrs['memory.used'])}`
    const outText = span.isFailed ? 'Feedback failed.' : 'Feedback completed.'
    return (
      memoryIoCard('Feedback · Input', '', preBody(inText)) + memoryIoCard('Feedback · Output', '', preBody(outText))
    )
  }

  function renderRaw(span: any, artifacts: any): any {
    const payload: any = {
      span,
      artifacts: artifacts.map(({ label, artifact }: any) => ({
        label,
        path: artifact?.path,
        parsed: artifact?.parsed,
        content: artifact?.parsed ? undefined : artifact?.content,
        error: artifact?.error
      }))
    }
    return `
    <div class="raw-view">
      <pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>
    </div>
  `
  }
  return {
    t,
    formatTime,
    formatTimeOnly,
    formatDuration,
    formatBytes,
    shortId,
    sessionChainLabel,
    traceRoundLabel,
    allSessions,
    filteredSessions,
    allApiCalls,
    filteredApiCalls,
    aggregateApiOverview,
    groupApiByProviderModel,
    currentSession,
    sortedTraces,
    currentTrace,
    currentSpan,
    preferredSpan,
    traceSummary,
    visibleTraceTree,
    collectArtifacts,
    renderContent,
    renderMetadata,
    renderRaw,
    usageFromSpan,
    usageReported
  }
}
