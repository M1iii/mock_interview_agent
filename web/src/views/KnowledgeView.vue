<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  createKnowledgeBase,
  deleteKnowledgeBase,
  listKnowledgeBases,
  retryKnowledgeFile,
  uploadKnowledgeFile,
} from '../api/client'
import type { KnowledgeBase } from '../api/types'

const router = useRouter()

const kbs = ref<KnowledgeBase[]>([])
const loading = ref(false)
const error = ref('')

const creating = ref(false)
const createOpen = ref(false)
const createName = ref('')
const createError = ref('')

const uploadTarget = ref<KnowledgeBase | null>(null)
const uploading = ref(false)
const uploadError = ref('')

const deletingId = ref('')
const deleteTarget = ref<KnowledgeBase | null>(null)

let pollTimer: number | undefined

const ACCEPT_EXTS = '.md,.txt,.docx,.pdf'
const MAX_MB = 50

async function load() {
  loading.value = true
  error.value = ''
  try {
    kbs.value = await listKnowledgeBases()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载知识库失败'
  } finally {
    loading.value = false
  }
}

function startPolling() {
  window.clearInterval(pollTimer)
  pollTimer = window.setInterval(load, 3000)
}

function stopPolling() {
  window.clearInterval(pollTimer)
}

onMounted(() => {
  load()
  startPolling()
})

onUnmounted(stopPolling)

function openCreate() {
  createOpen.value = true
  createName.value = ''
  createError.value = ''
}

async function submitCreate() {
  const name = createName.value.trim()
  if (!name) {
    createError.value = '请输入知识库名称'
    return
  }
  creating.value = true
  createError.value = ''
  try {
    await createKnowledgeBase(name)
    createOpen.value = false
    await load()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    creating.value = false
  }
}

function pickUpload(kb: KnowledgeBase) {
  uploadTarget.value = kb
  uploadError.value = ''
  ;(document.getElementById(`file-${kb.id}`) as HTMLInputElement | null)?.click()
}

async function onFileChange(kb: KnowledgeBase, evt: Event) {
  const input = evt.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > MAX_MB * 1024 * 1024) {
    uploadError.value = `文件超过 ${MAX_MB}MB 上限`
    return
  }
  uploading.value = true
  uploadError.value = ''
  try {
    await uploadKnowledgeFile(kb.id, file)
    await load()
  } catch (e) {
    uploadError.value = e instanceof Error ? e.message : '上传失败'
  } finally {
    uploading.value = false
  }
}

async function retry(kbId: string, recordId: string) {
  try {
    await retryKnowledgeFile(kbId, recordId)
    await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '重试失败'
  }
}

function askDelete(kb: KnowledgeBase) {
  deleteTarget.value = kb
}

async function confirmDelete() {
  if (!deleteTarget.value) return
  const kb = deleteTarget.value
  deletingId.value = kb.id
  try {
    await deleteKnowledgeBase(kb.id)
    kbs.value = kbs.value.filter((k) => k.id !== kb.id)
    deleteTarget.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  } finally {
    deletingId.value = ''
  }
}

