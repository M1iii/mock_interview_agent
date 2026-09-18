<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import Sidebar from './components/Sidebar.vue'

const route = useRoute()
const sidebarRef = ref<InstanceType<typeof Sidebar> | null>(null)

// 对话页和报告页是否为独立布局（无侧边栏，全屏沉浸式）
const isFullscreen = computed(() => {
  return route.path.startsWith('/chat/') || route.path.startsWith('/report/')
})

// 路由变化时刷新侧边栏会话列表
watch(
  () => route.path,
  () => {
    if (sidebarRef.value) {
      void sidebarRef.value.loadSessions()
    }
  },
)
</script>

<template>
  <!-- 全屏模式：对话页 / 报告页，保持原有布局 -->
  <RouterView v-if="isFullscreen" />

  <!-- 侧边栏模式：其余页面 -->
  <div v-else class="app-layout">
    <Sidebar ref="sidebarRef" />
    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<style>
.app-layout {
  display: flex;
  min-height: 100vh;
  position: relative;
  z-index: 1;
}

.app-main {
  flex: 1;
  min-width: 0;
  overflow-x: hidden;
}

/* 调整非全屏页面的 page 容器 padding 和 max-width */
.app-main .page {
  padding: 32px 40px;
  max-width: 960px;
}
</style>
