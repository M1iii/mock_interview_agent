<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { chatStream, finishSession, getSessionMessages, listKnowledgeBases, listSessions } from '../api/client'
import type { AssessPayload, Citation, KnowledgeBase, SSEEvent, SessionMeta } from '../api/types'

const route = useRoute()
const router = useRouter()

const sessionId = String(route.params.id)

const REPORT_PENDING = '报告生成中，请稍候…'

interface Msg {
  role: 'ai' | 'user'
  content: string
  streaming?: boolean
  citations?: Citation[]
  showCites?: boolean
  time: number
}

const session = ref<SessionMeta | null>(null)
const kbs = ref<KnowledgeBase[]>([])
const messages = ref<Msg[]>([])
const input = ref('')
const busy = ref(false)
const hintUsed = ref(false)
const questionIndex = ref(0)
const assessData = ref<AssessPayload | null>(null)
const showAssessCites = ref(false)
const toast = ref('')
const scrollBox = ref<HTMLDivElement | null>(null)
const inputEl = ref<HTMLTextAreaElement | null>(null)

let toastTimer: ReturnType<typeof setTimeout> | null = null

const canAnswer = computed(() => !busy.value && messages.value.length > 0)
const canHint = computed(() => canAnswer.value && !hintUsed.value)
const canSkip = computed(() => canAnswer.value)

const kbLabel = computed(() => {
  if (!session.value?.kb_id) return '未关联'
  const kb = kbs.value.find((k) => k.id === session.value!.kb_id)
  return kb ? kb.name : '已关联'
})

const progressPct = computed(() => {
  if (!session.value) return 0
  const done = Math.min(questionIndex.value, session.value.question_count)
  return Math.round((done / session.value.question_count) * 100)
})

const progressLabel = computed(() => {
  if (!session.value) return ''
  const cur = Math.min(questionIndex.value + 1, session.value.question_count)
  return `第 ${cur} / ${session.value.question_count} 题`
})

const hasAssess = computed(() => {
  const d = assessData.value
  return !!d && (Object.keys(d.dimensions).length > 0 || !!d.comment)
})

function showToast(text: string) {
  toast.value = text
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toast.value = ''), 3000)
}

async function scrollToBottom() {
  await nextTick()
  scrollBox.value?.scrollTo({ top: scrollBox.value.scrollHeight, behavior: 'smooth' })
}

