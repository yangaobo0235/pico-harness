// AUTO-GENERATED — DO NOT EDIT — run `npm run gen:contracts`.
export type SpanNode = Span & {
  depth: number;
  children: SpanNode[];
  [k: string]: unknown;
};

export interface TracingContracts {
  Span?: Span;
  SpanNode?: SpanNode;
  Trace?: Trace;
  TraceSession?: TraceSession;
  LogWindow?: LogWindow;
  TraceData?: TraceData;
  Artifact?: Artifact;
  Descriptor?: Descriptor;
  DescriptorsResponse?: DescriptorsResponse;
  SearchHit?: SearchHit;
  SearchResponse?: SearchResponse;
  HealthResponse?: HealthResponse;
  ShutdownResponse?: ShutdownResponse;
}
export interface Span {
  spanId: string;
  traceId: string;
  traceKey?: string | null;
  parentSpanId?: string | null;
  name: string;
  kind: string;
  startTime: string;
  endTime?: string | null;
  durationMs: number;
  status: {
    code?: string | number | null;
    message?: string | null;
    [k: string]: unknown;
  };
  isFailed: boolean;
  failureLabel: string;
  attributes: {
    [k: string]: unknown;
  };
  events: {
    time: string;
    name: string;
    [k: string]: unknown;
  }[];
  sessionId?: string | null;
  sessionKey?: string | null;
  agentId?: string | null;
  workspaceDir?: string | null;
  runId?: string | null;
  trigger?: string | null;
  channelId?: string | null;
  displayTitle: string;
  displaySubtitle: unknown;
  displayParentSpanId?: string | null;
  [k: string]: unknown;
}
export interface Trace {
  traceKey: string;
  traceId: string;
  sessionId: string;
  sessionKey: string | null;
  agentId: string | null;
  workspaceDir: string | null;
  trigger: string | null;
  channelId: string | null;
  startTime: string;
  endTime: string | null;
  durationMs: number;
  spanCount: number;
  visibleSpanCount: number;
  spans: Span[];
  tree: SpanNode[];
  events: {
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
export interface TraceSession {
  sessionId: string;
  sessionKey: string | null;
  agentId: string | null;
  workspaceDir: string | null;
  trigger: string | null;
  channelId: string | null;
  resumedFrom: string | null;
  resumedTo: string | null;
  startedAt: string | null;
  updatedAt: string | null;
  traceCount: number;
  traces: Trace[];
  [k: string]: unknown;
}
export interface LogWindow {
  bytesRead: number;
  maxBytes: number;
  filesRead: number;
  filesAvailable: number;
  records: number;
  truncated: boolean;
  [k: string]: unknown;
}
export interface TraceData {
  generatedAt: string;
  sessions: TraceSession[];
  window: {
    truncated: boolean;
    spans: LogWindow;
    events: LogWindow;
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
export interface Artifact {
  path: string;
  content: string;
  parsed: unknown;
  [k: string]: unknown;
}
export interface Descriptor {
  type: string;
  label?: string;
  subtitle?: string;
  render?: string;
  usage?: boolean;
  status?: {
    [k: string]: unknown;
  }[];
  panels?: {
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
export interface DescriptorsResponse {
  descriptors: Descriptor[];
  [k: string]: unknown;
}
export interface SearchHit {
  sessionId: string;
  traceKey: string;
  traceId: string;
  spanId: string;
  name: string;
  title: string;
  startTime: string;
  field: string;
  snippet: string;
  subtitle?: unknown;
  [k: string]: unknown;
}
export interface SearchResponse {
  results: SearchHit[];
  [k: string]: unknown;
}
export interface HealthResponse {
  ok: true;
  port: number;
  stateDir: string;
  [k: string]: unknown;
}
export interface ShutdownResponse {
  ok: true;
  stopping: true;
  [k: string]: unknown;
}
