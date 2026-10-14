<script setup lang="ts">
/** ChatThread（doc 04 §4.2）：消息列表 + 自动滚动（视口在底部 120px 内才抢滚动）+ 回到底部钮。
 *  末位渲染 TodoDagBlock（doc 04 §5：`tool_progress` → ToolCallBlock + TodoDagBlock）——
 *  DAG 是本轮流式聚合状态而非单条消息，故挂在消息流尾部随节点点亮（§4.5）。 */
import { nextTick, onMounted, ref, watch } from 'vue'
import { useChatStore } from '../../stores/chat'
import MessageItem from './MessageItem.vue'
import TodoDagBlock from '../blocks/TodoDagBlock.vue'

const chat = useChatStore()
const scrollEl = ref<HTMLElement | null>(null)
const atBottom = ref(true)

function onScroll() {
  const el = scrollEl.value
  if (!el) return
  atBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

function jumpToBottom() {
  atBottom.value = true
  toBottom()
}


async function toBottom() {
  await nextTick()
  const el = scrollEl.value
  if (el && atBottom.value) el.scrollTop = el.scrollHeight
}

watch(() => chat.messages.length, toBottom)
watch(() => chat.streamingText, toBottom)
watch(() => chat.dagNodes.map((n) => n.status).join(), toBottom)   // 节点点亮亦随流滚动
onMounted(toBottom)
</script>

<template>
  <div class="wrap">
    <div ref="scrollEl" class="thread" @scroll="onScroll">
      <div class="col">
        <template v-for="m in chat.messages" :key="m.id">
          <div class="divider" v-if="m.role === 'user' && (m.kind === 'text')">── 今天 {{ new Date(m.ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }} ──</div>
          <MessageItem :message="m" />
        </template>
        <div v-if="chat.streamingText" class="streaming">
          {{ chat.streamingText }}<span class="caret">▍</span>
        </div>
        <TodoDagBlock v-if="chat.dagNodes.length" :nodes="chat.dagNodes" />
      </div>
    </div>
    <button v-if="!atBottom" class="jump" @click="jumpToBottom">↓ 回到底部</button>
  </div>
</template>

<style scoped>
.wrap { position: relative; flex: 1; min-height: 0; display: flex; }
.thread { flex: 1; overflow-y: auto; padding: 22px 0; }
.col { max-width: 820px; margin: 0 auto; padding: 0 24px; display: flex; flex-direction: column; gap: 14px; }
.divider { text-align: center; color: var(--text-faint); font-size: 11px; }
.streaming { color: var(--text-secondary); font-size: 13.5px; line-height: 1.75; }
.caret { color: var(--text-faint); animation: blink 1s infinite; }
@keyframes blink { 50% { opacity: 0; } }
.jump {
  position: absolute; right: 22px; bottom: 12px; width: 32px; height: 32px; border-radius: 50%;
  background: var(--bg-panel); border: 1px solid var(--border-strong); color: var(--text-muted); font-size: 11px;
}
</style>