function formatTime(t: number): string {
  const d = new Date(t)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

function appendAi(content: string, streaming = false): Msg {
  const msg: Msg = { role: 'ai', content, streaming, time: Date.now() }
  messages.value.push(msg)
  return msg
}

function handleEvent(e: SSEEvent, streamingMsg?: Msg) {
  if (e.event === 'status') {
    if (e.kind === 'thinking') {
      // 静默期占位：空消息由模板渲染「正在思考…」，首 token 到达后自然替换
      if (!streamingMsg) streamingMsg = appendAi('', true)
      void scrollToBottom()
    } else {
      // 报告生成占位：图执行期间先展示，生成完成后由 token 一次性替换
      if (streamingMsg) {
        streamingMsg.content = e.message ?? REPORT_PENDING
        streamingMsg.streaming = true
      } else {
        streamingMsg = appendAi(e.message ?? REPORT_PENDING, true)
      }
      void scrollToBottom()
    }
  } else if (e.event === 'token') {
    if (streamingMsg) {
      if (streamingMsg.content === REPORT_PENDING) streamingMsg.content = ''
      streamingMsg.content += e.content
      streamingMsg.streaming = true
    } else {
      streamingMsg = appendAi(e.content, true)
    }
    void scrollToBottom()
  } else if (e.event === 'error') {
    busy.value = false
    if (streamingMsg && streamingMsg.content === '' && streamingMsg.streaming) {
      // 请求失败：移除空的「正在思考…」占位气泡
      const idx = messages.value.indexOf(streamingMsg)
      if (idx >= 0) messages.value.splice(idx, 1)
    }
    showToast(e.message)
  } else if (e.event === 'done') {
    if (streamingMsg) streamingMsg.streaming = false
    busy.value = false
    if (typeof e.question_index === 'number') questionIndex.value = e.question_index
    void scrollToBottom()
    if (e.finished) {
      router.push(`/report/${sessionId}`)
    }
  } else if (e.event === 'assess') {
    assessData.value = {
      dimensions: e.dimensions,
      comment: e.comment,
      score: e.score,
      citations: e.citations || [],
    }
  } else if (e.event === 'citations') {
    if (streamingMsg) {
      streamingMsg.citations = e.citations
      streamingMsg.showCites = true
    }
  }
}

function toggleCites(m: Msg) {
  m.showCites = !m.showCites
}

async function runChat(options: { answer?: string; action?: 'hint' | 'skip' }, streamingMsg?: Msg) {
  busy.value = true
  try {
    await chatStream(sessionId, options, (e) => handleEvent(e, streamingMsg))
  } catch (err) {
    busy.value = false
    showToast(err instanceof Error ? err.message : '对话失败，请重试')
  }
}

async function startFirst() {
  if (busy.value || messages.value.length > 0) return
  const msg = appendAi('', true)
  await runChat({}, msg)
}

function onInputKeydown(e: KeyboardEvent) {
  // 中文输入法组合中回车用于确认拼音，不发送
  if (e.isComposing || e.keyCode === 229) return
  if (!e.shiftKey) {
    e.preventDefault()
    sendAnswer()
  }
}

function autoGrow() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 120)}px`
}

function resetInputHeight() {
  const el = inputEl.value
  if (el) el.style.height = 'auto'
}

function sendAnswer() {
  const text = input.value.trim()
  if (!text || busy.value) return
  input.value = ''
  resetInputHeight()
  messages.value.push({ role: 'user', content: text, time: Date.now() })
  void scrollToBottom()
  const msg = appendAi('', true)
  void runChat({ answer: text }, msg)
}

function requestHint() {
  if (!canHint.value) return
  hintUsed.value = true
  const msg = appendAi('', true)
  void runChat({ action: 'hint' }, msg)
}

function skipQuestion() {
  if (!canSkip.value) return
  if (!window.confirm('跳过此题？将标记为未作答，不计分。')) return
  messages.value.push({ role: 'user', content: '（跳过此题）', time: Date.now() })
  void scrollToBottom()
  const msg = appendAi('', true)
  void runChat({ action: 'skip' }, msg)
}

async function finishInterview() {
  if (busy.value) return
  if (!window.confirm('确定结束面试并生成报告？')) return
  busy.value = true
  try {
    await finishSession(sessionId)
    router.push(`/report/${sessionId}`)
  } catch (err) {
    busy.value = false
    showToast(err instanceof Error ? err.message : '结束失败')
  }
}

function backToList() {
  router.push('/')
}

onMounted(async () => {
  try {
    const list = await listSessions()
    session.value = list.find((s) => s.id === sessionId) ?? null
  } catch {
    session.value = null
  }
  try {
    kbs.value = await listKnowledgeBases()
  } catch {
    kbs.value = []
  }
  try {
    const hist = await getSessionMessages(sessionId)
    if (hist.status === 'finished') {
      router.push(`/report/${sessionId}`)
      return
    }
    hintUsed.value = hist.hints_used >= 1
    questionIndex.value = hist.question_index ?? 0
    if (hist.messages.length > 0) {
      for (const m of hist.messages) {
        messages.value.push({ role: m.role, content: m.content, time: Date.now() })
      }
      void scrollToBottom()
      return
    }
  } catch {
    // 历史接口异常时降级为新面试流程
  }
  await startFirst()
})

watch(messages, () => void scrollToBottom(), { deep: true })

onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer)
})

function sceneLabel(scene: string): string {
  return scene === 'intern' ? '实习' : '全职'
}
</script>

<template>
  <div class="chat-page">
    <div class="chat-layout">
      <div class="chat-main">
        <header class="chat-header">
          <button class="btn btn-ghost back-btn" @click="backToList">← 会话列表</button>
          <div class="chat-title">
            <h1 class="chat-heading">
              {{ session?.title ?? 'AI 面试官' }}
            </h1>
            <span v-if="session" class="chat-sub">
              <span class="type-chip">{{ sceneLabel(session.scene) }}</span>
              <span class="status-badge ongoing">进行中</span>
              · {{ session.question_count }} 题
              <span v-if="hintUsed" class="hint-used"> · 已用提示</span>
            </span>
          </div>
          <button class="btn btn-danger-ghost" :disabled="busy" @click="finishInterview">
            结束面试
          </button>
        </header>

        <div v-if="session" class="progress-row">
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
          </div>
          <span class="progress-label">{{ progressLabel }}</span>
        </div>

        <div ref="scrollBox" class="chat-scroll">
          <div v-if="messages.length === 0" class="chat-empty">
            <p>正在开启面试…</p>
          </div>

          <div v-for="(m, i) in messages" :key="i" class="bubble-row" :class="m.role">
            <div v-if="m.role === 'ai'" class="avatar ai-avatar">AI</div>
            <div class="bubble-col">
              <div class="bubble" :class="m.role">
                <span v-if="m.streaming && m.content === ''" class="typing">正在思考…</span>
                <span v-else-if="m.content === REPORT_PENDING" class="report-pending">
                  {{ m.content }}
                </span>
                <span v-else>{{ m.content }}</span>
              </div>
              <div
                v-if="!m.streaming && m.citations && m.citations.length"
                class="cite-block"
              >
                <button class="cite-toggle" @click="toggleCites(m)">
                  <span class="cite-arrow" :class="{ open: m.showCites }">▸</span>
                  引用来源（{{ m.citations.length }}）
                </button>
                <div v-if="m.showCites" class="cite-list">
                  <div v-for="(c, ci) in m.citations" :key="ci" class="cite-item">
                    <span class="cite-badge">[{{ ci + 1 }}]</span>
                    <div class="cite-body">
                      <div class="cite-file">{{ c.file_name }}</div>
                      <div class="cite-text">{{ c.text }}</div>
                    </div>
                  </div>
                </div>
              </div>
              <span v-if="!m.streaming && m.time" class="msg-meta">{{ formatTime(m.time) }}</span>
            </div>
            <div v-if="m.role === 'user'" class="avatar user-avatar">我</div>
          </div>

          <div v-if="busy" class="typing-row">
            <span class="typing-dots"><i></i><i></i><i></i></span>
          </div>
        </div>

        <div class="chat-input-bar">
          <button class="btn hint-btn" :disabled="!canHint" @click="requestHint">提示一下</button>
          <button class="btn skip-btn" :disabled="!canSkip" @click="skipQuestion">跳过此题</button>
          <textarea
            v-model="input"
            ref="inputEl"
            class="input chat-input"
            rows="1"
            placeholder="输入你的回答…（Enter 发送，Shift+Enter 换行）"
            :disabled="!canAnswer"
            @keydown.enter="onInputKeydown"
            @input="autoGrow"
          ></textarea>
          <button class="btn btn-primary" :disabled="!canAnswer" @click="sendAnswer">发送</button>
        </div>
      </div>

      <aside class="chat-side">
        <div class="card side-card">
          <h4 class="side-title">本轮评估要点</h4>
          <div v-if="hasAssess" class="assess-panel">
            <div
              v-for="(val, key) in assessData!.dimensions"
              :key="key"
              class="dim-row"
              :class="val >= 6 ? 'good' : 'warn'"
            >
              <span class="dim-mark">{{ val >= 6 ? '✓' : '○' }}</span>
              <span class="dim-name">{{ key }}</span>
              <span class="dim-score">{{ val }} 分</span>
            </div>
            <p v-if="Object.keys(assessData!.dimensions).length > 0" class="assess-comment">
              {{ assessData!.comment }}
            </p>
            <p v-else class="assess-fallback">{{ assessData!.comment || '本次未生成评估要点' }}</p>
            <div
              v-if="hasAssess && assessData!.citations && assessData!.citations.length"
              class="cite-block assess-cites"
            >
              <button class="cite-toggle" @click="showAssessCites = !showAssessCites">
                <span class="cite-arrow" :class="{ open: showAssessCites }">▸</span>
                引用来源（{{ assessData!.citations.length }}）
              </button>
              <div v-if="showAssessCites" class="cite-list">
                <div v-for="(c, ci) in assessData!.citations" :key="ci" class="cite-item">
                  <span class="cite-badge">[{{ ci + 1 }}]</span>
                  <div class="cite-body">
                    <div class="cite-file">{{ c.file_name }}</div>
                    <div class="cite-text">{{ c.text }}</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <p v-else class="side-placeholder">回答后由评估节点实时生成</p>
        </div>

        <div class="card side-card">
          <h4 class="side-title">会话信息</h4>
          <div class="info-row"><span>面试官</span><b>DeepSeek</b></div>
          <div class="info-row">
            <span>面试场景</span><b>{{ session ? sceneLabel(session.scene) : '—' }}</b>
          </div>
          <div class="info-row">
            <span>知识库</span><b>{{ kbLabel }}</b>
          </div>
          <div class="info-row"><span>简历</span><b class="muted">未关联 · P2 启用</b></div>
        </div>
      </aside>
    </div>

    <transition name="toast">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </transition>
  </div>
</template>

<style scoped>
.chat-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
}

.chat-layout {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 24px;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.chat-side {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-top: 16px;
  overflow-y: auto;
}

.side-card {
  padding: 16px 18px;
}

.side-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-3);
  margin: 0 0 12px;
}

.dim-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  font-size: 13px;
}

.dim-mark {
  width: 16px;
  text-align: center;
  font-weight: 700;
}

.dim-row.good .dim-mark {
  color: #34c77b;
}

.dim-row.warn .dim-mark {
  color: var(--warning);
}

.dim-name {
  flex: 1;
  color: var(--text-1);
}

.dim-score {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.assess-comment {
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.6;
  border-top: 1px dashed var(--border);
  padding-top: 10px;
  margin: 8px 0 0;
}

.assess-fallback,
.side-placeholder {
  font-size: 13px;
  color: var(--text-3);
  margin: 0;
  line-height: 1.6;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 0;
  font-size: 13px;
}

.info-row span {
  color: var(--text-3);
}

.info-row b {
  color: var(--text-1);
  font-weight: 600;
}

.info-row .muted {
  color: var(--text-3);
  font-weight: 400;
}

@media (max-width: 960px) {
  .chat-side {
    display: none;
  }
}

.chat-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 0;
  border-bottom: 1px solid var(--border);
}

.back-btn {
  color: var(--text-2);
}

.chat-title {
  flex: 1;
}

.chat-heading {
  font-size: 18px;
  font-weight: 700;
}

.chat-sub {
  font-size: 13px;
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.type-chip,
.status-badge {
  font-size: 12px;
  font-weight: 500;
  padding: 2px 10px;
  border-radius: var(--r-full);
}

.type-chip {
  background: var(--primary-soft);
  color: var(--primary);
}

.status-badge.ongoing {
  background: #dcfce7;
  color: #15803d;
}

.hint-used {
  color: var(--warning);
}

.btn-danger-ghost {
  color: var(--danger);
  border-color: rgba(229, 72, 77, 0.3);
}

.progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0 0;
}

.progress-track {
  flex: 1;
  height: 6px;
  border-radius: var(--r-full);
  background: var(--border);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(135deg, var(--primary), #a78bfa);
  transition: width 0.3s var(--ease-out);
}

.progress-label {
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}

.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 4px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.chat-empty {
  text-align: center;
  color: var(--text-3);
  padding: 60px 0;
}

.bubble-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.bubble-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--primary), #a78bfa);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.user-avatar {
  background: #475569;
  font-size: 15px;
}

.bubble-col {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.bubble-row.user .bubble-col {
  align-items: flex-end;
}

.msg-meta {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 4px;
  padding: 0 4px;
  font-variant-numeric: tabular-nums;
}

.cite-block {
  margin-top: 8px;
  max-width: 520px;
}

.cite-toggle {
  background: var(--primary-soft);
  color: var(--primary);
  border: none;
  border-radius: var(--r-full);
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.cite-arrow {
  display: inline-block;
  transition: transform 0.2s var(--ease-out);
}

.cite-arrow.open {
  transform: rotate(90deg);
}

.cite-list {
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
  overflow: hidden;
}

.cite-item {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
}

.cite-item + .cite-item {
  border-top: 1px dashed var(--border);
}

.cite-badge {
  color: var(--primary);
  font-weight: 700;
  font-size: 12px;
  flex-shrink: 0;
}

.cite-body {
  min-width: 0;
}

.cite-file {
  font-weight: 600;
  color: var(--text-1);
  font-size: 12px;
  margin-bottom: 2px;
}

.cite-text {
  color: var(--text-2);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.assess-cites {
  margin-top: 8px;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
.assess-cites .cite-text {
  font-size: 12px;
  line-height: 1.5;
}

.bubble {
  max-width: 72%;
  padding: 12px 16px;
  border-radius: 18px;
  font-size: 15px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble.ai {
  background: var(--surface);
  border: 1px solid var(--border);
  border-top-left-radius: 6px;
  box-shadow: var(--shadow-sm);
}

.bubble.user {
  background: var(--primary);
  color: #fff;
  border-top-right-radius: 6px;
}

.typing {
  color: var(--text-3);
  font-size: 14px;
}

.report-pending {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--primary);
  font-weight: 600;
}

.report-pending::before {
  content: '';
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid rgba(124, 58, 237, 0.25);
  border-top-color: var(--primary);
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.typing-row {
  padding-left: 44px;
}

.typing-dots {
  display: inline-flex;
  gap: 4px;
}

.typing-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--primary);
  opacity: 0.4;
  animation: blink 1.2s infinite;
}

.typing-dots i:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-dots i:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.3;
  }
  40% {
    opacity: 1;
  }
}

.chat-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 16px 0 20px;
}

.hint-btn,
.skip-btn {
  white-space: nowrap;
  font-size: 13px;
  padding: 10px 14px;
  margin-bottom: 4px;
}

.skip-btn {
  color: var(--text-2);
}

.chat-input {
  flex: 1;
  padding: 12px 16px;
  resize: none;
  line-height: 1.5;
  max-height: 120px;
  overflow-y: auto;
}

.toast {
  position: fixed;
  top: 20px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--text-1);
  color: #fff;
  padding: 10px 20px;
  border-radius: var(--r-full);
  font-size: 14px;
  box-shadow: var(--shadow-lg);
  z-index: 200;
}

.toast-enter-active,
.toast-leave-active {
  transition:
    opacity 0.25s var(--ease-out),
    transform 0.25s var(--ease-out);
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-8px);
}
</style>
