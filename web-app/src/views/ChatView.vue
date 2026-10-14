<script setup lang="ts">
/** ChatView（doc 04 §3.3 主战场）：侧栏 + 模式壳（大厅/消息流）+ 输入框 + 状态栏 + 透视抽屉 */
import { computed, onMounted } from 'vue'
import { getSessionSnapshot } from '../api/http'
import { useAppStore } from '../stores/app'
import { useChatStore } from '../stores/chat'
import { useSessionStore } from '../stores/session'
import AppSidebar from '../components/layout/AppSidebar.vue'
import StatusBar from '../components/layout/StatusBar.vue'
import TraceDrawer from '../components/layout/TraceDrawer.vue'
import PerspectiveLayer from '../components/layout/PerspectiveLayer.vue'
import ChatThread from '../components/chat/ChatThread.vue'
import ChatInput from '../components/chat/ChatInput.vue'
import ScenarioHub from '../components/chat/ScenarioHub.vue'

const app = useAppStore()
const chat = useChatStore()
const session = useSessionStore()

const showHall = computed(() => !chat.sessionStarted || app.hallRequested)

onMounted(async () => {
  // 刷新恢复（doc 04 §7）：REST 兜底（WS 亦会推送 session_snapshot，重复应用被去重）
  try {
    const snap = await getSessionSnapshot(session.sessionId)
    if (snap.card || snap.mfa) chat.applySnapshot(snap)
  } catch { /* 服务不可达时保持空态 */ }
})
</script>

<template>
  <div class="app">
    <AppSidebar />
    <PerspectiveLayer>
      <div v-if="showHall" class="hall-wrap">
        <div class="hall-col"><ScenarioHub /></div>
      </div>
      <ChatThread v-else />
      <ChatInput />
      <StatusBar />
    </PerspectiveLayer>
    <TraceDrawer />
  </div>
</template>

<style scoped>
.app { display: flex; height: 100%; position: relative; background: var(--bg-base); }
.hall-wrap { flex: 1; overflow-y: auto; padding: 22px 0; }
.hall-col { max-width: 820px; margin: 0 auto; padding: 0 24px; }
</style>
