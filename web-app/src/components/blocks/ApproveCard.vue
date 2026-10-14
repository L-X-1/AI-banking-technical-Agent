<script setup lang="ts">
/** ApproveCard（doc 04 §4.6 ★核心交互）：黄/红审批卡；数据一律服务端 payload 原样渲染。
 *  倒计时双轨：expires_in_sec 本地递减仅作显示，归零置灰；最终定性以服务端消息为准。
 *  键盘：↑/↓ 切换高亮，Enter 提交，Esc = 取消。提交后降透明 + 「已确认/已取消」，选项区移除（防重复）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAppStore } from '../../stores/app'
import type { ConfirmCardPayload } from '../../types/protocol'

const props = defineProps<{ card: ConfirmCardPayload; handled?: 'approved' | 'rejected' }>()
const emit = defineEmits<{ (e: 'confirm', approved: boolean): void }>()

const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')

const left = ref(props.card.expires_in_sec)
let timer: number | null = null
onMounted(() => { timer = window.setInterval(() => { if (left.value > 0) left.value -= 1 }, 1000) })
onBeforeUnmount(() => { if (timer !== null) clearInterval(timer) })

const expired = computed(() => left.value <= 0 && !props.handled)
const done = computed(() => !!props.handled)
const sel = ref(0)                                   // 0 确认 · 1 取消

const mmss = computed(() => {
  const s = Math.max(0, left.value)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})
const isAmount = (label: string) => label.includes('金额')

function submit(approved: boolean) {
  if (done.value || expired.value) return
  emit('confirm', approved)
}

function onKey(e: KeyboardEvent) {
  if (done.value || expired.value) return
  if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); sel.value = sel.value === 0 ? 1 : 0 }
  else if (e.key === 'Enter') { e.preventDefault(); submit(sel.value === 0) }
  else if (e.key === 'Escape') { e.preventDefault(); submit(false) }
}
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="approve" :class="[card.risk_level, { butler, done, expired }]">
    <div class="hd">
      <span class="ttl">{{ card.title || '需要您的确认' }}</span>
      <span class="pill" :class="card.risk_level">
        {{ card.risk_level === 'red' ? '红色高危 · 需 MFA' : '黄色操作' }}
      </span>
      <span class="cd mono" v-if="!done">
        <b>{{ mmss }}</b> {{ expired ? '已过期' : '后自动取消' }}
      </span>
      <span class="cd done-tag" v-else>{{ handled === 'approved' ? '已确认 ✓' : '已取消' }}</span>
    </div>

    <div class="rows">
      <div class="r" v-for="d in card.detail" :key="d.label">
        <span>{{ d.label }}</span>
        <b :class="{ amt: isAmount(d.label) }" class="mono">{{ d.value }}</b>
      </div>
      <div class="r">
        <span>后果</span><span class="consequence">{{ card.consequence }}</span>
      </div>
    </div>

    <div class="reasons" v-if="card.upgrade_reasons && card.upgrade_reasons.length">
      ⚠ {{ card.upgrade_reasons.join('；') }}
    </div>

    <div class="opts" v-if="!done && !expired">
      <div v-if="butler" class="btns">
        <button class="pri" @click="submit(true)">确认</button>
        <button class="gho" @click="submit(false)">取消</button>
      </div>
      <template v-else>
        <div :class="{ sel: sel === 0 }" @mouseenter="sel = 0" @click="submit(true)">1. 确认</div>
        <div :class="{ sel: sel === 1 }" @mouseenter="sel = 1" @click="submit(false)">2. 取消</div>
      </template>
    </div>
    <div class="expired-tip" v-if="expired">确认已超时，本条操作已自动取消（以服务端为准）</div>
  </div>
</template>

<style scoped>
.approve {
  border: 1px solid var(--border-strong); border-left: 3px solid var(--yellow);
  border-radius: var(--r-card); background: var(--bg-panel); padding: 12px 14px;
  transition: opacity var(--motion);
}
.approve.red { border-left-color: var(--red); }
.approve.butler { border-radius: var(--bt-radius-card); border-color: var(--bt-card-border); margin-left: 32px; max-width: 580px; padding: 16px 18px; }
.approve.done { opacity: .55; }
.approve.expired { filter: grayscale(.4); opacity: .7; }
.hd { display: flex; align-items: center; gap: 8px; color: var(--text-primary); font-weight: 600; }
.pill { font-size: 10.5px; padding: 2px 9px; border-radius: 999px; border: 1px solid; font-weight: 400; }
.pill.yellow { color: var(--yellow); border-color: var(--bt-pill-y); }
.pill.red { color: var(--red); border-color: var(--bt-pill-r); }
.cd { margin-left: auto; color: var(--text-muted); font-size: 11.5px; }
.cd b { color: var(--yellow); }
.done-tag { color: var(--green); }
.rows { margin: 12px 0 4px; }
.r { display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; color: var(--text-muted); border-bottom: 1px dashed var(--bg-hover); }
.r:last-child { border-bottom: none; }
.r b { color: var(--text-primary); font-weight: 500; }
.amt { color: var(--yellow); }
.approve.red .amt { color: var(--red); }
.consequence { color: var(--text-secondary); font-size: 12.5px; }
.reasons { color: var(--yellow); font-size: 11.5px; margin-top: 6px; line-height: 1.7; }
.opts { margin-top: 10px; color: var(--text-muted); }
.opts .sel { color: var(--text-primary); }
.opts .sel::before { content: "❯ "; color: var(--yellow); }
.opts > div { padding: 1.5px 0; cursor: pointer; }
.btns { display: flex; gap: 10px; }
.btns button { flex: 1; text-align: center; padding: 9px 0; border-radius: 999px; font-size: 13px; }
.btns .pri { background: var(--brand); border: 1px solid var(--brand); color: #1a1a1a; font-weight: 600; }
.btns .gho { background: transparent; border: 1px solid var(--border-strong); color: var(--text-muted); }
.expired-tip { color: var(--text-faint); font-size: 11.5px; margin-top: 10px; }
</style>
