/** 消息流与待办（doc 04 §6）：渲染流唯一事实来源；11 类 ServerMessage 分发（§5 表） */
import { defineStore } from 'pinia'
import { wsClient } from '../ws/client'
import type {
  ChatMessage, ClarifyPayload, ConfirmCardPayload, DagNodeProgress, InboundMessage,
  MfaRequestPayload, ServerMessage, SessionSnapshotPayload,
} from '../types/protocol'
import { useAppStore } from './app'
import { useSessionStore } from './session'

let seq = 0
const mid = () => `m${Date.now()}_${seq++}`

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [] as ChatMessage[],
    /** 待办确认卡（服务端 payload 原样，金额/收款人唯一事实源） */
    pendingAction: null as ConfirmCardPayload | null,
    pendingMfa: null as MfaRequestPayload | null,
    clarify: null as ClarifyPayload | null,
    /** 卡片提交态（防重复点击）：action_id → approved/rejected */
    cardState: {} as Record<string, 'approved' | 'rejected'>,
    mfaState: '' as '' | 'passed' | 'failed',
    dagNodes: [] as DagNodeProgress[],
    streamingText: '',
    smsContent: '',
    smsCode: '',
    lastError: null as { code: string; message: string } | null,
    /** 首条消息后大厅让位消息流（本会话内不回显，侧栏可重返） */
    sessionStarted: false,
    connected: false,
  }),
  actions: {
    push(m: ChatMessage) { this.messages.push(m) },

    bindWs() {
      wsClient.onMessage((msg) => this.applyServerMessage(msg))
    },

    connect() {
      const session = useSessionStore()
      wsClient.connect(session.sessionId)
      this.connected = true
    },

    userSay(text: string) {
      const app = useAppStore()
      app.hallRequested = false          // 发出指令 → 大厅让位消息流
      this.push({ id: mid(), role: 'user', kind: 'text', text, ts: Date.now() })
      this.sessionStarted = true
      this.send({ type: 'user_message', text })
    },

    send(msg: InboundMessage) { wsClient.send(msg) },

    confirmAction(approved: boolean) {
      const a = this.pendingAction
      if (!a || this.cardState[a.action_id]) return          // 防重复上行
      this.cardState[a.action_id] = approved ? 'approved' : 'rejected'
      this.send({ type: 'action_confirm', action_id: a.action_id, approved })
    },

    submitMfa(code: string) {
      const m = this.pendingMfa
      if (!m) return
      this.send({ type: 'mfa_submit', challenge_id: m.challenge_id, code })
    },

    sendInterrupt(mode: 'stop' | 'takeover') { this.send({ type: 'interrupt', mode }) },

    /** §5 分发表：按 type 分发；tool_progress 同时更新工具块与 dagNodes */
    applyServerMessage(msg: ServerMessage) {
      const session = useSessionStore()
      const app = useAppStore()
      switch (msg.type) {
        case 'session_ready':
          session.sessionId = msg.payload.session_id
          break
        case 'session_snapshot':
          this.applySnapshot(msg.payload)
          break
        case 'stream_token':
          this.streamingText += msg.payload.delta
          break
        case 'tool_progress': {
          const p = msg.payload
          this.upsertDag(p.node_id, p.tool, p.status === 'failed' ? 'failed' : 'done')
          this.push({ id: mid(), role: 'agent', kind: 'tool_progress', payload: p, ts: Date.now() })
          break
        }
        case 'confirm_card':
          this.pendingAction = msg.payload
          session.setStatus('waiting_confirm')
          session.setTrace(msg.trace_id || session.lastTraceId)
          this.markDagWaiting()
          this.push({ id: mid(), role: 'agent', kind: 'confirm_card',
                      payload: msg.payload, trace_id: msg.trace_id, ts: Date.now() })
          break
        case 'mfa_request':
          this.pendingMfa = msg.payload
          session.setStatus('waiting_mfa')
          this.push({ id: mid(), role: 'agent', kind: 'mfa_request', payload: msg.payload, ts: Date.now() })
          break
        case 'mfa_sms':
          this.smsContent = msg.payload.content
          this.smsCode = (msg.payload.content.match(/(\d{6})/) || [])[1] || ''
          app.showSms()
          break
        case 'mfa_retry':
          break
        case 'clarify_options':
          this.clarify = msg.payload
          session.setStatus('waiting_clarify')
          this.push({ id: mid(), role: 'agent', kind: 'clarify_options', payload: msg.payload, ts: Date.now() })
          break
        case 'receipt': {
          const p = msg.payload
          if (p.trace_id) session.setTrace(p.trace_id)
          this.push({ id: mid(), role: 'agent', kind: 'receipt', payload: p, ts: Date.now() })
          break
        }
        case 'notify':
          this.push({ id: mid(), role: 'system', kind: 'notify', payload: msg.payload, ts: Date.now() })
          app.showSms()
          break
        case 'locked':
          session.lock(msg.payload.reason, msg.payload.seconds_left)
          this.push({ id: mid(), role: 'system', kind: 'locked', payload: msg.payload, ts: Date.now() })
          break
        case 'error':
          this.lastError = { code: msg.payload.code, message: msg.payload.message }
          if (msg.payload.code === 'SESSION_LOCKED') {
            session.lock(msg.payload.message, msg.payload.seconds_left || 900)
          }
          this.push({ id: mid(), role: 'agent', kind: 'error', payload: msg.payload, ts: Date.now() })
          break
        case 'final': {
          if (this.streamingText) {
            this.push({ id: mid(), role: 'agent', kind: 'text', text: this.streamingText, ts: Date.now() })
            this.streamingText = ''
          }
          this.push({ id: mid(), role: 'agent', kind: 'final', payload: msg.payload, ts: Date.now() })
          break
        }
        case 'status': {
          session.setStatus(msg.payload.status)
          if (msg.payload.status === 'active') {
            this.pendingAction = null
            this.pendingMfa = null
            this.clarify = null
            this.mfaState = ''
            app.hideSms()
            this.dagNodes = this.dagNodes.map((n) =>
              (n.status === 'running' ? { ...n, status: 'done' } : n))
          }
          break
        }
        default:
          break
      }
    },

    /** 快照恢复（doc 04 §7）：刷新/重连后原样重放待办块（服务端唯一事实源，可继续点） */
    applySnapshot(snap: SessionSnapshotPayload) {
      const session = useSessionStore()
      session.setStatus(snap.session_status)
      session.setTrace(snap.trace_id)
      this.sessionStarted = true
      if (snap.card) {
        delete this.cardState[snap.card.action_id]      // 恢复的卡片可继续提交
        this.pendingAction = snap.card
        this.push({ id: mid(), role: 'agent', kind: 'confirm_card', payload: snap.card, ts: Date.now() })
      }
      if (snap.mfa) {
        this.pendingMfa = snap.mfa
        this.push({ id: mid(), role: 'agent', kind: 'mfa_request', payload: snap.mfa, ts: Date.now() })
        if (snap.mfa.code) {
          this.smsCode = snap.mfa.code
          this.smsContent = `【智银】验证码 ${snap.mfa.code}，5 分钟内有效。`
          useAppStore().showSms()
        }
      }
    },

    upsertDag(nodeId: string, tool: string, status: DagNodeProgress['status']) {
      const hit = this.dagNodes.find((n) => n.id === nodeId)
      if (hit) hit.status = status
      else this.dagNodes.push({ id: nodeId, label: nodeId, toolName: tool, status })
    },

    /** 待办卡出现时把最后一个执行节点标为等待确认/等待 MFA（DAG 逐节点点亮） */
    markDagWaiting() {
      const hit = this.dagNodes.find((n) => n.status === 'pending' || n.status === 'running')
      if (hit) hit.status = this.pendingAction?.risk_level === 'red' ? 'waiting_mfa' : 'waiting_confirm'
    },

    resetThread() {
      this.messages = []
      this.pendingAction = null
      this.pendingMfa = null
      this.clarify = null
      this.cardState = {}
      this.dagNodes = []
      this.streamingText = ''
      this.sessionStarted = false
      this.lastError = null
    },
  },
})

