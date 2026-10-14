/** 全局 UI 状态（doc 04 §6）：抽屉 / 短信面板 / 双层模式（v2.2 §11） */
import { defineStore } from 'pinia'

export type TraceTab = 'dag' | 'decision' | 'audit'
export type ViewMode = 'butler' | 'perspective'

const MODE_KEY = 'zy_view_mode'

export const useAppStore = defineStore('app', {
  state: () => ({
    traceDrawerOpen: false,
    traceDrawerTab: 'dag' as TraceTab,
    smsPanelVisible: false,
    viewMode: (localStorage.getItem(MODE_KEY) as ViewMode) || 'butler',
    sidebarOpen: false,
    /** 大厅是否可见（空会话直达；侧栏「◈ 服务大厅」可重返） */
    hallRequested: false,
  }),
  actions: {
    /** Shift+Tab 切换双层模式（两模式共享同一消息流与状态机，零协议差异） */
    toggleMode() {
      this.viewMode = this.viewMode === 'butler' ? 'perspective' : 'butler'
      localStorage.setItem(MODE_KEY, this.viewMode)
    },
    openTrace(tab: TraceTab = 'dag') {
      this.traceDrawerTab = tab
      this.traceDrawerOpen = true
    },
    closeTrace() { this.traceDrawerOpen = false },
    showSms() { this.smsPanelVisible = true },
    hideSms() { this.smsPanelVisible = false },
  },
})
