<script setup lang="ts">
/**
 * 页面顶栏：左边标题，右边字号挡位 + 作者信息（上下两行，点 @后面的名字 跳到对应主页）。
 *
 * 两个页面都用它，所以标题和这段引流信息只在这里维护一份。
 * 标题按作者信息那两行的**中线**垂直居中；整条顶栏的上下留白压得比较小，
 * 这样两行信息塞进来以后总高度和以前一行时差不多，标题看起来也不会往下掉。
 *
 * 链接特意用 target="_blank"：打包版窗口是 Edge 的「应用模式」——没有地址栏、
 * 没有后退按钮，直接在本窗口里跳走用户就回不来了；新窗口打开会交给系统默认浏览器。
 */
import { storeToRefs } from 'pinia'
import { UI_SCALES, useBuildStore } from '@/stores/build'

const store = useBuildStore()
const { uiScale } = storeToRefs(store)
const { setUiScale } = store

const LINKS = [
  { site: 'bilibili', name: '@山而shaner_', url: 'https://space.bilibili.com/7658355' },
  { site: '小黑盒', name: '@蓝云_', url: 'https://xiaoheihe.cn/app/user/profile/63676601' },
  { site: 'github', name: '求star(●`◡`●)', url: 'https://github.com/BlueWhiteCloud/nightreign-relic-build-tool' },
]
</script>

<template>
  <div class="title-bar">
    <div class="title-main">
      <img class="title-logo" src="/logo.png" alt="黑夜君临遗物配置工具 logo">
      <h1>黑夜君临遗物配置工具</h1>
    </div>
    <div class="title-right">
      <!-- 整体字号挡位：选了就存下来，两个页面都跟着变 -->
      <label class="ui-scale">
        字号
        <select
          :value="String(uiScale)"
          @change="setUiScale(Number(($event.target as HTMLSelectElement).value))"
        >
          <option v-for="scale in UI_SCALES" :key="scale.value" :value="String(scale.value)">
            {{ scale.label }}
          </option>
        </select>
      </label>
      <div class="author">
        <span v-for="link in LINKS" :key="link.site">
          {{ link.site }}：<a :href="link.url" target="_blank" rel="noreferrer noopener">{{ link.name }}</a>
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.title-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 8px 20px;
  /* 吸顶：配合 #app 当滚动容器（见 style.css），滚动时一直停在窗口上方。
     底色要比原来实一点 + 背景虚化，不然内容会从半透明条底下透出来。 */
  position: sticky;
  top: 0;
  background: rgba(10, 13, 20, 0.9);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  z-index: 10;
}

.title-main {
  display: flex;
  align-items: center;
  gap: 12px;
}

h1 {
  margin: 0;
  font-size: 26px;
  font-family: var(--title-font);
  color: var(--primary);
  text-shadow: 0 0 15px rgba(114, 161, 229, 0.4);
  letter-spacing: 2px;
}

.title-logo {
  height: 36px;
  width: auto;
  filter: drop-shadow(0 0 8px rgba(114, 161, 229, 0.3));
}

.title-right {
  display: flex;
  align-items: center;
  gap: 24px;
}

.ui-scale {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--muted);
  font-family: var(--ui-font);
}

.ui-scale select {
  background: rgba(30, 45, 70, 0.6);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 8px;
  color: var(--text);
}

.author {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--muted);
  font-family: var(--ui-font);
}

.author a {
  color: var(--primary);
  /* opacity: 0.8; */
  /* transition: opacity 0.2s; */
}

.author a:hover {
  /* opacity: 1; */
  text-decoration: underline;
}
</style>
