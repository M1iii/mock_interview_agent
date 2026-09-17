<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createSession, deleteSession, listKnowledgeBases, listSessions } from '../api/client'
import type { KnowledgeBase, Scene, SessionMeta, SessionStatus } from '../api/types'

const router = useRouter()

type SessionFilter = 'all' | SessionStatus

const sessions = ref<SessionMeta[]>([])
const loading = ref(true)
const filter = ref<SessionFilter>('all')

const filters: { value: SessionFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'ongoing', label: '进行中' },
  { value: 'finished', label: '已完成' },
]

const filteredSessions = computed(() =>
  filter.value === 'all'
    ? sessions.value
    : sessions.value.filter((s) => s.status === filter.value),
)

const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const kbs = ref<KnowledgeBase[]>([])
const form = reactive({
  scene: 'intern' as Scene,
  question_count: 10,
  skip_opening: false,
  kb_id: '',
})

async function load() {
  loading.value = true
  try {
    sessions.value = await listSessions()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await load()
  try {
    kbs.value = await listKnowledgeBases()
  } catch {
    kbs.value = []
  }
})

function openCreate() {
  createError.value = ''
  form.scene = 'intern'
  form.question_count = 10
  form.skip_opening = false
  form.kb_id = ''
  showCreate.value = true
}

async function handleCreate() {
  creating.value = true
  createError.value = ''
  try {
    const meta = await createSession({
      scene: form.scene,
      question_count: form.question_count,
      skip_opening: form.skip_opening,
      kb_id: form.kb_id || undefined,
    })
    showCreate.value = false
    router.push(`/chat/${meta.id}`)
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    creating.value = false
  }
}

async function handleDelete(e: MouseEvent, id: string) {
  e.stopPropagation()
  if (!window.confirm('删除后不可恢复，确定删除该会话？')) return
  await deleteSession(id)
  await load()
}

function openSession(s: SessionMeta) {
  if (s.status === 'finished') {
    router.push(`/report/${s.id}`)
  } else {
    router.push(`/chat/${s.id}`)
  }
}

function sceneLabel(scene: Scene): string {
  return scene === 'intern' ? '实习' : '全职'
}

function statusLabel(status: SessionMeta['status']): string {
  return status === 'finished' ? '已完成' : '进行中'
}

function progressText(s: SessionMeta): string {
  if (s.status === 'finished') return `${s.question_count} 题已答完`
  const cur = Math.min((s.question_index ?? 0) + 1, s.question_count)
  return `第 ${cur} / ${s.question_count} 题`
}
</script>

