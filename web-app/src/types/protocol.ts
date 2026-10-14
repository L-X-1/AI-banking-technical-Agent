/** 协议类型（与 doc 02 §10.1 一致；doc 04 §5 分发表） */

export type RiskLevel = 'green' | 'yellow' | 'red'

export type SessionStatus =
  | 'active' | 'processing' | 'waiting_confirm' | 'waiting_mfa' | 'waiting_clarify'
  | 'locked' | 'human_takeover'

export interface DetailRow { label: string; value: string }

export interface ConfirmCardPayload {
  action_id: string
  risk_level: 'yellow' | 'red'
  title: string
  detail: DetailRow[]
  consequence: string
  expires_in_sec: number
  upgrade_reasons?: string[]
}

export interface MfaRequestPayload {
  challenge_id: string
  type: 'sms' | 'face'
  target_masked: string
  expires_in_sec: number
  attempts_left: number
  /** 仅演示环境随快照下发（MockSmsPanel 同源） */
  code?: string
}

export interface ToolProgressPayload {
  node_id: string
  tool: string
  status: 'done' | 'failed'
  duration_ms: number
  result_summary: string
}

export type DagNodeStatus =
  | 'done' | 'running' | 'waiting_confirm' | 'waiting_mfa' | 'pending' | 'failed' | 'compensated'

export interface DagNodeProgress {
  id: string
  label: string
  toolName: string
  status: DagNodeStatus
}

export interface ClarifyOption { id: string; primary: string; secondary?: string }
export interface ClarifyPayload { question: string; options: ClarifyOption[] }

export interface ReceiptPayload {
  title: string
  amount?: number | null
  counterparty?: string | null
  detail: DetailRow[]
  risk_level?: RiskLevel
  trace_id?: string
}

export interface NotifyPayload { event_type: string; title: string; content: string }

export interface SessionSnapshotPayload {
  session_id: string
  session_status: SessionStatus
  trace_id: string
  card: ConfirmCardPayload | null
  mfa: MfaRequestPayload | null
}

export type ServerMessage =
  | { type: 'session_ready'; payload: { session_id: string } }
  | { type: 'session_snapshot'; payload: SessionSnapshotPayload }
  | { type: 'stream_token'; payload: { delta: string } }
  | { type: 'tool_progress'; payload: ToolProgressPayload }
  | { type: 'confirm_card'; payload: ConfirmCardPayload; trace_id?: string }
  | { type: 'mfa_request'; payload: MfaRequestPayload }
  | { type: 'mfa_sms'; payload: { content: string; challenge_id?: string } }
  | { type: 'mfa_retry'; payload: { challenge_id: string; attempts_left: number } }
  | { type: 'clarify_options'; payload: ClarifyPayload }
  | { type: 'receipt'; payload: ReceiptPayload }
  | { type: 'account'; payload: unknown }
  | { type: 'chart'; payload: unknown }
  | { type: 'notify'; payload: NotifyPayload; trace_id?: string }
  | { type: 'locked'; payload: { reason: string; seconds_left: number } }
  | { type: 'final'; payload: { text: string } }
  | { type: 'error'; payload: { code: string; message: string; seconds_left?: number } }
  | { type: 'status'; payload: { status: SessionStatus } }

export type InboundMessage =
  | { type: 'user_message'; text: string }
  | { type: 'action_confirm'; action_id: string; approved: boolean }
  | { type: 'mfa_submit'; challenge_id: string; code: string }
  | { type: 'interrupt'; mode: 'stop' | 'takeover' }

export interface ChatMessage {
  id: string
  role: 'user' | 'agent' | 'system'
  kind: ServerMessage['type'] | 'text'
  text?: string
  payload?: unknown
  trace_id?: string
  ts: number
}

export interface AuditEvent {
  id: number
  trace_id: string
  session_id: string
  node: 'intent' | 'plan' | 'decision' | 'tool_call' | 'confirm' | 'reply'
  payload: Record<string, unknown>
  created_at: string
}
