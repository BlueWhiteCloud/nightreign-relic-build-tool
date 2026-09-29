import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 不传第三个参数时，只加载带 VITE_ 前缀的变量，本项目够用
  const env = loadEnv(mode, process.cwd())

  return {
    plugins: [vue()],
    resolve: {
      // 用 @ 指 src，import 时不用写一长串 ../../../
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: Number(env.VITE_PORT) || 5173,
      // Python 后端起来后，前端只写 /api/xxx，dev server 帮忙转发过去（顺便免掉跨域）
      proxy: env.VITE_PROXY_TARGET
        ? { '/api': { target: env.VITE_PROXY_TARGET, changeOrigin: true } }
        : undefined,
    },
  }
})
