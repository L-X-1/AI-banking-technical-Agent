<script setup lang="ts">
/** AgentMessage（doc 04 §4.3）：管家模式 22px 圆点头像 + UI 字体；透视模式 ⏺ + 控制台字体。
 *  有限 Markdown：加粗 / 行内 code / 列表（不渲染链接与图片，安全收敛）。 */
import { computed } from 'vue'
import { useAppStore } from '../../stores/app'

const props = defineProps<{ text: string; tone?: 'normal' | 'error' | 'streaming' }>()
const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')

const html = computed(() => {
  let h = props.text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
  h = h.replace(/(^|\n)-\s(.+)/g, '$1• $2')
  return h
})
</script>

<template>
  <div v-if="butler" class="bt-agent">
    <div class="bt-ava">智</div>
    <div class="bt-msg" :class="tone" v-html="html" />
  </div>
  <div v-else class="a" :class="tone" v-html="html" />
</template>

<style scoped>
.a { color: var(--text-secondary); font-size: 13.5px; line-height: 1.75; }
.a::before { content: "⏺ "; color: var(--green); }
.a.error::before { color: var(--red); }
.a.error { color: var(--red); }
:deep(code) { background: var(--bg-panel); border-radius: 4px; padding: 0 4px; font-family: var(--font-mono); font-size: 12px; }
.bt-agent { display: flex; gap: 10px; align-items: flex-start; }
.bt-ava {
  width: 22px; height: 22px; border-radius: 50%; background: var(--bt-ava); color: #141414;
  font-size: 11px; font-weight: 700; display: flex; align-items: center; justify-content: center;
  flex: none; margin-top: 2px;
}
.bt-msg { color: var(--text-secondary); font-size: 13.5px; line-height: 1.8; padding-top: 2px; }
.bt-msg.error { color: var(--red); }
</style>
