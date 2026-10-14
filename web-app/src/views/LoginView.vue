<script setup lang="ts">
/** LoginView（doc 04 §3.5）：mock 登录——选演示用户（张三）+ 口令 → token 存 sessionStorage */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useSessionStore } from '../stores/session'

const router = useRouter()
const session = useSessionStore()
const pwd = ref('123456')
const err = ref('')

function login() {
  if (pwd.value.trim() !== '123456') { err.value = '演示口令：123456'; return }
  session.token = 'demo-token'
  sessionStorage.setItem('zy_token', session.token)
  router.push('/chat')
}
</script>

<template>
  <div class="login">
    <div class="card">
      <div class="brand"><i>◆</i> 智银 · AI 银行管家</div>
      <div class="sub">演示环境：选择演示用户并登录（mock）</div>
      <div class="user">
        <span class="ava">张</span>
        <span>张三 · 尾号 6688</span>
      </div>
      <input v-model="pwd" type="password" placeholder="登录口令（演示：123456）" @keydown.enter="login">
      <button class="pri" @click="login">登录</button>
      <div class="err" v-if="err">{{ err }}</div>
      <div class="hint">登录态仅用于演示；所有资金操作仍走服务端权限裁决与 MFA。</div>
    </div>
  </div>
</template>

<style scoped>
.login { height: 100%; display: flex; align-items: center; justify-content: center; }
.card {
  width: 360px; background: var(--bg-panel); border: 1px solid var(--border-strong);
  border-radius: 16px; padding: 26px 26px 22px;
}
.brand { color: var(--text-primary); font-weight: 700; font-size: 16px; }
.brand i { color: var(--brand); font-style: normal; }
.sub { color: var(--text-muted); font-size: 12px; margin: 6px 0 16px; }
.user {
  display: flex; align-items: center; gap: 10px; border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 12px; color: var(--text-secondary); font-size: 13px; margin-bottom: 12px;
}
.ava {
  width: 26px; height: 26px; border-radius: 50%; background: var(--bt-ava); color: #141414;
  font-weight: 700; font-size: 12px; display: flex; align-items: center; justify-content: center;
}
input {
  width: 100%; background: var(--bg-base); border: 1px solid var(--border-strong); color: var(--text-primary);
  border-radius: 10px; padding: 10px 12px; font-size: 13px; margin-bottom: 12px;
}
.pri { width: 100%; background: var(--brand); border: none; color: #1a1a1a; font-weight: 600; border-radius: 999px; padding: 10px 0; font-size: 13.5px; }
.err { color: var(--red); font-size: 12px; margin-top: 8px; }
.hint { color: var(--text-faint); font-size: 11px; margin-top: 12px; line-height: 1.7; }
</style>
