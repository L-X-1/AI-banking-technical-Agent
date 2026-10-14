<script setup lang="ts">
/** ChatInput（doc 04 §4.12）：占位轮播（与大厅示例同源）；Enter 发送 / Shift+Enter 换行 /
 *  Esc 中断（处理中）；状态机决定可用性（processing/locked 禁用）。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { PLACEHOLDER_PROMPTS } from '../../config/scenarios'
import { useAppStore } from '../../stores/app'
import { useChatStore } from '../../stores/chat'
import { useSessionStore } from '../../stores/session'

const chat = useChatStore()
const session = useSessionStore()
const app = useAppStore()

const text = ref('')
const placeholder = ref(PLACEHOLDER_PROMPTS[0] || '输入指令…')
let rot: number | null = null

const disabled = computed(() => session.status === 'locked')
const busy = computed(() => session.status === 'processing')
const modeHint = computed(() => app.viewMode === 'butler' ? 'Shift+Tab 切换透视模式' : 'Shift+Tab 返回管家模式')

function send() {
  const v = text.value.trim()
  if (!v || disabled.value) return
  chat.userSay(v)
  text.value = ''
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
}

onMounted(() => {
  rot = window.setInterval(() => {
    const arr = PLACEHOLDER_PROMPTS
    if (!arr.length) return
    const i = arr.indexOf(placeholder.value)
    placeholder.value = arr[(i + 1) % arr.length]
  }, 4200)
})
onBeforeUnmount(() => { if (rot !== null) clearInterval(rot) })
</script>

<template>
  <div class="box">
    <div class="input" :class="{ butler: app.viewMode === 'butler', dis: disabled }">
      <textarea v-model="text" rows="1" :disabled="disabled"
                :placeholder="busy ? '正在处理…' : placeholder" @keydown="onKeydown" />
      <button class="send" :disabled="disabled || !text.trim()" @click="send">⏎</button>
    </div>
    <div class="helper">
      <span class="mono">deepseek-chat · 智银 v1.0</span>
      <span>Enter 发送 · Shift+Enter 换行 · Esc 中断｜{{ modeHint }}</span>
    </div>
  </div>
</template>

<style scoped>
.box { padding: 0 24px 10px; }
.input {
  max-width: 820px; margin: 0 auto; display: flex; align-items: flex-end; gap: 8px;
  border: 1px solid var(--border-strong); border-radius: 12px; background: var(--bg-panel);
  padding: 10px 12px; transition: border-color var(--motion), box-shadow var(--motion);
}
.input.butler { border-radius: 999px; padding: 11px 18px; }
.input:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(212, 175, 55, .12); }
.input.dis { opacity: .55; }
textarea {
  flex: 1; background: transparent; border: none; resize: none; color: var(--text-primary);
  font-size: 13.5px; line-height: 1.6; max-height: 120px;
}
textarea::placeholder { color: var(--text-faint); }
.send { background: transparent; border: none; color: var(--text-primary); font-size: 14px; }
.send:disabled { color: var(--text-faint); }
.helper {
  max-width: 820px; margin: 6px auto 0; display: flex; justify-content: space-between;
  color: var(--text-faint); font-size: 11px;
}
</style>
