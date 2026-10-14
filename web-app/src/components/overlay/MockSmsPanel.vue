<script setup lang="ts">
/** MockSmsPanel（doc 04 §4.15）：MFA 下发滑入，演示环境直显验证码；10s 自动收起 */
import { computed, watch } from 'vue'
import { useAppStore } from '../../stores/app'
import { useChatStore } from '../../stores/chat'

const app = useAppStore()
const chat = useChatStore()
const visible = computed(() => app.smsPanelVisible && !!chat.smsContent)

let timer: number | null = null
watch(visible, (v) => {
  if (timer !== null) { clearTimeout(timer); timer = null }
  if (v) timer = window.setTimeout(() => app.hideSms(), 10000)
})
</script>

<template>
  <transition name="sms">
    <div v-if="visible" class="sms" @click="app.hideSms()">
      <div class="hd">📱 手机通知 <span class="close">×</span></div>
      <div class="body">{{ chat.smsContent }}</div>
      <div class="code mono" v-if="chat.smsCode">{{ chat.smsCode }}</div>
    </div>
  </transition>
</template>

<style scoped>
.sms {
  position: fixed; top: 16px; right: 16px; width: 260px;
  background: var(--bg-panel); border: 1px solid var(--border-strong);
  border-radius: 12px; padding: 12px 14px; z-index: var(--z-sms);
  box-shadow: 0 18px 50px rgba(0, 0, 0, .55); cursor: pointer;
}
.hd { color: var(--text-muted); font-size: 11.5px; display: flex; justify-content: space-between; }
.close { color: var(--text-faint); }
.body { color: var(--text-secondary); font-size: 12.5px; margin-top: 8px; line-height: 1.7; }
.code { color: var(--brand); font-size: 18px; font-weight: 700; letter-spacing: 3px; margin-top: 6px; }
.sms-enter-active, .sms-leave-active { transition: transform .2s ease, opacity .2s ease; }
.sms-enter-from, .sms-leave-to { opacity: 0; transform: translateX(20px); }
</style>
