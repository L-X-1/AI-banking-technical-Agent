<script setup lang="ts">
/** ToolCallBlock（doc 04 §4.4）：⏺ 工具名(参数) + 状态位 + ⎿ 结果摘要；
 *  管家模式折叠为一行进度摘要（§11.2#4），点击「查看过程」切透视。 */
import { computed, ref } from 'vue'
import { useAppStore } from '../../stores/app'
import type { ToolProgressPayload } from '../../types/protocol'

const props = defineProps<{ progress: ToolProgressPayload }>()
const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')
const expand = ref(false)

const statusText = computed(() =>
  props.progress.status === 'done' ? `✓ ${props.progress.duration_ms}ms` : '✗ 失败')
</script>

<template>
  <div v-if="butler" class="butler-line">
    <span class="ok" :class="{ bad: progress.status === 'failed' }">
      {{ progress.status === 'failed' ? '✗' : '✓' }}
    </span>
    <span class="sum">{{ progress.result_summary }} · <span class="mono">{{ progress.duration_ms }}ms</span></span>
    <a class="lk" @click="app.toggleMode()">查看过程 →</a>
  </div>

  <div v-else class="tool">
    <div class="t1">
      ⏺ {{ progress.tool }}<span class="dim">(node: {{ progress.node_id }})</span>
      <span class="st" :class="progress.status === 'done' ? 'g' : 'r'">{{ statusText }}</span>
    </div>
    <div class="res" :class="{ collapsed: !expand }" @click="expand = !expand">{{ progress.result_summary }}</div>
  </div>
</template>

<style scoped>
.tool { border: 1px solid var(--border); border-radius: var(--r-card); background: var(--bg-panel); padding: 10px 14px; font-size: 12.5px; }
.t1 { color: var(--text-primary); font-family: var(--font-mono); }
.dim { color: var(--text-faint); margin-left: 6px; }
.st { float: right; }
.g { color: var(--green); } .r { color: var(--red); }
.res { color: var(--text-muted); padding-left: 18px; position: relative; margin-top: 4px; line-height: 1.8; cursor: pointer; }
.res::before { content: "⎿"; position: absolute; left: 0; color: var(--text-faint); }
.res.collapsed { max-height: 3.6em; overflow: hidden; }
.butler-line { display: flex; align-items: center; gap: 8px; margin-left: 32px; color: var(--text-muted); font-size: 12px; }
.butler-line .ok {
  width: 16px; height: 16px; border-radius: 50%; background: var(--green-bg); color: var(--green);
  font-size: 10px; display: flex; align-items: center; justify-content: center; flex: none;
}
.butler-line .ok.bad { background: var(--red-bg); color: var(--red); }
.sum { color: var(--text-muted); }
.lk { color: var(--text-muted); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
</style>
