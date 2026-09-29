import { createPinia } from 'pinia'

/**
 * 全局状态容器（跨页面共享的数据放这里）。
 *
 * 加新 store 的写法：在 src/stores 下新建文件，例如
 *
 *   // src/stores/build.ts
 *   import { defineStore } from 'pinia'
 *   import { ref } from 'vue'
 *
 *   export const useBuildStore = defineStore('build', () => {
 *     const heroType = ref<number | null>(null)
 *     const sort = ref('综合得分')
 *     return { heroType, sort }
 *   })
 *
 * 组件里 `const build = useBuildStore()` 即可读取 / 修改。
 */
export const pinia = createPinia()