<template>
  <div class="page home">
    <header class="home-header">
      <div class="home-title">
        <div class="logo-badge">面</div>
        <div>
          <h1 class="page-title">AI 面试官</h1>
          <p class="page-sub">模拟面试 · 实时评估 · 报告导出</p>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn" @click="router.push('/knowledge')">知识库</button>
        <button class="btn" @click="router.push('/settings')">环境配置</button>
        <button class="btn btn-primary" @click="openCreate">新建面试</button>
      </div>
    </header>

    <div v-if="loading" class="state-hint">加载会话中…</div>

    <div v-else-if="sessions.length === 0" class="state-hint empty-card card">
      <p class="empty-title">还没有面试会话</p>
      <p class="empty-sub">创建一场面试，开始练习吧</p>
      <button class="btn btn-primary" @click="openCreate">开始第一次面试</button>
    </div>

    <div v-else>
      <div class="filter-row">
        <button
          v-for="f in filters"
          :key="f.value"
          class="filter-chip"
          :class="{ active: filter === f.value }"
          @click="filter = f.value"
        >
          {{ f.label }}
        </button>
      </div>

      <div v-if="filteredSessions.length === 0" class="state-hint">该分类下暂无会话</div>

      <div v-else class="session-grid">
        <div
          v-for="s in filteredSessions"
          :key="s.id"
          class="card session-card"
          @click="openSession(s)"
        >
          <div class="session-top">
            <span class="scene-tag" :class="s.scene">{{ sceneLabel(s.scene) }}</span>
            <span class="status-tag" :class="s.status">{{ statusLabel(s.status) }}</span>
            <button class="btn-ghost delete-btn" title="删除会话" @click="handleDelete($event, s.id)">
              删除
            </button>
          </div>
          <h3 class="session-title">{{ s.title }}</h3>
          <div class="session-meta">
            <span>{{ s.message_count ?? 0 }} 条消息</span>
            <span>{{ progressText(s) }}</span>
            <span>{{ new Date(s.created_at).toLocaleString('zh-CN') }}</span>
          </div>
          <div class="session-action">
            <button class="btn session-btn" @click.stop="openSession(s)">
              {{ s.status === 'finished' ? '查看报告' : '继续面试' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="card modal">
        <h2 class="modal-title">新建面试</h2>

        <div class="field">
          <span class="label">面试场景</span>
          <div class="scene-toggle">
            <button
              type="button"
              class="btn"
              :class="{ 'btn-primary': form.scene === 'intern' }"
              @click="form.scene = 'intern'"
            >
              实习
            </button>
            <button
              type="button"
              class="btn"
              :class="{ 'btn-primary': form.scene === 'fulltime' }"
              @click="form.scene = 'fulltime'"
            >
              全职
            </button>
          </div>
          <p class="field-hint">
            {{ form.scene === 'intern' ? '以基础概念、项目介绍为主，不深挖底层原理' : '覆盖原理、系统设计、边界条件' }}
          </p>
        </div>

        <div class="field">
          <label class="label" for="q-count">题目数量（5–30）</label>
          <input
            id="q-count"
            v-model.number="form.question_count"
            class="input"
            type="number"
            min="5"
            max="30"
          />
        </div>

        <div class="field">
          <label class="label" for="kb-select">关联知识库（可选）</label>
          <select id="kb-select" v-model="form.kb_id" class="input">
            <option value="">不关联（通用出题）</option>
            <option v-for="kb in kbs" :key="kb.id" :value="kb.id">
              {{ kb.name }}（{{ kb.files.length }} 个文件）
            </option>
          </select>
          <p class="field-hint">关联后出题将基于知识库内容，并标注引用来源</p>
        </div>

        <div class="field">
          <label class="switch-row">
            <input v-model="form.skip_opening" type="checkbox" />
            <span>跳过开场白，直接进入第一题</span>
          </label>
        </div>

        <p v-if="createError" class="error">{{ createError }}</p>

        <div class="modal-actions">
          <button class="btn" :disabled="creating" @click="showCreate = false">取消</button>
          <button class="btn btn-primary" :disabled="creating" @click="handleCreate">
            {{ creating ? '创建中…' : '开始面试' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
}

.home-title {
  display: flex;
  align-items: center;
  gap: 14px;
}

.logo-badge {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  background: linear-gradient(135deg, var(--primary), #a78bfa);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-md);
}

.header-actions {
  display: flex;
  gap: 10px;
}

.state-hint {
  text-align: center;
  color: var(--text-2);
  padding: 40px 0;
}

.empty-card {
  padding: 48px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-title {
  font-size: 18px;
  font-weight: 600;
}

.empty-sub {
  font-size: 14px;
  color: var(--text-2);
  margin-bottom: 12px;
}

.filter-row {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.filter-chip {
  font-size: 13px;
  padding: 6px 18px;
  border-radius: var(--r-full);
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  transition:
    background 0.2s var(--ease-out),
    color 0.2s var(--ease-out),
    border-color 0.2s var(--ease-out);
}

.filter-chip:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.filter-chip.active {
  background: var(--primary);
  border-color: var(--primary);
  color: #fff;
}

.session-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.session-card {
  padding: 20px;
  cursor: pointer;
  transition:
    transform 0.2s var(--ease-out),
    box-shadow 0.2s var(--ease-out);
}

.session-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
}

.session-top {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.scene-tag,
.status-tag {
  font-size: 12px;
  font-weight: 500;
  padding: 3px 10px;
  border-radius: var(--r-full);
}

.scene-tag.intern {
  background: var(--primary-soft);
  color: var(--primary);
}

.scene-tag.fulltime {
  background: #fef3c7;
  color: #b45309;
}

.status-tag.ongoing {
  background: #dcfce7;
  color: #15803d;
}

.status-tag.finished {
  background: #e2e8f0;
  color: #475569;
}

.delete-btn {
  margin-left: auto;
  font-size: 13px;
  color: var(--text-3);
}

.delete-btn:hover {
  color: var(--danger);
}

.session-title {
  font-size: 17px;
  font-weight: 600;
  margin-bottom: 6px;
}

.session-meta {
  display: flex;
  gap: 14px;
  font-size: 13px;
  color: var(--text-3);
  margin-bottom: 14px;
}

.session-action {
  display: flex;
  justify-content: flex-end;
}

.session-btn {
  font-size: 13px;
  padding: 7px 16px;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(42, 36, 56, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal {
  width: 400px;
  max-width: calc(100vw - 48px);
  padding: 28px;
}

.modal-title {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 20px;
}

.field {
  margin-bottom: 18px;
}

.scene-toggle {
  display: flex;
  gap: 10px;
}

.scene-toggle .btn {
  flex: 1;
}

.field-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-3);
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-1);
  cursor: pointer;
}

.switch-row input {
  width: 16px;
  height: 16px;
  accent-color: var(--primary);
}

.error {
  color: var(--danger);
  font-size: 13px;
  margin: 12px 0;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
</style>
