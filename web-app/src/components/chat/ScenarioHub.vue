<script setup lang="ts">
/** ScenarioHub（doc 04 §4.19 ★第一屏）：四组服务宫格（D 组置顶），#n 徽标 + 示例 chip，
 *  点击 chip = 以该文本上行（与手动输入完全同构，不另设协议、不降安全等级）。 */
import { computed } from 'vue'
import { HALL_GROUP_ORDER, SCENARIO_GROUPS, scenariosOf } from '../../config/scenarios'
import { useChatStore } from '../../stores/chat'
import { useSessionStore } from '../../stores/session'

const chat = useChatStore()
const session = useSessionStore()

const groups = computed(() =>
  HALL_GROUP_ORDER.map((id) => ({
    ...SCENARIO_GROUPS.find((g) => g.id === id)!,
    cards: scenariosOf(id),
  })))

function fire(text: string) {
  chat.userSay(text)
}
</script>

<template>
  <div class="hall">
    <div class="hi">
      <div class="t">{{ session.userName }}，晚上好。今天想办点什么？</div>
      <div class="s">点击示例卡片直接办理，或输入你的指令——所有操作都经过同一套安全裁决。</div>
    </div>

    <div v-for="g in groups" :key="g.id" class="grp">
      <div class="gt"><b>{{ g.name }}</b><span>{{ g.tagline }}</span></div>
      <div class="grid" :class="{ single: g.cards.length === 1 }">
        <div v-for="s in g.cards" :key="s.groupId + '-' + s.id" class="scn" :class="{ star: s.star }">
          <div class="t">
            <span>{{ s.icon }}</span>
            <span>{{ s.name }}</span>
            <span class="no mono">#{{ s.no }}</span>
            <span class="rk">
              <span v-for="r in s.riskTags" :key="r.label" class="pill" :class="r.level">{{ r.label }}</span>
            </span>
          </div>
          <div class="d">{{ s.desc }}</div>
          <div class="chips">
            <span v-for="e in s.examples" :key="e" class="chip" @click="fire(e)">{{ e }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hall { display: flex; flex-direction: column; gap: 6px; }
.hi { margin-bottom: 6px; }
.hi .t { color: var(--text-primary); font-size: 19px; font-weight: 600; }
.hi .s { color: var(--text-muted); font-size: 12.5px; margin-top: 4px; }
.gt { display: flex; align-items: baseline; gap: 10px; margin: 16px 0 10px; }
.gt b { color: var(--text-secondary); font-size: 13px; }
.gt span { color: var(--text-faint); font-size: 11px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.grid.single { grid-template-columns: 1fr; }
.scn { border: 1px solid var(--border); border-radius: 14px; background: var(--bg-panel); padding: 13px 15px; transition: border-color var(--motion); }
.scn:hover { border-color: var(--border-strong); }
.scn.star { border-color: rgba(212, 175, 55, .45); background: linear-gradient(180deg, rgba(212, 175, 55, .06), var(--bg-panel) 45%); }
.scn .t { display: flex; align-items: center; gap: 8px; color: var(--text-primary); font-weight: 600; font-size: 13px; flex-wrap: wrap; }
.no { font-size: 10px; color: var(--brand); border: 1px solid rgba(212, 175, 55, .4); border-radius: 999px; padding: 1px 7px; }
.rk { margin-left: auto; display: flex; gap: 6px; }
.pill { font-size: 10px; padding: 1px 8px; border-radius: 999px; border: 1px solid; font-weight: 400; }
.pill.green { color: var(--green); border-color: var(--bt-pill-g); }
.pill.yellow { color: var(--yellow); border-color: var(--bt-pill-y); }
.pill.red { color: var(--red); border-color: var(--bt-pill-r); }
.scn .d { color: var(--text-muted); font-size: 11.5px; margin: 7px 0 9px; }
.chip {
  display: inline-block; border: 1px solid var(--bt-card-border); border-radius: 999px;
  background: #181818; padding: 5px 12px; color: #c9c9ce; font-size: 12px; margin: 0 6px 6px 0; cursor: pointer;
}
.chip:hover { border-color: var(--brand); color: var(--text-primary); }
@media (max-width: 1023px) { .grid { grid-template-columns: 1fr; } }
</style>
