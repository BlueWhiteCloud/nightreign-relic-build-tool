import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'
import { tip } from './utils/tip'
import './style.css'

// 挂载时会把 #app 里的内容**整个替换掉**。index.html 的 #app 里预先写了一段
// 「正在加载界面……」的占位文案（内联样式），那是给「JS 根本没跑起来」兜底的：
// 挂载成功它就被换掉了，没跑起来它就留在页面上 —— 用户至少知道不是卡死，还知道去哪找日志。
// 所以那段文案别删；也别改成依赖外部样式表，那样表可能同样没加载。
// （它是给用户看的，别在旁边写注释讲原理 —— 页面右键「查看源代码」是能看到的。）
createApp(App).use(pinia).use(router).directive('tip', tip).mount('#app')

// 心跳：打包版靠它判断「网页还开着」——网页关掉后后端会自己退出，不留看不见的后台进程。
// 开发态（vite）下这个接口也有，什么都不影响；失败了也不打扰用户。
//
// 注意上面那发是「挂载成功后立刻打一次」：后端拿它判断页面到底画出来没有
// （挂载失败/JS 没跑起来就不会有这一发，后端据此走默认浏览器兜底，见 app.py）。
// 所以别删、别挪到挂载前面 —— 那样就分不清「页面起不来」和「页面慢」了。
const ping = () => fetch(`${import.meta.env.VITE_API_BASE_URL}/ping`).catch(() => {})
ping()
setInterval(ping, 10000)
