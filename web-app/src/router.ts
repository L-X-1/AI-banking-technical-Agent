import { createRouter, createWebHistory } from 'vue-router'

/** 路由（doc 04 §3.5）：/login 选演示用户 → /chat 主战场；/audit/:traceId 答辩回放；/im 渠道降级 */
export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', name: 'login', component: () => import('./views/LoginView.vue') },
    { path: '/chat', name: 'chat', component: () => import('./views/ChatView.vue') },
    { path: '/audit/:traceId', name: 'audit', component: () => import('./views/AuditView.vue') },
    { path: '/im', name: 'im', component: () => import('./views/MockImView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})
