<script setup lang="ts">
/** MockImView（doc 04 §4.18 / M3#8）：模拟 IM 渠道页——极简手机 IM；
 *  审批降级为「回复 1 确认 / 2 取消」；MFA 直接输 6 位短信码。
 *  同一 Agent、同一 trace、同一权限链路：UI 降级，安全不降级。 */
import { nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'
import { imSend } from '../api/http'

const router = useRouter()
const sid = ref('s_im_' + Math.random().toString(36).slice(2, 6))
const draft = ref('')
const log = ref<{ me: boolean; text: string; kind: string; trace?: string }[]>([
  { me: false, text: '您好，我是智银 IM 客服。试试「给赵敏转 200」。', kind: '' },
])
const logEl = ref<HTMLElement | null>(null)
const lastTrace = ref('')

async function send(text?: string) {
  const v = (text ?? draft.value).trim()
  if (!v) return
  log.value.push({ me: true, text: v, kind: '' })
  draft.value = ''
  try {
    const out = await imSend(sid.value, v)
    lastTrace.value = out.trace_id || lastTrace.value
    out.replies.forEach((r) => log.value.push({ me: false, text: r, kind: kindOf(r), trace: out.trace_id }))
  } catch (e) {
    log.value.push({ me: false, text: `发送失败：${e}`, kind: 'warn' })
  }
  await nextTick()
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

function kindOf(text: string): string {
  if (/【失败|锁定/.test(text)) return 'warn'
  if (/【需确认|【请选择|【短信验证/.test(text)) return 'ask'
  if (/【回执|【通知/.test(text)) return 'ok'
  return ''
}

const needConfirm = () => log.value.some((l) => /回复 1 确认 \/ 2 取消/.test(l.text))
</script>

<template>
  <div class="page">
    <div class="phone">
      <div class="head">
        智银 IM 客服
        <small>非流式降级通道 · 同一 trace · 红操作仍需短信码</small>
      </div>
      <div ref="logEl" class="log">
        <div v-for="(m, i) in log" :key="i" class="b" :class="[m.me ? 'me' : 'bot', m.kind]">
          {{ m.text }}
          <div class="trace mono" v-if="m.trace">trace #{{ m.trace.replace(/^tr_/, '') }}</div>
        </div>
      </div>
      <div class="quick" v-if="needConfirm()">
        <button @click="send('1')">1 确认</button>
        <button @click="send('2')">2 取消</button>
      </div>
      <div class="bar">
        <input v-model="draft" placeholder="输入指令 / 回复 1 / 输入 6 位验证码" @keydown.enter="send()">
        <button class="pri" @click="send()">发送</button>
      </div>
      <div class="hint">trace 随消息下发，可跳 <a @click="router.push('/audit/' + lastTrace)" :class="{ dis: !lastTrace }">审计回放</a>；同一 Agent，安全等级不降。</div>
    </div>
  </div>
</template>

<style scoped>
.page { min-height: 100%; display: flex; justify-content: center; padding: 24px 12px; }
.phone { width: 390px; max-width: 96vw; border: 1px solid var(--border); border-radius: 22px; background: var(--bg-base); overflow: hidden; display: flex; flex-direction: column; }
.head { padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--brand); font-weight: 600; font-size: 14px; }
.head small { display: block; color: var(--text-faint); font-weight: 400; font-size: 11px; margin-top: 2px; }
.log { height: 460px; overflow-y: auto; padding: 14px 12px; display: flex; flex-direction: column; gap: 8px; }
.b { max-width: 88%; padding: 8px 12px; border-radius: 12px; font-size: 13px; line-height: 1.7; white-space: pre-wrap; }
.me { align-self: flex-end; background: var(--brand); color: #141414; }
.bot { align-self: flex-start; background: var(--bg-panel); border: 1px solid var(--border); color: var(--text-secondary); }
.bot.ok { border-left: 3px solid var(--green); }
.bot.warn { border-left: 3px solid var(--red); }
.bot.ask { border-left: 3px solid var(--yellow); }
.trace { color: var(--text-faint); font-size: 10.5px; margin-top: 4px; }
.quick { display: flex; gap: 8px; padding: 0 12px 8px; }
.quick button { flex: 1; background: var(--bg-panel); border: 1px solid var(--border-strong); color: var(--text-primary); border-radius: 8px; padding: 7px 0; font-size: 12.5px; }
.bar { display: flex; gap: 8px; padding: 0 12px 10px; }
input { flex: 1; background: var(--bg-panel); border: 1px solid var(--border-strong); color: var(--text-primary); border-radius: 10px; padding: 10px 12px; font-size: 13px; }
.pri { background: var(--brand); border: 1px solid var(--brand); color: #141414; font-weight: 600; border-radius: 10px; padding: 0 16px; }
.hint { padding: 0 16px 14px; color: var(--text-faint); font-size: 11px; line-height: 1.7; }
.hint a { color: var(--brand); cursor: pointer; }
.hint a.dis { color: var(--text-faint); cursor: default; }
</style>
