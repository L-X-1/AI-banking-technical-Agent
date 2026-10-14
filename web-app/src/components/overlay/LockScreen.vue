<script setup lang="ts">
/** LockScreen（doc 04 §4.16）：熔断锁定全屏遮罩 + mono 倒计时；演示口令解锁（admin123） */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useChatStore } from '../../stores/chat'
import { useSessionStore } from '../../stores/session'

const session = useSessionStore()
const chat = useChatStore()
const pwd = ref('')
const hint = ref('')

const left = ref(0)
let timer: number | null = null

const mmss = computed(() => {
  const s = Math.max(0, left.value)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})

function tick() {
  left.value = Math.max(0, Math.floor((session.lockUntil - Date.now()) / 1000))
  if (left.value === 0 && session.status === 'locked') session.setStatus('active')
}

function unlock() {
  // 演示环境人工接管出口（doc 06 §5.2 偏差②：解锁口令代替重登录）
  if (pwd.value.trim() === 'admin123') {
    session.setStatus('active')
    hint.value = ''
  } else {
    hint.value = '口令不正确（演示口令：admin123）'
  }
}

onMounted(() => { tick(); timer = window.setInterval(tick, 1000) })
onBeforeUnmount(() => { if (timer !== null) clearInterval(timer) })
</script>

<template>
  <div class="lock">
    <div class="card">
      <div class="title">🔒 会话已临时锁定</div>
      <div class="reason">{{ session.lockReason || '安全熔断触发' }}</div>
      <div class="count mono">{{ mmss }}</div>
      <div class="sub">或输入主管口令解锁（演示：admin123）</div>
      <div class="row">
        <input v-model="pwd" type="password" placeholder="主管口令" @keydown.enter="unlock" >
        <button class="pri" @click="unlock">解锁</button>
        <button class="gho" @click="chat.sendInterrupt('stop')">放弃操作</button>
      </div>
      <div class="hint" v-if="hint">{{ hint }}</div>
    </div>
  </div>
</template>

<style scoped>
.lock {
  position: fixed; inset: 0; z-index: var(--z-lock);
  background: rgba(0, 0, 0, .72); backdrop-filter: blur(4px);
  display: flex; align-items: center; justify-content: center;
}
.card {
  width: 360px; background: var(--bg-panel); border: 1px solid var(--border-strong);
  border-left: 3px solid var(--red); border-radius: 14px; padding: 22px 24px;
}
.title { color: var(--red); font-weight: 700; font-size: 14.5px; }
.reason { color: var(--text-secondary); font-size: 12.5px; margin-top: 8px; line-height: 1.7; }
.count { color: var(--text-primary); font-size: 30px; margin: 14px 0 4px; letter-spacing: 2px; }
.sub { color: var(--text-muted); font-size: 11.5px; }
.row { display: flex; gap: 8px; margin-top: 12px; }
input {
  flex: 1; background: var(--bg-base); border: 1px solid var(--border-strong);
  color: var(--text-primary); border-radius: 8px; padding: 8px 10px; font-size: 13px;
}
button { border-radius: 8px; font-size: 12.5px; padding: 8px 12px; }
.pri { background: var(--brand); border: 1px solid var(--brand); color: #141414; font-weight: 600; }
.gho { background: transparent; border: 1px solid var(--border-strong); color: var(--text-muted); }
.hint { color: var(--red); font-size: 11.5px; margin-top: 8px; }
</style>
