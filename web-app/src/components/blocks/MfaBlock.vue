<script setup lang="ts">
/** MfaBlock（doc 04 §4.7）：六格验证码；自动右移/粘贴拆分/退格回退；错误抖动；
 *  attemptsLeft 归零由服务端锁会话（LockScreen 接管）。红色强阻断样式仅此块保留（§11.2#3）。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useChatStore } from '../../stores/chat'
import type { MfaRequestPayload } from '../../types/protocol'

const props = defineProps<{ mfa: MfaRequestPayload; passed?: boolean }>()
const emit = defineEmits<{ (e: 'submit', code: string): void }>()
const chat = useChatStore()

const digits = ref<string[]>(['', '', '', '', '', ''])
const inputs = ref<HTMLInputElement[]>([])
const shake = ref(false)
const submitted = ref(false)

const left = ref(props.mfa.expires_in_sec)
let timer: number | null = null
onMounted(() => { timer = window.setInterval(() => { if (left.value > 0) left.value -= 1 }, 1000) })
onBeforeUnmount(() => { if (timer !== null) clearInterval(timer) })

const mmss = computed(() => {
  const s = Math.max(0, left.value)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})
const code = computed(() => digits.value.join(''))
const done = computed(() => !!props.passed)

// 错误验证码：随 mfa_retry/error 触发的抖动由父级传入 attempts 变化——本地以 lastError 观察
watch(() => chat.lastError, (e) => {
  if (e && (e.code === 'MFA_MISMATCH' || e.code === 'MFA_INVALID')) {
    shake.value = true
    setTimeout(() => { shake.value = false }, 320)
    if (e.code === 'MFA_MISMATCH') { digits.value = ['', '', '', '', '', '']; nextTick(() => inputs.value[0]?.focus()) }
  }
})

function setDigit(i: number, v: string) {
  const ch = (v.match(/\d/) || [''])[0]
  digits.value[i] = ch
  if (ch && i < 5) nextTick(() => inputs.value[i + 1]?.focus())
}
function onPaste(e: ClipboardEvent) {
  const text = e.clipboardData?.getData('text') || ''
  const six = text.replace(/\D/g, '').slice(0, 6)
  if (!six) return
  e.preventDefault()
  six.split('').forEach((c, i) => { digits.value[i] = c })
  nextTick(() => inputs.value[Math.min(5, six.length - 1)]?.focus())
}
function onBack(i: number, e: KeyboardEvent) {
  if (e.key === 'Backspace' && !digits.value[i] && i > 0) nextTick(() => inputs.value[i - 1]?.focus())
}
function submit() {
  if (done.value || submitted.value || code.value.length < 6) return
  submitted.value = true
  emit('submit', code.value)
}
</script>

<template>
  <div class="mfa" :class="{ done, shake }">
    <div class="hd">
      🔐 多因子认证 · 短信验证
      <span class="cd mono" v-if="!done">{{ mmss }} ⏳</span>
      <span class="cd ok" v-else>已通过 ✓</span>
    </div>
    <div class="to">验证码已发送至 <span class="mono">{{ mfa.target_masked }}</span></div>
    <div class="cells">
      <input v-for="(d, i) in digits" :key="i" :ref="(el) => { if (el) inputs[i] = el as HTMLInputElement }"
             class="mono" :class="{ filled: !!d }" inputmode="numeric" maxlength="1"
             :value="d" :disabled="done" @input="setDigit(i, ($event.target as HTMLInputElement).value)"
             @keydown="onBack(i, $event)" @paste="onPaste" >
      <span class="left-tip">剩余尝试：{{ mfa.attempts_left }} 次</span>
    </div>
    <div class="act">
      <button class="pri" :disabled="done || code.length < 6" @click="submit">确认验证</button>
      <span class="resend">没收到？60s 后重发</span>
    </div>
  </div>
</template>

<style scoped>
.mfa {
  border: 1px solid var(--border-strong); border-left: 3px solid var(--red);
  border-radius: var(--r-card); background: var(--bg-panel); padding: 12px 14px;
}
.mfa.done { opacity: .6; }
.mfa.shake { animation: shake .3s; }
@keyframes shake { 0%,100% { transform: translateX(0) } 25% { transform: translateX(-6px) } 75% { transform: translateX(6px) } }
.hd { color: var(--text-primary); font-weight: 600; display: flex; align-items: center; gap: 8px; }
.cd { margin-left: auto; color: var(--text-muted); font-size: 11.5px; }
.cd.ok { color: var(--green); }
.to { color: var(--text-muted); font-size: 12.5px; margin: 8px 0 10px; }
.cells { display: flex; align-items: center; gap: 8px; }
.cells input {
  width: 36px; height: 44px; text-align: center; font-size: 20px;
  background: var(--bg-base); border: 1px solid var(--border-strong);
  color: var(--text-primary); border-radius: 8px;
}
.cells input:focus { border-color: var(--red); }
.cells input.filled { border-color: var(--border-strong); color: var(--text-primary); }
.left-tip { color: var(--text-faint); font-size: 11px; margin-left: 6px; }
.act { display: flex; align-items: center; gap: 12px; margin-top: 12px; }
.pri {
  background: var(--red); border: 1px solid var(--red); color: #141414;
  font-weight: 600; border-radius: 8px; padding: 8px 16px; font-size: 12.5px;
}
.pri:disabled { opacity: .45; cursor: not-allowed; }
.resend { color: var(--text-faint); font-size: 11.5px; }
</style>
