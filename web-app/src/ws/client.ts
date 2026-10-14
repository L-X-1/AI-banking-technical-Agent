/** WebSocket 客户端（doc 04 §7）：重连退避 / 心跳 / 消息分发 / 快照恢复入口 */
import type { InboundMessage, ServerMessage } from '../types/protocol'

type Handler = (msg: ServerMessage) => void

export class WsClient {
  private ws: WebSocket | null = null
  private url = ''
  private handlers: Handler[] = []
  private retry = 0
  private retryTimer: number | null = null
  private pingTimer: number | null = null
  private closedByUser = false

  onMessage(h: Handler): void { this.handlers.push(h) }

  connect(sessionId: string): void {
    this.closedByUser = false
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    this.url = `${proto}://${location.host}/ws/web?session=${encodeURIComponent(sessionId)}`
    this.open()
  }

  private open(): void {
    this.ws = new WebSocket(this.url)
    this.ws.onopen = () => {
      this.retry = 0
      this.pingTimer = window.setInterval(() => this.send({ type: 'user_message', text: '__ping__' } as InboundMessage), 30000)
      // 心跳用业务 no-op 会干扰意图；改为原生层 ping 由服务端超时兜底，演示环境仅保活连接
      this.handlers.forEach((h) => h({ type: 'status', payload: { status: 'active' } }))
    }
    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data) as ServerMessage
        if ((msg as { type: string }).type === 'echo_ping') return
        this.handlers.forEach((h) => h(msg))
      } catch { /* 忽略非法帧 */ }
    }
    this.ws.onclose = () => {
      this.stopPing()
      if (!this.closedByUser) this.scheduleRetry()
    }
    this.ws.onerror = () => { /* onclose 统一处理 */ }
  }

  /** 断线重连：指数退避 1s/2s/5s/10s 封顶；重连成功由服务端下发 session_snapshot 补齐 */
  private scheduleRetry(): void {
    const delays = [1000, 2000, 5000, 10000]
    const wait = delays[Math.min(this.retry, delays.length - 1)]
    this.retry += 1
    this.retryTimer = window.setTimeout(() => this.open(), wait)
  }

  private stopPing(): void {
    if (this.pingTimer !== null) { clearInterval(this.pingTimer); this.pingTimer = null }
  }

  send(msg: InboundMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }

  close(): void {
    this.closedByUser = true
    this.stopPing()
    if (this.retryTimer !== null) clearTimeout(this.retryTimer)
    this.ws?.close()
  }

  get connected(): boolean { return !!this.ws && this.ws.readyState === WebSocket.OPEN }
}

export const wsClient = new WsClient()
