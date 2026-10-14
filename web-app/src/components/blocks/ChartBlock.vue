<script setup lang="ts">
/** ChartBlock（doc 04 §4.9）：ECharts 图表卡（消费分类饼图 / 推荐对比柱图 / 订阅清单 / 异常列表）。
 *  数据一律来自服务端 chart 消息 payload（前端不做任何金融计算）。 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ chart: Record<string, unknown> }>()

const kind = computed(() => String(props.chart.kind || 'pie'))
const series = computed(() => (props.chart.series as { name: string; value: number }[]) || [])
const items = computed(() => (props.chart.items as Record<string, unknown>[]) || [])

const PALETTE = ['#d4af37', '#4ade80', '#60a5fa', '#fbbf24', '#a78bfa', '#f87171']

const option = computed(() => {
  if (kind.value === 'bar') {
    return {
      grid: { left: 90, right: 24, top: 16, bottom: 16 },
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'value', axisLabel: { color: '#8b8b90' }, splitLine: { lineStyle: { color: '#26262a' } } },
      yAxis: { type: 'category', data: series.value.map((s) => s.name), axisLabel: { color: '#8b8b90' } },
      series: [{ type: 'bar', data: series.value.map((s) => s.value), itemStyle: { color: '#d4af37' }, barWidth: 14 }],
    }
  }
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: '#8b8b90', fontSize: 11 } },
    color: PALETTE,
    series: [{
      type: 'pie', radius: ['42%', '68%'], center: ['50%', '44%'],
      label: { color: '#d4d4d8', fontSize: 11 },
      data: series.value,
    }],
  }
})
</script>

<template>
  <div class="chart-card">
    <div class="hd">
      {{ chart.title || '数据图表' }}
      <span class="sub" v-if="chart.total">共 ¥{{ Number(chart.total).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
    </div>

    <VChart v-if="series.length && kind !== 'subs' && kind !== 'anomalies'" class="canvas" :option="option" autoresize />

    <div v-if="kind === 'subs'" class="subs">
      <div v-for="(it, i) in items" :key="i" class="sub-row">
        <span>{{ it.merchant }}</span>
        <span class="mono">¥{{ Number(it.amount).toFixed(2) }}/{{ it.cycle || '月' }}</span>
        <span class="new" v-if="it.is_new">遗忘候选</span>
        <span class="occ" v-if="it.occurrences">×{{ it.occurrences }}</span>
      </div>
    </div>

    <div v-if="kind === 'anomalies'" class="anoms">
      <div v-for="(it, i) in items" :key="i" class="anom">
        <span class="mark">⚠</span>
        <span class="when mono">{{ String(it.created_at).slice(5, 16) }}</span>
        <span class="who">{{ it.counterparty }}</span>
        <span class="mono amt">¥{{ Number(it.amount).toLocaleString('zh-CN', { minimumFractionDigits: 2 }) }}</span>
        <span class="why">{{ (it.reasons as string[] || []).join('；') }}</span>
      </div>
      <div class="empty" v-if="!items.length">未检测到异常支出</div>
    </div>
  </div>
</template>

<style scoped>
.chart-card { border: 1px solid var(--border); border-radius: var(--r-card); background: var(--bg-panel); padding: 12px 14px; }
.hd { color: var(--text-primary); font-size: 13px; font-weight: 600; display: flex; justify-content: space-between; }
.sub { color: var(--brand); font-family: var(--font-mono); font-size: 12.5px; font-weight: 400; }
.canvas { height: 220px; margin-top: 8px; }
.subs { margin-top: 8px; }
.sub-row { display: flex; gap: 12px; align-items: center; padding: 6px 0; border-bottom: 1px dashed var(--bg-hover); color: var(--text-secondary); font-size: 12.5px; }
.sub-row:last-child { border-bottom: none; }
.new { color: var(--yellow); font-size: 11px; border: 1px solid var(--bt-pill-y); border-radius: 999px; padding: 0 8px; }
.occ { margin-left: auto; color: var(--text-faint); font-size: 11px; }
.anoms { margin-top: 8px; }
.anom { display: flex; gap: 10px; align-items: baseline; padding: 5px 0; font-size: 12.5px; color: var(--text-secondary); }
.mark { color: var(--yellow); }
.when { color: var(--text-muted); font-size: 11.5px; }
.who { color: var(--text-primary); }
.amt { color: var(--red); }
.why { color: var(--text-faint); font-size: 11px; }
.empty { color: var(--text-faint); font-size: 12px; padding: 6px 0; }
</style>
