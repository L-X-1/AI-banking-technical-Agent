<script setup lang="ts">
/** UserMessage（doc 04 §4.3）：管家模式气泡右对齐；透视模式 ❯ 前缀 */
import { computed } from 'vue'
import { useAppStore } from '../../stores/app'

defineProps<{ text: string }>()
const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')
</script>

<template>
  <div v-if="butler" class="bt-user"><div class="bub">{{ text }}</div></div>
  <div v-else class="u">{{ text }}</div>
</template>

<style scoped>
.u { color: var(--text-primary); font-size: 14px; }
.u::before { content: "❯ "; color: var(--brand); font-weight: 700; }
.bt-user { display: flex; justify-content: flex-end; }
.bub {
  background: var(--bt-bubble); color: var(--text-primary); font-size: 13.5px;
  padding: 9px 15px; border-radius: 16px 16px 4px 16px; max-width: 78%; line-height: 1.7;
}
</style>
