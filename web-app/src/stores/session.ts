/** 会话状态机镜像（doc 04 §6；与服务端 doc 03 §2.1 同步） */
import { defineStore } from 'pinia'
import type { SessionStatus } from '../types/protocol'

const SID_KEY = 'zy_session_id'

export const useSessionStore = defineStore('session', {
  state: () => ({
    token: sessionStorage.getItem('zy_token') || '',
    userId: 'u001',
    userName: '张三',
    sessionId: localStorage.getItem(SID_KEY) || newSessionId(),
    status: 'active' as SessionStatus,
    lockReason: '',
    lockUntil: 0,
    todayTransferCents: 0,
    injectionHits: 0,
    breaker: 'closed',
    lastTraceId: '',
    availableBalance: 0,
  }),
  actions: {
    newSession() {
      this.sessionId = newSessionId()
      localStorage.setItem(SID_KEY, this.sessionId)
      this.status = 'active'
      this.lastTraceId = ''
    },
    setStatus(s: SessionStatus) {
      this.status = s
      if (s !== 'locked') { this.lockReason = ''; this.lockUntil = 0 }
    },
    setTrace(t: string) { if (t) this.lastTraceId = t },
    lock(reason: string, secondsLeft: number) {
      this.status = 'locked'
      this.lockReason = reason
      this.lockUntil = Date.now() + secondsLeft * 1000
    },
  },
})

function newSessionId(): string {
  return 's_' + Math.random().toString(36).slice(2, 8)
}
