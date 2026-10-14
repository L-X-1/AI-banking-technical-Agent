/**
 * 场景静态配置（v2.2 · 四组服务宫格数据源）
 * 依据：doc 01 §1.2 六场景 / doc 06 §1 场景合并（4 组 7 卡，#5 一卡双归） / doc 03 §9 种子数据
 * 约束：
 *  - 示例指令必须命中种子数据（两个李磊、凌晨 ¥4,999 异常、¥68/月 遗忘订阅、
 *    稳健添利 30 天 R2、爱人王芳生日），保证"点下去一定演得出来"；
 *  - 本文件为前端唯一示例来源（大厅卡片 + ChatInput 占位轮播），不走服务端/LLM，杜绝篡改；
 *  - 每卡携带赛题编号 `no`（徽标 #n），与 doc 01 §1.2 一一对应，评委可指认。
 */

export type RiskLevel = 'green' | 'yellow' | 'red'

export interface RiskTag {
  level: RiskLevel
  label: string
}

export type GroupId = 'A' | 'B' | 'C' | 'D'

export interface Scenario {
  id: string
  /** 赛题场景编号（doc 01 §1.2，大厅徽标 #n 的数据源） */
  no: 1 | 2 | 3 | 4 | 5 | 6
  groupId: GroupId
  icon: string
  name: string
  desc: string
  riskTags: RiskTag[]
  /** 示例指令（点击 = 以该文本上行 user_message，走完整安全链路） */
  examples: string[]
  /** 演示主线标记（金色描边 + ⭐ 标） */
  star?: boolean
}

export interface ScenarioGroup {
  id: GroupId
  name: string
  tagline: string
}

/** 四组分区（doc 06 §1.2/§1.4） */
export const SCENARIO_GROUPS: ScenarioGroup[] = [
  { id: 'A', name: '资金办理', tagline: '把钱动起来：转账 · 理财' },
  { id: 'B', name: '洞察分析', tagline: '把钱看明白：账单 · 订阅识别' },
  { id: 'C', name: '卡片与订阅管理', tagline: '把长期契约管起来' },
  { id: 'D', name: '智能联动', tagline: '一句话，自动办一串事' },
]

/** 大厅渲染组序：D 组置顶（演示主线第一眼，doc 06 §1.4）；A/B/C 顺排 */
export const HALL_GROUP_ORDER: GroupId[] = ['D', 'A', 'B', 'C']

export const SCENARIOS: Scenario[] = [
  // ── 组 A 资金办理 ─────────────────────────────
  {
    id: 'transfer',
    no: 1,
    groupId: 'A',
    icon: '💸',
    name: '智能转账',
    desc: '人名/手机号/备注转账 · 定时转账 · AA 拆分',
    riskTags: [
      { level: 'yellow', label: '需确认' },
      { level: 'red', label: '超限升 MFA' },
    ],
    // 种子：两个「李磊」（尾号 3821 同事 / 7719 同学）→ 命中同名消歧
    examples: ['给李磊转 500，备注生日快乐', '这顿 300 我们仨 AA'],
  },
  {
    id: 'wealth',
    no: 3,
    groupId: 'A',
    icon: '📈',
    name: '理财服务',
    desc: '产品推荐与对比 · 风险评估 · 申购赎回',
    riskTags: [
      { level: 'green', label: '查询自动执行' },
      { level: 'red', label: '申购需 MFA' },
    ],
    // 种子：稳健添利 30 天（R2，年化 2.8%）；用户风险等级 R2 → 申购 R4 触发拒绝演示
    examples: ['帮我推荐稳健的理财', '申购 1 万元那只股票型基金'],
  },
  // ── 组 B 洞察分析 ─────────────────────────────
  {
    id: 'billing',
    no: 2,
    groupId: 'B',
    icon: '📊',
    name: '账单分析',
    desc: '消费分类统计 · 异常交易识别 · 月度报告',
    riskTags: [{ level: 'green', label: '自动执行' }],
    // 种子：09-14 03:22 数码商城 ¥4,999 异常交易
    examples: ['上个月钱花哪了', '帮我查查有没有异常交易'],
  },
  {
    id: 'subscription-detect',
    no: 5,
    groupId: 'B',
    icon: '🔍',
    name: '订阅扣费识别',
    desc: '自动识别周期性扣费 · 发现遗忘订阅',
    riskTags: [{ level: 'green', label: '自动执行' }],
    // 种子：¥68/月 云盘订阅（遗忘）、¥25/月 视频会员
    examples: ['我有哪些自动扣费'],
  },
  // ── 组 C 卡片与订阅管理 ────────────────────────
  {
    id: 'card',
    no: 4,
    groupId: 'C',
    icon: '💳',
    name: '卡片管理',
    desc: '虚拟卡申请 · 额度调整 · 交易限制 · 挂失',
    riskTags: [
      { level: 'yellow', label: '申请需确认' },
      { level: 'red', label: '挂失需 MFA' },
    ],
    examples: ['帮我申请一张虚拟卡', '卡好像被盗刷了，立即挂失'],
  },
  {
    id: 'subscription-manage',
    no: 5,
    groupId: 'C',
    icon: '🔁',
    name: '订阅代扣管理',
    desc: '续费提醒 · 一键取消',
    riskTags: [{ level: 'yellow', label: '取消需确认' }],
    examples: ['把不用的订阅都取消掉'],
  },
  // ── 组 D 智能联动（演示主线）───────────────────
  {
    id: 'orchestration',
    no: 6,
    groupId: 'D',
    icon: '🎂',
    name: '跨场景联动',
    desc: '一句话触发多步任务编排 · 定时执行 · 到期通知',
    riskTags: [{ level: 'yellow', label: '按子操作分级' }],
    // 种子：爱人王芳生日 10-15（演示口令按 doc 03 §9 对齐）
    examples: ['下个月 15 号是我爱人生日，帮我提前准备好'],
    star: true,
  },
]

/** ChatInput 占位轮播词（与大厅示例同源，doc 04 §4.12） */
export const PLACEHOLDER_PROMPTS: string[] = SCENARIOS.flatMap((s) => s.examples)

/** 按组取卡（大厅分区渲染用） */
export function scenariosOf(groupId: GroupId): Scenario[] {
  return SCENARIOS.filter((s) => s.groupId === groupId)
}
