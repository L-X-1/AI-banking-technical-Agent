<script setup lang="ts">
/** StatusBar（doc 04 §4.13）：管家模式精简（安全圆点 + trace）；透视模式完整计数（§11.2#7） */
import { computed } from 'vue'
import { useAppStore } from '../../stores/app'
import { useSessionStore } from '../../stores/session'

const app = useAppStore()
const session = useSessionStore()
const butler = computed(() => app.viewMode === 'butler')
const traceShort = computed(() => (session.lastTraceId || '').replace(/^tr_/, '') || '—')
const today = computed(() => (session.todayTransferCents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2 }))
</script>

<template>
  <div class="bar" :class="{ mono: !butler }">
    <span v-if="butler">
      <span class="g">●</span> 安全守护中
      <span class="sep">·</span> trace <span class="mono">{{ traceShort }}</span>
    </span>
    <span v-else>
      会话 #{{ session.sessionId }} <span class="sep">·</span> trace {{ traceShort }} <span class="sep">·</span>
      <span class="g">●</span> 熔断器 {{ session.breaker }} <span class="sep">·</span>
      注入检测 {{ session.injectionHits }} 命中 <span class="sep">·</span> 今日转账 ¥{{ today }}/50,000
    </span>
    <span v-if="butler" class="right mono">Shift+Tab 透视 · 全链路审计可回放</span>
  </div>
</template>

<style scoped>
.bar {
  border-top: 1px solid var(--border); background: var(--bg-sunken); padding: 6px 18px;
  display: flex; justify-content: space-between; font-size: 11px; color: var(--text-muted);
}
.g { color: var(--green); }
.sep { color: var(--text-faint); margin: 0 4px; }
.right { color: var(--text-faint); }
</style>
