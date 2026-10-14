<script setup lang="ts">
/** AppSidebar（doc 04 §4.1）：品牌区（随模式文案）/ ＋新会话 / ◈服务大厅 / 会话列表 / 用户卡 */
import { computed } from 'vue'
import { useAppStore } from '../../stores/app'
import { useChatStore } from '../../stores/chat'
import { useSessionStore } from '../../stores/session'
import type { SessionStatus } from '../../types/protocol'
import { wsClient } from '../../ws/client'

const app = useAppStore()
const chat = useChatStore()
const session = useSessionStore()

const butler = computed(() => app.viewMode === 'butler')
const title = computed(() => {
  const first = chat.messages.find((m) => m.role === 'user' && m.text)
  return first?.text?.slice(0, 14) || '新会话'
})
const STATUS_WORD: Record<SessionStatus, string> = {
  active: '进行中', processing: '处理中', waiting_confirm: '等待确认',
  waiting_mfa: '等待验证', waiting_clarify: '等待选择', locked: '已锁定', human_takeover: '人工接管',
}
const statusWord = computed(() => STATUS_WORD[session.status])
const DOT_CLASS: Partial<Record<SessionStatus, string>> = {
  waiting_confirm: 'yellow', waiting_mfa: 'red', locked: 'red', processing: 'yellow',
}
const dotClass = computed(() => DOT_CLASS[session.status] || '')

function newSession() {
  wsClient.close()
  chat.resetThread()
  session.newSession()
  app.hallRequested = true
  chat.connect()
}

function backToHall() {
  chat.sessionStarted = false      // 本会话内重返大厅
  app.hallRequested = true
}
</script>

<template>
  <aside class="side">
    <div class="brand"><i>◆</i> {{ butler ? '智银' : '智银 Agent' }}</div>
    <div class="newchat" @click="newSession">＋ 新会话</div>
    <div class="navitem" :class="{ on: !chat.sessionStarted }" @click="backToHall">◈ 服务大厅</div>

    <div class="sec">会话</div>
    <div class="sess on">
      {{ title }}
      <div class="tagline">
        <span v-if="dotClass" class="dot" :class="dotClass">●</span> {{ statusWord }} · 刚刚
      </div>
    </div>

    <div class="foot">
      {{ session.userName }} · 尾号 <span class="mono">6688</span><br>
      <span class="okdot">●</span> 安全引擎 · <span class="okdot">●</span> 熔断器 {{ session.breaker }}
    </div>
  </aside>
</template>

<style scoped>
.side { width: 230px; background: var(--bg-sunken); border-right: 1px solid var(--border); display: flex; flex-direction: column; flex: none; }
.brand { padding: 16px 16px 12px; color: var(--text-primary); font-weight: 700; font-size: 14px; }
.brand i { color: var(--brand); font-style: normal; }
.newchat { margin: 0 12px; padding: 8px; text-align: center; font-size: 12.5px; color: var(--text-secondary); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }
.newchat:hover { border-color: var(--border-strong); }
.navitem { margin: 8px 12px 0; padding: 8px; text-align: center; font-size: 12.5px; color: var(--text-muted); border: 1px dashed var(--border); border-radius: 8px; cursor: pointer; }
.navitem.on, .navitem:hover { color: var(--brand); border: 1px solid var(--border-strong); background: var(--bg-panel); }
.sec { font-size: 10.5px; color: var(--text-faint); padding: 16px 16px 6px; letter-spacing: 1px; }
.sess { padding: 8px 16px; font-size: 12.5px; color: var(--text-muted); border-left: 2px solid transparent; }
.sess.on { color: var(--text-primary); background: var(--bg-panel); border-left-color: var(--brand); }
.sess .tagline { font-size: 10px; color: var(--text-faint); margin-top: 2px; }
.dot.yellow { color: var(--yellow); } .dot.red { color: var(--red); }
.foot { margin-top: auto; padding: 12px 16px; border-top: 1px solid var(--border); font-size: 11.5px; color: var(--text-muted); line-height: 1.9; }
.okdot { color: var(--green); }
@media (max-width: 1023px) { .side { display: none; } }
</style>
