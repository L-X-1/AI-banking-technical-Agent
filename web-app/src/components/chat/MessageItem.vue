<script setup lang="ts">
/** MessageItem（doc 04 §5 分发器）：11 类 ServerMessage → 块组件 */
import { computed } from 'vue'
import { useChatStore } from '../../stores/chat'
import type { ChatMessage } from '../../types/protocol'
import UserMessage from './UserMessage.vue'
import AgentMessage from './AgentMessage.vue'
import ToolCallBlock from '../blocks/ToolCallBlock.vue'
import ApproveCard from '../blocks/ApproveCard.vue'
import MfaBlock from '../blocks/MfaBlock.vue'
import DisambiguationBlock from '../blocks/DisambiguationBlock.vue'
import ChartBlock from '../blocks/ChartBlock.vue'
import ReceiptBlock from '../blocks/ReceiptBlock.vue'
import AccountCard from '../blocks/AccountCard.vue'

const props = defineProps<{ message: ChatMessage }>()
const chat = useChatStore()

const m = computed(() => props.message)
const p = computed(() => (props.message.payload || {}) as Record<string, unknown>)
const isLast = computed(() => chat.messages[chat.messages.length - 1]?.id === props.message.id)

function onConfirm(approved: boolean) {
  if (!isLast.value) return
  chat.confirmAction(approved)
}
function onSubmitMfa(code: string) {
  if (!isLast.value) return
  chat.submitMfa(code)
}
function onPick(option: { id: string; primary: string }) {
  // 点击即上行结构化文本（doc 04 §4.8）；服务端 _pick_option 从文本提取尾号/备注
  chat.userSay(`选择：${option.primary}`)
}
</script>

<template>
  <UserMessage v-if="m.role === 'user'" :text="m.text || ''" />

  <template v-else-if="m.kind === 'text'">
    <AgentMessage :text="m.text || ''" />
  </template>

  <template v-else-if="m.kind === 'final'">
    <AgentMessage :text="String(p.text || '')" />
  </template>

  <template v-else-if="m.kind === 'error'">
    <AgentMessage :text="`${p.message}（${p.code}）`" tone="error" />
  </template>

  <template v-else-if="m.kind === 'tool_progress'">
    <ToolCallBlock :progress="p as never" />
  </template>

  <template v-else-if="m.kind === 'confirm_card'">
    <ApproveCard :card="p as never"
                 :handled="chat.cardState[String(p.action_id)]"
                 @confirm="onConfirm" />
  </template>

  <template v-else-if="m.kind === 'mfa_request'">
    <MfaBlock :mfa="p as never" :passed="chat.mfaState === 'passed'" @submit="onSubmitMfa" />
  </template>

  <template v-else-if="m.kind === 'clarify_options'">
    <DisambiguationBlock :clarify="p as never" @pick="onPick" />
  </template>

  <template v-else-if="m.kind === 'chart'">
    <ChartBlock :chart="p" />
  </template>

  <template v-else-if="m.kind === 'account'">
    <AccountCard :account="p as never" />
  </template>

  <template v-else-if="m.kind === 'receipt'">
    <ReceiptBlock :receipt="p as never" />
  </template>

  <template v-else-if="m.kind === 'notify'">
    <div class="notify">📣 <b>{{ p.title }}</b> · {{ p.content }}</div>
  </template>

  <template v-else-if="m.kind === 'locked'">
    <div class="locked">🔒 {{ p.reason }}（剩余 {{ Math.floor(Number(p.seconds_left || 0) / 60) }} 分钟）</div>
  </template>
</template>

<style scoped>
.notify { border: 1px solid var(--bt-pill-y); border-radius: var(--r-card); background: var(--yellow-bg); color: var(--yellow); font-size: 12.5px; padding: 10px 14px; }
.locked { border: 1px solid var(--bt-pill-r); border-radius: var(--r-card); background: var(--red-bg); color: var(--red); font-size: 12.5px; padding: 10px 14px; }
</style>
