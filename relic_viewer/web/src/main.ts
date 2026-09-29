import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import { tip } from './utils/tip'
import './style.css'

// v-tip：词条名被省略号截断时，鼠标停一会儿弹气泡显示全文（见 utils/tip.ts）
createApp(App).use(pinia).use(router).directive('tip', tip).mount('#app')

// 心跳：打包版靠它判断「网页还开着」——网页关掉后后端会自己退出，不留看不见的后台进程。
// 开发态（vite）下这个接口也有，什么都不影响；失败了也不打扰用户。
setInterval(() => {
  fetch(`${import.meta.env.VITE_API_BASE_URL}/ping`).catch(() => {})
}, 10000)
