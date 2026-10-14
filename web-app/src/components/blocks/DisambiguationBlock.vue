<script setup lang="ts">
/** DisambiguationBlock（doc 04 §4.8）：同名/候选消歧；点击即上行结构化文本，块转单选态 */
import { ref } from 'vue'
import type { ClarifyPayload } from '../../types/protocol'

const props = defineProps<{ clarify: ClarifyPayload; answered?: boolean }>()
const emit = defineEmits<{ (e: 'pick', option: ClarifyPayload['options'][number]): void }>()

const picked = ref<string>('')
function pick(o: ClarifyPayload['options'][number]) {
  if (picked.value || props.answered) return
  picked.value = o.id
  emit('pick', o)
}
</script>

<template>
  <div class="dis">
    <div class="q">{{ clarify.question }}</div>
    <div class="opts">
      <div v-for="o in clarify.options" :key="o.id" class="opt"
           :class="{ on: picked === o.id, off: !!picked && picked !== o.id }"
           @click="pick(o)">
        <span class="primary">{{ o.primary }}</span>
        <span class="secondary" v-if="o.secondary">{{ o.secondary }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dis { border: 1px solid var(--border-strong); border-radius: var(--r-card); background: var(--bg-panel); padding: 12px 14px; }
.q { color: var(--text-primary); font-size: 13px; }
.opts { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.opt {
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px;
  display: flex; justify-content: space-between; align-items: center; cursor: pointer;
  transition: border-color var(--motion), opacity var(--motion);
}
.opt:hover { border-color: var(--border-strong); }
.opt.on { border-color: var(--brand); background: var(--bg-hover); }
.opt.off { opacity: .4; }
.primary { color: var(--text-primary); font-size: 13px; }
.secondary { color: var(--text-faint); font-size: 11.5px; }
</style>
