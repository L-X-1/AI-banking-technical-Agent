<script setup lang="ts">
/** PerspectiveLayer（doc 04 §11.1）：双层 UI 模式壳——两模式共享同一消息流与状态机，零协议差异。
 *  壳层提供模式徽标与「切到透视」入口；块组件按 viewMode 自选渲染变体（§11.2 覆盖表）。 */
import { computed } from 'vue'
import { useAppStore } from '../../stores/app'

const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')
</script>

<template>
  <div class="layer" :data-mode="app.viewMode">
    <div class="modebar">
      <span class="mode" :class="{ on: butler }">管家模式</span>
      <span class="mode" :class="{ on: !butler }">透视模式</span>
      <a class="switch" @click="app.toggleMode()">Shift+Tab 切换</a>
      <a class="trace" v-if="!butler" @click="app.openTrace('dag')">查看过程</a>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.layer { flex: 1; display: flex; flex-direction: column; min-width: 0; position: relative; }
.modebar {
  display: flex; align-items: center; gap: 10px; padding: 6px 18px;
  border-bottom: 1px solid var(--border); background: var(--bg-sunken); font-size: 11px;
}
.mode { color: var(--text-faint); border: 1px solid var(--border); border-radius: 999px; padding: 1px 10px; }
.mode.on { color: var(--brand); border-color: rgba(212, 175, 55, .45); }
.switch, .trace { color: var(--text-muted); cursor: pointer; }
.trace { margin-left: auto; text-decoration: underline; text-underline-offset: 3px; }
</style>
