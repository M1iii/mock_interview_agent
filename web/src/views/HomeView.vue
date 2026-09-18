<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createSession, deleteSession, listKnowledgeBases, listResumes, listSessions } from '../api/client'
import type { InterviewType, KnowledgeBase, Resume, Scene, SessionMeta, SessionStatus } from '../api/types'

const router = useRouter()

type SessionFilter = 'all' | SessionStatus

const PAGE_SIZE = 10

const sessions = ref<SessionMeta[]>([])
const loading = ref(true)
const filter = ref<SessionFilter>('all')
const currentPage = ref(1)

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

const totalPages = computed(() => Math.max(1, Math.ceil(filteredSessions.value.length / PAGE_SIZE)))

const pagedSessions = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return filteredSessions.value.slice(start, start + PAGE_SIZE)
})

// 切换筛选时回到第一页
function setFilter(f: SessionFilter) {
  filter.value = f
  currentPage.value = 1
}

function goToPage(page: number) {
  if (page < 1 || page > totalPages.value) return
  currentPage.value = page
}

const pageNumbers = computed(() => {
  const total = totalPages.value
  if (total <= 5) return Array.from({ length: total }, (_, i) => i + 1)
  const cur = currentPage.value
  const pages: (number | 'ellipsis')[] = [1]
  if (cur > 3) pages.push('ellipsis')
  const start = Math.max(2, cur - 1)
  const end = Math.min(total - 1, cur + 1)
  for (let i = start; i <= end; i++) pages.push(i)
  if (cur < total - 2) pages.push('ellipsis')
  pages.push(total)
  return pages
})

const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const kbs = ref<KnowledgeBase[]>([])
const resumes = ref<Resume[]>([])
const form = reactive({
  scene: 'intern' as Scene,
  question_count: 10,
  skip_opening: false,
  kb_id: '',
  interview_type: 'technical' as InterviewType,
  resume_id: '',
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
  try {
    resumes.value = await listResumes()
  } catch {
    resumes.value = []
  }
})

