import type { TraceData, Descriptor } from '@pico/contracts/tracing'

export type Language = 'en' | 'zh'
export interface ViewerState {
  data: TraceData | null
  descriptors: Record<string, Descriptor>
  appView: 'trace' | 'api'
  selectedSessionId: string | null
  selectedTraceKey: string | null
  selectedSpanId: string | null
  selectedTab: 'content' | 'metadata' | 'raw'
  search: string
  searchSessionIds: string[]
  agent: string
  provider: string
  model: string
  apiStatus: string
  apiWindow: string
  lang: Language
}

export function initialState(): ViewerState {
  let lang: Language = 'en'
  try {
    if (localStorage.getItem('tracing:lang') === 'zh') lang = 'zh'
  } catch {
    /* Private mode. */
  }
  return {
    data: null,
    descriptors: {},
    appView: 'trace',
    selectedSessionId: null,
    selectedTraceKey: null,
    selectedSpanId: null,
    selectedTab: 'content',
    search: '',
    searchSessionIds: [],
    agent: 'all',
    provider: 'all',
    model: 'all',
    apiStatus: 'all',
    apiWindow: '24h',
    lang
  }
}
