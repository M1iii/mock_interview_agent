<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listSessions } from '../api/client'
import type { SessionMeta } from '../api/types'

const router = useRouter()
const route = useRoute()

const sessions = ref<SessionMeta[]>([])
const loading = ref(false)

const recentSessions = computed(() => {
  return sessions.value
    .filter((s) => s.status === 'ongoing')
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    )
    .slice(0, 3)
})

interface NavItem {
  name: string
  label: string
  icon: string
  path: string
}

const navItems: NavItem[] = [
  {
    name: 'home',
    label: '面试对话',
    icon:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    path: '/',
  },
  {
    name: 'resumes',
    label: '简历管理',
    icon:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    path: '/resumes',
  },
  {
    name: 'knowledge',
    label: '知识库',
    icon:
      '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
    path: '/knowledge',
  },
]

const activeName = computed(() => {
  const path = route.path
  if (path.startsWith('/chat') || path.startsWith('/report') || path === '/') return 'home'
  if (path.startsWith('/resumes')) return 'resumes'
  if (path.startsWith('/knowledge')) return 'knowledge'
  if (path.startsWith('/settings')) return 'settings'
  return 'home'
})

async function loadSessions() {
  try {
    sessions.value = await listSessions()
  } catch {
    sessions.value = []
  }
}

function navigate(path: string) {
  if (route.path !== path) {
    router.push(path)
  }
}

function openSession(s: SessionMeta) {
  if (s.status === 'finished') {
    router.push(`/report/${s.id}`)
  } else {
    router.push(`/chat/${s.id}`)
  }
}

function sceneLabel(scene: string): string {
  return scene === 'intern' ? '实习' : '全职'
}

onMounted(() => {
  void loadSessions()
})

// 暴露刷新方法供父组件调用
defineExpose({ loadSessions })
</script>

<template>
  <aside class="app-sidebar">
    <div class="app-logo">
      <span class="logo-badge">AI</span>
      <span class="logo-text">AI 面试官</span>
    </div>

    <nav class="app-nav">
      <button
        v-for="item in navItems"
        :key="item.name"
        class="app-nav-item"
        :class="{ active: activeName === item.name }"
        @click="navigate(item.path)"
      >
        <span class="nav-icon" v-html="item.icon"></span>
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div class="session-side">
      <div class="session-side-title">最近会话</div>
      <template v-if="recentSessions.length > 0">
        <div
          v-for="s in recentSessions"
          :key="s.id"
          class="session-side-item"
          :class="{ active: route.params.id === s.id }"
          @click="openSession(s)"
        >
          <span class="ss-dot" :class="s.status"></span>
          <span class="ss-title" :title="s.title">{{ s.title }}</span>
          <span class="ss-meta">{{ sceneLabel(s.scene) }}</span>
        </div>
      </template>
      <div v-else class="session-empty">暂无进行中的会话</div>
    </div>

    <div class="sidebar-bottom">
      <button
        class="app-nav-item settings-item"
        :class="{ active: activeName === 'settings' }"
        @click="navigate('/settings')"
      >
        <span class="nav-icon">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
          </svg>
        </span>
        <span>环境配置</span>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  width: 232px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--soft-overlay);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  backdrop-filter: blur(24px) saturate(180%);
  border-right: 1px solid oklch(100% 0 0 / 0.5);
  box-shadow: 2px 0 20px oklch(55% 0.15 280 / 0.08);
  position: relative;
  z-index: 10;
  height: 100vh;
  position: sticky;
  top: 0;
}

.app-logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px 20px 16px;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: -0.01em;
  color: var(--soft-ink);
}

.logo-badge {
  width: 28px;
  height: 28px;
  border-radius: 9px;
  background: var(--soft-accent-grad);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 700;
  box-shadow: var(--soft-shadow-sm);
  flex-shrink: 0;
}

.logo-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.app-nav {
  padding: 6px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.app-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--soft-ink);
  background: transparent;
  text-align: left;
  width: 100%;
  border: none;
  transition: all var(--transition-fast);
  font-weight: 500;
}

.app-nav-item:hover {
  background: oklch(70% 0.2 280 / 0.1);
  color: var(--soft-ink);
}

.app-nav-item.active {
  background: var(--soft-accent-grad);
  color: #fff;
  font-weight: 600;
  box-shadow: var(--soft-shadow-sm);
}

.nav-icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.nav-icon :deep(svg) {
  width: 16px;
  height: 16px;
}

.session-side {
  padding: 12px 12px 0;
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.session-side-title {
  font-size: 11px;
  color: var(--soft-faint);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 4px 10px 8px;
}

.session-side-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  cursor: pointer;
  font-size: 12.5px;
  color: var(--soft-ink);
  transition: background var(--transition-fast);
  margin-bottom: 2px;
}

.session-side-item:hover {
  background: oklch(70% 0.2 280 / 0.1);
}

.session-side-item.active {
  background: oklch(70% 0.2 280 / 0.15);
  font-weight: 500;
}

.ss-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--soft-accent);
}

.ss-dot.ongoing {
  background: var(--soft-accent);
}

.ss-dot.finished {
  background: var(--soft-faint);
}

.ss-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.ss-meta {
  font-size: 11px;
  color: var(--soft-faint);
  flex-shrink: 0;
}

.session-empty {
  font-size: 12px;
  color: var(--soft-faint);
  padding: 8px 10px;
  font-style: italic;
}

.sidebar-bottom {
  margin-top: auto;
  padding: 8px 12px 12px;
  border-top: 1px solid var(--soft-hairline);
}

.settings-item {
  width: 100%;
}
</style>
