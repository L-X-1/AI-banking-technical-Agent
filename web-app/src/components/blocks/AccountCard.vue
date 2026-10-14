<script setup lang="ts">
/** AccountCard（doc 04 §4.11）：余额摘要卡；金额服务端原样渲染（¥ 千分位） */
import { computed } from 'vue'
import type { DetailRow } from '../../types/protocol'

const props = defineProps<{ account: { accountName?: string; maskedNo?: string; balance?: number; available?: number; currency?: string; detail?: DetailRow[] } }>()

const fmt = (v?: number) =>
  typeof v === 'number' ? `¥${v.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` : '—'
const bal = computed(() => fmt(props.account.balance))
const avail = computed(() => fmt(props.account.available))
</script>

<template>
  <div class="acct">
    <div class="row1">
      <span class="name">{{ account.accountName || '账户' }}</span>
      <span class="no mono" v-if="account.maskedNo">尾号 {{ account.maskedNo }}</span>
    </div>
    <div class="bal mono">{{ bal }}</div>
    <div class="avail">可用余额 <span class="mono">{{ avail }}</span></div>
  </div>
</template>

<style scoped>
.acct { border: 1px solid var(--border); border-radius: var(--r-card); background: var(--bg-panel); padding: 12px 14px; }
.row1 { display: flex; justify-content: space-between; color: var(--text-muted); font-size: 12px; }
.no { color: var(--text-faint); }
.bal { color: var(--brand); font-size: 22px; font-weight: 600; margin-top: 8px; }
.avail { color: var(--text-muted); font-size: 12px; margin-top: 4px; }
</style>
