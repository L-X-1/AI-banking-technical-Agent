<script setup lang="ts">
/** TodoDagBlock（doc 04 §4.5）：执行计划清单，节点状态逐一点亮；
 *  管家模式折叠为一行摘要（§11.2#4）。「⤢ 详情」开透视抽屉 DAG 页签。 */
import { computed } from 'vue'
import { useAppStore } from '../../stores/app'
import type { DagNodeProgress } from '../../types/protocol'

const props = defineProps<{ nodes: DagNodeProgress[] }>()
const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')

const ICONS: Record<DagNodeProgress['status'], string> = {
  done: '☒', running: '◐', waiting_confirm: '⚠', waiting_mfa: '⚠',
  pending: '☐', failed: '✗', compensated: '↩',
}
const doneCount = computed(() => props.nodes.filter((n) => n.status === 'done').length)
</script>

<template>
  <div v-if="butler" class="butler-line">
    <span class="ok">✓</span>
    <span>已推进 {{ doneCount }}/{{ nodes.length }} 步</span>
    <a class="lk" @click="app.openTrace('dag')">查看计划 →</a>
  </div>

  <div v-else class="todo">
    <div class="h">执行计划 · DAG
      <a class="more" @click="app.openTrace('dag')">⤢ 详情</a>
    </div>
    <div v-for="n in nodes" :key="n.id" class="node">
      <span class="ic" :class="n.status">{{ ICONS[n.status] }}</span>
      <span class="mono tool-name">{{ n.toolName }}</span>
      <span class="lbl">（{{ n.label }}）</span>
      <span class="tag" v-if="n.status === 'waiting_mfa'">⚠ 等待 MFA</span>
      <span class="tag" v-else-if="n.status === 'waiting_confirm'">⚠ 等待确认</span>
    </div>
  </div>
</template>

<style scoped>
.todo { border: 1px solid var(--border); border-radius: var(--r-card); background: var(--bg-panel); padding: 10px 14px; font-size: 12.5px; }
.h { color: var(--text-muted); font-size: 11px; letter-spacing: 1px; margin-bottom: 6px; display: flex; justify-content: space-between; }
.more { color: var(--text-muted); cursor: pointer; letter-spacing: 0; }
.node { color: var(--text-secondary); padding: 2px 0; display: flex; align-items: center; gap: 6px; }
.ic { width: 16px; } .ic.done { color: var(--green); }
.ic.running { color: var(--yellow); animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.ic.waiting_confirm, .ic.waiting_mfa { color: var(--yellow); } .ic.failed { color: var(--red); }
.ic.pending { color: var(--text-faint); } .ic.compensated { color: var(--text-muted); }
.tool-name { color: var(--text-primary); }
.lbl { color: var(--text-muted); }
.tag { margin-left: auto; color: var(--yellow); font-size: 11px; }
.butler-line { display: flex; align-items: center; gap: 8px; margin-left: 32px; color: var(--text-muted); font-size: 12px; }
.butler-line .ok {
  width: 16px; height: 16px; border-radius: 50%; background: var(--green-bg); color: var(--green);
  font-size: 10px; display: flex; align-items: center; justify-content: center; flex: none;
}
.lk { color: var(--text-muted); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
</style>
