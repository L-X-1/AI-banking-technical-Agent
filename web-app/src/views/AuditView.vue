<script setup lang="ts">
/** AuditView（doc 04 §4.17 答辩杀手锏）：trace 摘要 + 六类事件时间线 + 逐条重放点亮动画 */
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAudit } from '../api/http'
import type { AuditEvent } from '../types/protocol'

const route = useRoute()
const router = useRouter()
const events = ref<AuditEvent[]>([])
const lit = ref(0)
const playing = ref(false)
let timer: number | null = null

onMounted(async () => {
  events.value = (await getAudit(String(route.params.traceId))).events
  play()
})

function play() {
  if (timer !== null) clearInterval(timer)
  lit.value = 0
  playing.value = true
  timer = window.setInterval(() => {
    lit.value += 1
    if (lit.value >= events.value.length) {
      if (timer !== null) clearInterval(timer)
      playing.value = false
    }
  }, 400)
}

function summary(e: AuditEvent): string {
  const p = e.payload as Record<string, unknown>
  if (e.node === 'intent') return `${p.scenario} · ${JSON.stringify(p.slots)}`
  if (e.node === 'plan') return `${p.goal || ''}｜${((p.nodes as unknown[]) || []).length} 节点`
  if (e.node === 'decision') return `${p.stage || p.node || ''} ${p.level ? `[${p.level}]` : ''} ${((p.reasons as string[]) || []).join('；')}`
  if (e.node === 'tool_call') return `${p.tool} ${p.ok ? '✓' : '✗'} ${p.duration_ms}ms｜${p.summary || ''}`
  if (e.node === 'confirm') return JSON.stringify(p)
  if (e.node === 'reply') return String(p.text || '')
  return JSON.stringify(p)
}

const KIND_CLASS: Record<string, string> = {
  intent: 'intent', plan: 'plan', decision: 'decision', tool_call: 'tool', confirm: 'confirm', reply: 'reply',
}
</script>

<template>
  <div class="audit">
    <div class="top">
      <span class="mono">trace #{{ String(route.params.traceId).replace(/^tr_/, '') }}</span>
      <span class="dim">共 {{ events.length }} 条事件</span>
      <button class="gho" @click="play" :disabled="playing">{{ playing ? '重放中…' : '▶ 重新播放' }}</button>
      <a class="back" @click="router.push('/chat')">← 返回会话</a>
    </div>

    <div class="line">
      <div v-for="(e, i) in events" :key="e.id" class="evt" :class="[KIND_CLASS[e.node], { on: i < lit }]">
        <span class="dot" />
        <span class="ts mono">{{ e.created_at.slice(11) }}</span>
        <span class="badge" :class="KIND_CLASS[e.node]">{{ e.node }}</span>
        <span class="txt">{{ summary(e) }}</span>
        <details v-if="e.node === 'decision' || e.node === 'plan'">
          <summary>payload</summary>
          <pre class="mono">{{ JSON.stringify(e.payload, null, 2) }}</pre>
        </details>
      </div>
    </div>
  </div>
</template>

<style scoped>
.audit { max-width: 900px; margin: 0 auto; padding: 20px 24px 40px; }
.top { display: flex; align-items: center; gap: 12px; color: var(--text-primary); font-size: 13.5px; margin-bottom: 16px; }
.dim { color: var(--text-faint); font-size: 12px; }
.gho { margin-left: auto; background: transparent; border: 1px solid var(--border-strong); color: var(--text-muted); border-radius: 999px; padding: 5px 14px; font-size: 12px; }
.back { color: var(--brand); cursor: pointer; font-size: 12.5px; }
.line { border-left: 1px solid var(--border); padding-left: 16px; display: flex; flex-direction: column; gap: 10px; }
.evt { display: flex; gap: 10px; align-items: baseline; opacity: .25; transition: opacity .4s ease; position: relative; font-size: 12.5px; }
.evt.on { opacity: 1; }
.dot { position: absolute; left: -21px; top: 6px; width: 7px; height: 7px; border-radius: 50%; background: var(--text-faint); }
.evt.on .dot { background: var(--brand); }
.ts { color: var(--text-faint); font-size: 11.5px; }
.badge { font-size: 10px; border-radius: 999px; padding: 1px 8px; border: 1px solid var(--border-strong); color: var(--text-muted); }
.badge.intent { color: #94a3b8; } .badge.plan { color: #c084fc; } .badge.decision { color: var(--yellow); }
.badge.tool { color: var(--green); } .badge.confirm { color: #fb923c; } .badge.reply { color: var(--text-primary); }
.txt { color: var(--text-secondary); }
details { color: var(--text-faint); }
pre { background: var(--bg-panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-top: 6px; font-size: 11px; overflow-x: auto; }
</style>
