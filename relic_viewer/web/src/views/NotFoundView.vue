<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <section class="not-found">
    <h1>404</h1>
    <p>这个地址没有对应的页面。</p>
    <RouterLink to="/">回首页</RouterLink>
  </section>
</template>

<style scoped>
.not-found {
  padding: 48px 24px;
  text-align: center;
}

h1 {
  margin: 0 0 8px;
}
</style>
