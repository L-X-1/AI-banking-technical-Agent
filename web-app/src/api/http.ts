/** REST 客户端（登录、审计查询、会话快照、IM 桥）（doc 04 §1 / §7） */
import type { AuditEvent, SessionSnapshotPayload } from '../types/protocol'

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<T>
}

export function getHealth() {
  return j<{ status: string; service: string }>('/health').catch(() => ({ status: 'down', service: '' }))
}

export function getAudit(traceId: string) {
  return j<{ trace_id: string; events: AuditEvent[]; kinds: string[] }>(`/api/audit/${traceId}`)
}

export function getSessionSnapshot(sessionId: string) {
  return j<SessionSnapshotPayload>(`/api/session/${encodeURIComponent(sessionId)}`)
}

/** MockImView 走模拟 IM webhook（doc 02 §10.2；同一 Agent 同一 trace，非流式降级） */
export function imSend(sessionId: string, text: string) {
  return j<{ session_id: string; trace_id: string; session_status: string; replies: string[] }>(
    '/api/im/webhook', { method: 'POST', body: JSON.stringify({ session_id: sessionId, text }) })
}
