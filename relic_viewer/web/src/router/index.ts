import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

// 页面都用 () => import() 懒加载：首屏只加载当前页，打包也会自动切成多个 chunk
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '首页' },
  },
  {
    // 第二页：推荐结果展示
    path: '/result',
    name: 'result',
    component: () => import('@/views/ResultView.vue'),
    meta: { title: '推荐结果' },
  },
  {
    // 兜底：没匹配上的路径都当 404，页面不会白屏
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// 切页面时顺手改浏览器标签页标题：meta.title 优先
router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title
    ? `${title} · ${import.meta.env.VITE_APP_TITLE}`
    : import.meta.env.VITE_APP_TITLE
})

export default router
