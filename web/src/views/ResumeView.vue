<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { deleteResume, listResumes, retryResume, uploadResume } from '../api/client'
import type { Resume, ResumeStatus } from '../api/types'

const router = useRouter()

const resumes = ref<Resume[]>([])
const loading = ref(false)
const error = ref('')
const uploading = ref(false)
const fileInput = ref<HTMLInputElement>()

const ACCEPT_EXTS = '.pdf,.docx,.md,.txt'
const MAX_MB = 20

const STATUS_LABEL: Record<ResumeStatus, string> = {
  processing: '解析中',
  ready: '就绪',
  failed: '失败',
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    resumes.value = await listResumes()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载简历失败'
  } finally {
    loading.value = false
  }
}

function poll() {
  if (resumes.value.some((r) => r.status === 'processing')) {
    setTimeout(async () => {
      await load()
      poll()
    }, 1500)
  }
}

function pickFile() {
  fileInput.value?.click()
}

async function onUpload() {
  const file = fileInput.value?.files?.[0]
  if (!file) return
  if (file.size > MAX_MB * 1024 * 1024) {
    error.value = `文件超过 ${MAX_MB}MB 上限`
    return
  }
  uploading.value = true
  error.value = ''
  try {
    await uploadResume(file)
    if (fileInput.value) fileInput.value.value = ''
    await load()
    poll()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function onRetry(id: string) {
  try {
    await retryResume(id)
    await load()
    poll()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '重试失败'
  }
}

async function onDelete(id: string) {
  if (!window.confirm('删除后不可恢复，确定删除该简历？')) return
  try {
    await deleteResume(id)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  }
}

function formatSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

function goHome() {
  router.push('/')
}

onMounted(async () => {
  await load()
  poll()
})
</script>

<template>
  <div class="page resumes">
    <header class="resume-header">
      <button class="btn btn-ghost" @click="goHome">← 返回</button>
      <h1 class="page-title">简历管理</h1>
      <button class="btn btn-primary" :disabled="uploading" @click="pickFile">
        {{ uploading ? '上传中…' : '上传简历' }}
      </button>
    </header>

    <p class="page-sub">
      上传简历（PDF / DOCX / MD / TXT，≤20MB），自动解析并抽取考点清单，供面试出题使用。
    </p>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-if="loading && resumes.length === 0" class="state-hint">加载简历中…</div>

    <div v-else-if="resumes.length === 0" class="state-hint empty-card card">
      <p class="empty-title">还没有简历</p>
      <p class="empty-sub">上传一份简历，面试官将结合简历考点出题</p>
      <button class="btn btn-primary" @click="pickFile">上传第一份简历</button>
    </div>

    <div v-else class="resume-list">
      <div v-for="r in resumes" :key="r.id" class="card resume-card">
        <div class="resume-card-head">
          <div class="resume-title-wrap">
            <h2 class="resume-name" :title="r.file_name">{{ r.file_name }}</h2>
            <span class="resume-size">{{ formatSize(r.size) }}</span>
          </div>
          <span class="resume-status" :class="`st-${r.status}`">
            {{ STATUS_LABEL[r.status] }}
          </span>
        </div>

        <p class="resume-meta">
          考点 {{ r.point_count ?? 0 }} 个 · 创建于 {{ new Date(r.created_at).toLocaleString('zh-CN') }}
        </p>

        <p v-if="r.status === 'failed' && r.error" class="resume-error" :title="r.error">
          失败原因：{{ r.error }}
        </p>

        <div class="resume-actions">
          <button v-if="r.status === 'failed'" class="btn btn-ghost btn-sm" @click="onRetry(r.id)">
            重试
          </button>
          <button class="btn btn-danger-ghost btn-sm" @click="onDelete(r.id)">删除</button>
        </div>
      </div>
    </div>

    <input ref="fileInput" class="hidden-input" type="file" :accept="ACCEPT_EXTS" @change="onUpload" />
  </div>
</template>

<style scoped>
.resumes {
  max-width: 860px;
}

.resume-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.resume-header .page-title {
  margin: 0;
  flex: 1;
}

.resume-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.resume-card {
  padding: 20px 24px;
}

.resume-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.resume-title-wrap {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.resume-name {
  font-size: 17px;
  font-weight: 700;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-size {
  font-size: 12px;
  color: var(--text-3);
  font-family: 'JetBrains Mono', Consolas, monospace;
  white-space: nowrap;
}

.resume-status {
  font-size: 12px;
  padding: 3px 12px;
  border-radius: var(--r-full);
  white-space: nowrap;
}

.st-processing {
  background: #fef9c3;
  color: #a16207;
}

.st-ready {
  background: #dcfce7;
  color: #15803d;
}

.st-failed {
  background: #fee2e2;
  color: #b91c1c;
}

.resume-meta {
  font-size: 13px;
  color: var(--text-2);
  margin: 8px 0 0;
}

.resume-error {
  font-size: 13px;
  color: var(--danger);
  margin: 8px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.resume-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.btn-danger-ghost {
  color: var(--danger);
  border-color: var(--border);
  background: transparent;
}

.btn-danger-ghost:hover {
  border-color: var(--danger);
  color: var(--danger);
  background: #fef2f2;
}

.btn-sm {
  padding: 4px 12px;
  font-size: 12px;
}

.hidden-input {
  display: none;
}

.error {
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 14px;
}

.state-hint {
  text-align: center;
  color: var(--text-3);
  padding: 40px 0;
}

.empty-card {
  padding: 48px 24px;
}

.empty-title {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 8px;
}

.empty-sub {
  font-size: 14px;
  color: var(--text-2);
  margin-bottom: 20px;
}
</style>
