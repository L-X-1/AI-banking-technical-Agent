<script setup lang="ts">
/** 应用外壳：全局快捷键（Shift+Tab 双层模式 / Esc 中断）+ 全局浮层（锁定遮罩、模拟短信） */
import { onBeforeUnmount, onMounted } from 'vue'
import { useAppStore } from './stores/app'
import { useChatStore } from './stores/chat'
import { useSessionStore } from './stores/session'
import LockScreen from './components/overlay/LockScreen.vue'
import MockSmsPanel from './components/overlay/MockSmsPanel.vue'

const app = useAppStore()
const chat = useChatStore()
const session = useSessionStore()

function onKey(e: KeyboardEvent) {
  if (e.shiftKey && e.key === 'Tab') {          // §11.1 双层模式切换
    e.preventDefault()
    app.toggleMode()
    return
  }
  if (e.key === 'Escape' && !chat.pendingAction && !chat.pendingMfa) {
    chat.sendInterrupt('stop')                  // doc 06 §3.5 规则 1：Esc 中断
  }
}

onMounted(() => {
  chat.bindWs()
  chat.connect()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="shell" :data-mode="app.viewMode">
    <router-view />
    <MockSmsPanel />
    <LockScreen v-if="session.status === 'locked'" />
  </div>
</template>

<style scoped>
.shell { height: 100%; }
</style>