function formatSize(size: number): string {
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

function statusLabel(status: string): string {
  return { processing: '入库中', ready: '已就绪', failed: '失败' }[status] ?? status
}

function goHome() {
  router.push('/')
}
</script>

<template>
  <div class="page knowledge">
    <header class="kb-header">
      <button class="btn btn-ghost" @click="goHome">← 返回</button>
      <h1 class="page-title">知识库</h1>
      <button class="btn btn-primary" @click="openCreate">新建知识库</button>
    </header>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="uploadError" class="error">{{ uploadError }}</p>
    <p v-if="uploading" class="hint">上传中，请稍候…</p>

    <div v-if="loading && kbs.length === 0" class="state-hint">加载知识库中…</div>

    <div v-else-if="kbs.length === 0" class="state-hint empty-card card">
      <p class="empty-title">还没有知识库</p>
      <p class="empty-sub">上传面试相关的文档资料（简历、项目说明、岗位 JD），面试官将基于知识库出题</p>
      <button class="btn btn-primary" @click="openCreate">新建知识库</button>
    </div>

    <div v-else class="kb-grid">
      <div v-for="kb in kbs" :key="kb.id" class="card kb-card">
        <div class="kb-card-head">
          <div class="kb-title-wrap">
            <h2 class="kb-name">{{ kb.name }}</h2>
            <span class="kb-model">{{ kb.model_id }} · {{ kb.dims }}d</span>
          </div>
          <button class="btn btn-danger-ghost" @click="askDelete(kb)">删除</button>
        </div>

        <p class="kb-meta">
          文件 {{ kb.files.length }} 个 · 创建于 {{ new Date(kb.created_at).toLocaleDateString() }}
        </p>

        <div v-if="kb.files.length" class="file-list">
          <div v-for="f in kb.files" :key="f.id" class="file-row">
            <span class="file-name" :title="f.name">{{ f.name }}</span>
            <span class="file-size">{{ formatSize(f.size) }}</span>
            <span class="file-status" :class="`st-${f.status}`">
              {{ statusLabel(f.status) }}
              <span v-if="f.block_count != null">（{{ f.block_count }} 块）</span>
            </span>
            <button v-if="f.status === 'failed'" class="btn btn-ghost btn-sm" @click="retry(kb.id, f.id)">
              重试
            </button>
            <span v-if="f.status === 'failed' && f.error" class="file-error" :title="f.error">失败原因</span>
          </div>
        </div>
        <p v-else class="kb-empty">暂无文件</p>

        <input
          :id="`file-${kb.id}`"
          class="hidden-input"
          type="file"
          :accept="ACCEPT_EXTS"
          @change="onFileChange(kb, $event)"
        />
        <button class="btn btn-ghost upload-btn" :disabled="uploading" @click="pickUpload(kb)">
          上传文件
        </button>
        <p class="upload-hint">支持 md / txt / docx / pdf，单个 ≤ 50MB，上传后后台解析入库</p>
      </div>
    </div>

    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal card">
        <h3 class="modal-title">新建知识库</h3>
        <input
          v-model="createName"
          class="input"
          placeholder="知识库名称（如：岗位 JD + 项目资料）"
          maxlength="64"
          @keyup.enter="submitCreate"
        />
        <p v-if="createError" class="error">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="createOpen = false">取消</button>
          <button class="btn btn-primary" :disabled="creating" @click="submitCreate">
            {{ creating ? '创建中…' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="deleteTarget" class="modal-mask" @click.self="deleteTarget = null">
      <div class="modal card">
        <h3 class="modal-title">删除知识库</h3>
        <p class="modal-desc">
          将删除「{{ deleteTarget.name }}」的全部文件与索引（Qdrant 向量 + ES 正文，不可恢复）。
          确定删除吗？
        </p>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="deleteTarget = null">取消</button>
          <button class="btn btn-danger" :disabled="deletingId === deleteTarget.id" @click="confirmDelete">
            {{ deletingId === deleteTarget.id ? '删除中…' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.knowledge {
  max-width: 860px;
}

.kb-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.kb-header .page-title {
  margin: 0;
  flex: 1;
}

.kb-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.kb-card {
  padding: 22px 24px;
}

.kb-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.kb-name {
  font-size: 17px;
  font-weight: 700;
  margin: 0 0 4px;
}

.kb-model {
  font-size: 12px;
  color: var(--text-3);
  font-family: 'JetBrains Mono', Consolas, monospace;
}

.kb-meta {
  font-size: 13px;
  color: var(--text-2);
  margin: 6px 0 14px;
}

.file-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 14px;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}

.file-row:last-child {
  border-bottom: none;
}

.file-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-1);
}

.file-size {
  color: var(--text-3);
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 12px;
}

.file-status {
  font-size: 12px;
  padding: 2px 10px;
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

.file-error {
  font-size: 12px;
  color: var(--danger);
  cursor: help;
  white-space: nowrap;
}

.kb-empty {
  font-size: 13px;
  color: var(--text-3);
  margin: 0 0 14px;
}

.hidden-input {
  display: none;
}

.upload-btn {
  margin-bottom: 6px;
}

.upload-hint {
  font-size: 12px;
  color: var(--text-3);
  margin: 0;
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
  padding: 2px 10px;
  font-size: 12px;
}

.error {
  color: var(--danger);
  font-size: 13px;
  margin-bottom: 14px;
}

.hint {
  color: var(--text-2);
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

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}

.modal {
  width: 400px;
  max-width: calc(100vw - 40px);
  padding: 24px;
}

.modal-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 16px;
}

.modal-desc {
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.6;
  margin: 0 0 4px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.btn-danger {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}

.btn-danger:hover {
  opacity: 0.9;
}
</style>
