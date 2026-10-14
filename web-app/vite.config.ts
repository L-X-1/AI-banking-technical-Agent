import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器 8080（doc 06 §4.4 部署拓扑）；/api 与 /ws 反代 agent-service:8200
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 8080,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8200', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8200', ws: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
})
