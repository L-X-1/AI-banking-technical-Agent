<script setup lang="ts">
/** ReceiptBlock（doc 04 §4.10）：全块 mono；trace 可跳审计回放（答辩杀手锏）；
 *  v2.2 管家模式圆角柔化（§11.2#3）。 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAppStore } from '../../stores/app'
import type { ReceiptPayload } from '../../types/protocol'

const props = defineProps<{ receipt: ReceiptPayload }>()
const router = useRouter()
const app = useAppStore()
const butler = computed(() => app.viewMode === 'butler')

const trace = computed(() => (props.receipt.trace_id || '').replace(/^tr_/, ''))
const amountText = computed(() =>
  typeof props.receipt.amount === 'number' ? `¥${props.receipt.amount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` : '')

function openAudit() {
  if (props.receipt.trace_id) router.push(`/audit/${props.receipt.trace_id}`)
}
</script>

<template>
  <div class="receipt" :class="{ butler }">
    <div class="l1">
      <span class="ok">✓</span> {{ receipt.title }}
      <span v-if="amountText" class="amt">{{ amountText }}</span>
      <span v-if="receipt.counterparty" class="cp">→ {{ receipt.counterparty }}</span>
    </div>
    <div class="l2">
      <span v-for="d in receipt.detail" :key="d.label">{{ d.label }} {{ d.value }}</span>
    </div>
    <div class="l3" v-if="trace">
      <span class="mono">trace #{{ trace }}</span>
      <a class="link" @click="openAudit">[回放]</a>
    </div>
  </div>
</template>

<style scoped>
.receipt {
  border: 1px solid var(--border); border-left: 3px solid var(--green);
  border-radius: var(--r-card); background: var(--bg-panel); padding: 10px 14px;
  font-family: var(--font-mono); font-size: 12.5px; line-height: 1.9;
}
.receipt.butler { border-radius: var(--bt-radius-card); border-color: var(--bt-card-border); margin-left: 32px; font-family: var(--font-ui); }
.ok { color: var(--green); }
.amt { color: var(--brand); margin-left: 8px; }
.cp { color: var(--text-secondary); margin-left: 8px; }
.l2 { color: var(--text-muted); display: flex; gap: 14px; flex-wrap: wrap; }
.l3 { color: var(--text-faint); display: flex; gap: 10px; }
.link { color: var(--brand); cursor: pointer; }
</style>
