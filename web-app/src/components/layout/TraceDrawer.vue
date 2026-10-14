<script setup lang="ts">
/** TraceDrawer（doc 04 §4.14 ★答辩核心）：三页签——DAG 图 / 裁决日志 / 审计流（REST 拉取） */
import { computed, ref, watch } from 'vue'
import { getAudit } from '../../api/http'
import { useAppStore } from '../../stores/app'
import { useChatStore } from '../../stores/chat'
import { useSessionStore } from '../../stores/session'
import type { AuditEvent } from '../../types/protocol'

const app = useAppStore()
const chat = useChatStore()
const session = useSessionStore()

const events = ref<AuditEvent[]>([])
const loading = ref(false)

async function loadAudit() {
  if (!session.lastTraceId) return
  loading.value = true
  try { events.value = (await getAudit(session.lastTraceId)).events } catch { events.value = [] }
  finally { loading.value = false }
}

watch(() => app.traceDrawerOpen, (open) => { if (open) loadAudit() })
watch(() => app.traceDrawerTab, (tab) => { if (tab === 'audit' || tab === 'decision') loadAudit() })

const planNodes = computed(() => {
  const plan = events.value.find((e) => e.node === 'plan')
  const nodes = (plan?.payload as { nodes?: { id: string; tool: string; depends_on: string[] }[] })?.nodes || []
  return nodes.map((n) => {
    const live = chat.dagNodes.find((d) => d.id === n.id)
    return { ...n, status: live?.status || 'pending', from: (n.depends_on || []).join(',') || '—' }
  })
})

const decisions = computed(() => events.value.filter((e) => e.node === 'decision'))

const LEVEL_CLASS: Record<string, string> = { green: 'g', yellow: 'y', red: 'r', deny: 'r' }

function levelOf(e: AuditEvent): string {
  const p = e.payload as Record<string, unknown>
  return String(p.level || p.stage || '')
}

function summary(e: AuditEvent): string {
  const p = e.payload as Record<string, unknown>
  if (e.node === 'intent') return `${p.scenario} · ${JSON.stringify(p.slots)}`
  if (e.node === 'plan') return String(p.goal || '')
  if (e.node === 'decision') return `${p.stage || p.node || ''} ${p.level ? `[${p.level}]` : ''} ${((p.reasons as string[]) || []).join('；')}`
  if (e.node === 'tool_call') return `${p.tool} ${p.ok ? '✓' : '✗'} ${p.duration_ms}ms`
  if (e.node === 'confirm') return JSON.stringify(p)
  if (e.node === 'reply') return String(p.text || '')
  return ''
}

const STATUS_ICON: Record<string, string> = {
  done: '☒', running: '◐', waiting_confirm: '⚠', waiting_mfa: '⚠', pending: '☐', failed: '✗', compensated: '↩',
}
</script>

<template>
  <transition name="drawer">
    <div v-if="app.traceDrawerOpen" class="drawer">
      <div class="tabs">
        <span :class="{ on: app.traceDrawerTab === 'dag' }" @click="app.traceDrawerTab = 'dag'">DAG 图</span>
        <span :class="{ on: app.traceDrawerTab === 'decision' }" @click="app.traceDrawerTab = 'decision'">裁决日志</span>
        <span :class="{ on: app.traceDrawerTab === 'audit' }" @click="app.traceDrawerTab = 'audit'">审计流</span>
        <span class="x" @click="app.closeTrace()">✕</span>
      </div>

      <div class="body">
        <div v-if="loading" class="muted">加载中…</div>
        <template v-else-if="app.traceDrawerTab === 'dag'">
          <div v-if="!planNodes.length" class="muted">本会话尚无执行计划（发一条指令试试）。</div>
          <div v-for="n in planNodes" :key="n.id" class="dag-node">
            <span class="ic" :class="n.status">{{ STATUS_ICON[n.status] }}</span>
            <span class="mono tool">{{ n.tool }}</span>
            <span class="dep">← {{ n.from }}</span>
          </div>
        </template>
        <template v-else-if="app.traceDrawerTab === 'decision'">
          <div v-if="!decisions.length" class="muted">暂无裁决记录。</div>
          <div v-for="d in decisions" :key="d.id" class="dec">
            <span class="badge" :class="LEVEL_CLASS[levelOf(d).split('[')[0]] || 'g'">{{ levelOf(d) }}</span>
            <span class="dec-main">{{ summary(d) }}</span>
          </div>
        </template>
        <template v-else>
          <div v-if="!events.length" class="muted">该 trace 暂无审计事件。</div>
          <div v-for="e in events" :key="e.id" class="evt" :class="e.node">
            <span class="ts mono">{{ e.created_at.slice(11) }}</span>
            <span class="node">{{ e.node }}</span>
            <span class="txt">{{ summary(e) }}</span>
          </div>
        </template>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.drawer {
  width: 360px; flex: none; border-left: 1px solid var(--border); background: var(--bg-sunken);
  display: flex; flex-direction: column;
}
.tabs { display: flex; gap: 12px; padding: 12px 14px; border-bottom: 1px solid var(--border); font-size: 12.5px; color: var(--text-muted); }
.tabs span { cursor: pointer; }
.tabs span.on { color: var(--text-primary); border-bottom: 2px solid var(--brand); padding-bottom: 2px; }
.tabs .x { margin-left: auto; color: var(--text-faint); }
.body { flex: 1; overflow-y: auto; padding: 12px 14px; font-size: 12px; }
.muted { color: var(--text-faint); }
.dag-node { display: flex; align-items: center; gap: 8px; padding: 5px 0; color: var(--text-secondary); }
.ic.done { color: var(--green); }
.ic.running, .ic.waiting_confirm, .ic.waiting_mfa { color: var(--yellow); }
.ic.pending { color: var(--text-faint); }
.ic.failed { color: var(--red); }
.tool { color: var(--text-primary); }
.dep { color: var(--text-faint); font-size: 11px; margin-left: auto; }
.dec { display: flex; gap: 8px; padding: 5px 0; align-items: baseline; color: var(--text-muted); }
.badge { font-size: 10px; border-radius: 999px; padding: 1px 7px; border: 1px solid; flex: none; }
.badge.g { color: var(--green); border-color: var(--bt-pill-g); }
.badge.y { color: var(--yellow); border-color: var(--bt-pill-y); }
.badge.r { color: var(--red); border-color: var(--bt-pill-r); }
.dec-main { color: var(--text-secondary); }
.evt { display: flex; gap: 8px; padding: 3px 0; color: var(--text-muted); align-items: baseline; }
.evt .node { color: var(--text-secondary); min-width: 62px; }
.evt.intent .node { color: #94a3b8; }
.evt.plan .node { color: #c084fc; }
.evt.decision .node { color: var(--yellow); }
.evt.tool_call .node { color: var(--green); }
.evt.confirm .node { color: #fb923c; }
.evt.reply .node { color: var(--text-primary); }
.txt { color: var(--text-muted); }
.drawer-enter-active, .drawer-leave-active { transition: transform .2s ease, opacity .2s ease; }
.drawer-enter-from, .drawer-leave-to { transform: translateX(30px); opacity: 0; }
@media (max-width: 1279px) {
  .drawer { position: absolute; right: 0; top: 0; bottom: 0; z-index: var(--z-drawer); box-shadow: -18px 0 40px rgba(0, 0, 0, .5); }
}
</style>