function openCreate() {
  createError.value = ''
  form.scene = 'intern'
  form.question_count = 10
  form.skip_opening = false
  form.kb_id = ''
  form.interview_type = 'technical'
  form.resume_id = ''
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
      interview_type: form.interview_type,
      resume_id: form.resume_id || undefined,
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

function interviewTypeLabel(type?: string): string {
  return { technical: '技术面', behavioral: '行为面', comprehensive: '综合面' }[type ?? 'technical'] ?? '技术面'
}

function statusLabel(status: SessionMeta['status']): string {
  return status === 'finished' ? '已完成' : '进行中'
}

function progressText(s: SessionMeta): string {
  if (s.status === 'finished') return `${s.question_count} 题已答完`
  const cur = Math.min((s.question_index ?? 0) + 1, s.question_count)
  return `第 ${cur} / ${s.question_count} 题`
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const isToday = d.toDateString() === now.toDateString()
  if (isToday) {
    return `今天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  if (d.toDateString() === yesterday.toDateString()) {
    return `昨天 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}
</script>

<template>
  <div class="page home">
    <header class="home-header">
      <div>
        <h1 class="page-title">面试会话</h1>
        <p class="page-sub">创建一场面试，开始你的模拟练习</p>
      </div>
      <button class="btn btn-primary" @click="openCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        新建面试
      </button>
    </header>

    <div v-if="loading" class="state-hint">加载会话中…</div>

    <div v-else-if="sessions.length === 0" class="empty-wrap">
      <div class="card empty-card">
        <div class="empty-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <p class="empty-title">还没有面试会话</p>
        <p class="empty-sub">创建一场面试，开始练习吧</p>
        <button class="btn btn-primary" @click="openCreate">开始第一次面试</button>
      </div>
    </div>

    <div v-else>
      <div class="filter-row">
        <button
          v-for="f in filters"
          :key="f.value"
          class="filter-chip"
          :class="{ active: filter === f.value }"
          @click="setFilter(f.value)"
        >
          {{ f.label }}
        </button>
      </div>

      <div v-if="filteredSessions.length === 0" class="state-hint">该分类下暂无会话</div>

      <div v-else class="session-list">
        <div
          v-for="s in pagedSessions"
          :key="s.id"
          class="card session-card"
          @click="openSession(s)"
        >
          <div class="sc-main">
            <div class="sc-title">
              {{ s.title }}
              <span class="badge" :class="s.status === 'finished' ? 'badge-success' : 'badge-warning'">
                {{ statusLabel(s.status) }}
              </span>
              <span class="chip">{{ sceneLabel(s.scene) }} · {{ interviewTypeLabel(s.interview_type) }}</span>
            </div>
            <div class="sc-meta">
              <span>{{ formatDate(s.created_at) }}</span>
              <span>{{ s.message_count ?? 0 }} 条消息</span>
              <span>{{ progressText(s) }}</span>
            </div>
          </div>
          <div class="sc-actions">
            <button class="btn btn-ghost delete-btn" title="删除会话" @click.stop="handleDelete($event, s.id)">
              删除
            </button>
            <button class="btn btn-sm btn-primary" @click.stop="openSession(s)">
              {{ s.status === 'finished' ? '查看报告' : '继续面试' }}
            </button>
          </div>
        </div>

        <div v-if="totalPages > 1" class="pagination">
          <button
            class="page-btn"
            :disabled="currentPage === 1"
            @click="goToPage(currentPage - 1)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
          </button>
          <template v-for="(p, idx) in pageNumbers" :key="idx">
            <span v-if="p === 'ellipsis'" class="page-ellipsis">…</span>
            <button
              v-else
              class="page-btn"
              :class="{ active: currentPage === p }"
              @click="goToPage(p)"
            >
              {{ p }}
            </button>
          </template>
          <button
            class="page-btn"
            :disabled="currentPage === totalPages"
            @click="goToPage(currentPage + 1)"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <polyline points="9 18 15 12 9 6"/>
            </svg>
          </button>
          <span class="page-info">共 {{ filteredSessions.length }} 条</span>
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
              class="scene-chip"
              :class="{ active: form.scene === 'intern' }"
              @click="form.scene = 'intern'"
            >
              实习
            </button>
            <button
              type="button"
              class="scene-chip"
              :class="{ active: form.scene === 'fulltime' }"
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
          <span class="label">面试类型</span>
          <select v-model="form.interview_type" class="input">
            <option value="technical">技术面</option>
            <option value="behavioral">行为面</option>
            <option value="comprehensive">综合面</option>
          </select>
          <p class="field-hint">技术面偏原理与系统设计，行为面偏经历与软技能，综合面两者兼有</p>
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
          <label class="label" for="resume-select">关联简历（可选）</label>
          <select id="resume-select" v-model="form.resume_id" class="input">
            <option value="">不关联（通用出题）</option>
            <option
              v-for="r in resumes"
              :key="r.id"
              :value="r.id"
              :disabled="r.status !== 'ready'"
            >
              {{ r.file_name }}{{ r.status === 'ready' ? '' : '（解析中/失败）' }}
            </option>
          </select>
          <p class="field-hint">关联后出题将结合简历考点，混合知识库内容</p>
        </div>

        <div class="field">
          <label class="switch-row">
            <input v-model="form.skip_opening" type="checkbox" />
            <span>跳过开场白，直接进入第一题</span>
          </label>
        </div>

        <p v-if="createError" class="error">{{ createError }}</p>

        <div class="modal-actions">
          <button class="btn btn-ghost" :disabled="creating" @click="showCreate = false">取消</button>
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
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 28px;
  gap: 16px;
}

.home-header .page-title {
  margin-bottom: 2px;
}

.home-header .page-sub {
  margin-bottom: 0;
}

.empty-wrap {
  display: flex;
  justify-content: center;
  padding: 60px 0;
}

.empty-card {
  padding: 48px 56px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
  max-width: 420px;
}

.empty-icon {
  width: 64px;
  height: 64px;
  border-radius: 18px;
  background: var(--soft-accent-bg);
  color: var(--soft-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.empty-title {
  font-size: 17px;
  font-weight: 700;
  color: var(--soft-ink);
}

.empty-sub {
  font-size: 13.5px;
  color: var(--soft-muted);
  margin-bottom: 8px;
  line-height: 1.6;
}

.filter-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}

.filter-chip {
  font-size: 12.5px;
  padding: 6px 16px;
  border-radius: var(--r-full);
  border: 1px solid var(--soft-hairline);
  background: transparent;
  color: var(--soft-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-weight: 500;
}

.filter-chip:hover {
  border-color: var(--soft-accent);
  color: var(--soft-accent);
}

.filter-chip.active {
  color: var(--soft-accent);
  background: var(--soft-accent-bg);
  border-color: transparent;
  font-weight: 600;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.session-card {
  padding: 16px 20px;
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  align-items: center;
  gap: 16px;
}

.session-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--soft-shadow-md);
  border-color: oklch(100% 0 0 / 0.8);
}

.sc-main {
  flex: 1;
  min-width: 0;
}

.sc-title {
  font-weight: 600;
  font-size: 14.5px;
  color: var(--soft-ink);
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.sc-meta {
  font-size: 12.5px;
  color: var(--soft-muted);
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.sc-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.delete-btn {
  font-size: 12.5px;
  color: var(--soft-faint);
  padding: 5px 10px;
}

.delete-btn:hover {
  color: var(--danger);
}

.field {
  margin-bottom: 18px;
}

.scene-toggle {
  display: flex;
  gap: 10px;
}

.scene-chip {
  flex: 1;
  text-align: center;
  padding: 9px 14px;
  border-radius: var(--r-sm);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  border: 1px solid var(--soft-hairline);
  background: var(--soft-surface-strong);
  color: var(--soft-ink);
}

.scene-chip:hover {
  border-color: var(--soft-hairline-strong);
}

.scene-chip.active {
  background: var(--soft-accent-grad);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
  box-shadow: var(--soft-shadow-sm);
}

.field-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--soft-faint);
  line-height: 1.5;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--soft-ink);
  cursor: pointer;
}

.switch-row input {
  width: 16px;
  height: 16px;
  accent-color: var(--soft-accent);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin-top: 24px;
}

.page-btn {
  min-width: 34px;
  height: 34px;
  padding: 0 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--soft-hairline);
  background: var(--soft-surface-strong);
  color: var(--soft-ink);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  display: flex;
  align-items: center;
  justify-content: center;
}

.page-btn:hover:not(:disabled) {
  border-color: var(--soft-accent);
  color: var(--soft-accent);
}

.page-btn.active {
  background: var(--soft-accent-grad);
  border-color: transparent;
  color: #fff;
  font-weight: 600;
  box-shadow: var(--soft-shadow-sm);
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-ellipsis {
  color: var(--soft-faint);
  font-size: 13px;
  padding: 0 4px;
}

.page-info {
  margin-left: 12px;
  font-size: 12.5px;
  color: var(--soft-muted);
}
</style>
