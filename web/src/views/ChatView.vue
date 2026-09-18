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

const resumeLabel = computed(() => {
  if (!session.value?.resume_id) return '未关联'
  return '已关联'
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
      if (!streamingMsg) streamingMsg = appendAi('', true)
      void scrollToBottom()
    } else {
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
      verification: e.verification ?? null,
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
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
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

function interviewTypeLabel(type?: string): string {
  return { technical: '技术面', behavioral: '行为面', comprehensive: '综合面' }[type ?? 'technical'] ?? '技术面'
}
</script>

<template>
  <div class="chat-page">
    <div class="chat-layout">
      <div class="chat-main">
        <header class="chat-header">
          <button class="back-btn" @click="backToList">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="19" y1="12" x2="5" y2="12"/>
              <polyline points="12 19 5 12 12 5"/>
            </svg>
            会话列表
          </button>
          <div class="chat-title">
            <h1 class="chat-heading">
              {{ session?.title ?? 'AI 面试官' }}
            </h1>
            <span v-if="session" class="chat-sub">
              <span class="badge badge-info">{{ sceneLabel(session.scene) }} · {{ interviewTypeLabel(session.interview_type) }}</span>
              <span class="badge badge-success">进行中</span>
              <span class="chat-sub-text">{{ session.question_count }} 题</span>
              <span v-if="hintUsed" class="chat-sub-text hint-used">· 已用提示</span>
            </span>
          </div>
          <button class="btn btn-ghost finish-btn" :disabled="busy" @click="finishInterview">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
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
            <div v-if="m.role === 'ai'" class="avatar ai-avatar">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="11" width="18" height="10" rx="2"/>
                <circle cx="12" cy="5" r="2"/>
                <path d="M12 7v4"/>
                <line x1="8" y1="16" x2="8" y2="16"/>
                <line x1="16" y1="16" x2="16" y2="16"/>
              </svg>
            </div>
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
                <div v-if="m.showCites" class="cite-list card">
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

        <!-- 集成式输入底栏 -->
        <div class="chat-input-card">
          <textarea
            v-model="input"
            ref="inputEl"
            class="chat-input"
            rows="1"
            placeholder="输入你的回答…（Enter 发送，Shift+Enter 换行）"
            :disabled="!canAnswer"
            @keydown.enter="onInputKeydown"
            @input="autoGrow"
          ></textarea>
          <div class="input-toolbar">
            <div class="toolbar-left">
              <button class="toolbar-btn" :disabled="!canHint" @click="requestHint">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <circle cx="12" cy="12" r="10"/>
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
                  <line x1="12" y1="17" x2="12.01" y2="17"/>
                </svg>
                提示一下
              </button>
              <button class="toolbar-btn" :disabled="!canSkip" @click="skipQuestion">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3"/>
                  <line x1="19" y1="5" x2="19" y2="19"/>
                </svg>
                跳过此题
              </button>
            </div>
            <button class="send-btn" :disabled="!canAnswer" @click="sendAnswer">
              <span>发送</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/>
                <polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
            </button>
          </div>
        </div>
      </div>

      <aside class="chat-side">
        <div class="card side-card">
          <div class="side-card-head">
            <h4 class="side-title">本轮评估要点</h4>
            <span v-if="hasAssess && assessData!.score != null" class="score-chip">
              {{ assessData!.score }} 分
            </span>
          </div>
          <div v-if="hasAssess" class="assess-panel">
            <div class="dim-list">
              <div
                v-for="(val, key) in assessData!.dimensions"
                :key="key"
                class="dim-row"
                :class="val >= 6 ? 'good' : 'warn'"
              >
                <span class="dim-dot"></span>
                <span class="dim-name">{{ key }}</span>
                <span class="dim-score">{{ val }}</span>
              </div>
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
              <div v-if="showAssessCites" class="cite-list cite-list-side">
                <div v-for="(c, ci) in assessData!.citations" :key="ci" class="cite-item">
                  <span class="cite-badge">[{{ ci + 1 }}]</span>
                  <div class="cite-body">
                    <div class="cite-file">{{ c.file_name }}</div>
                    <div class="cite-text">{{ c.text }}</div>
                  </div>
                </div>
              </div>
            </div>

            <div
              v-if="hasAssess && assessData!.verification"
              class="verify-box"
            >
              <div class="verify-head">
                <span class="verify-badge" :class="assessData!.verification.status">
                  {{
                    assessData!.verification.status === 'verified' ? '已核验' :
                    assessData!.verification.status === 'uncertain' ? '存疑' : '无法确认'
                  }}
                </span>
                <span v-if="assessData!.verification.skipped" class="verify-skip">（已跳过）</span>
              </div>
              <p v-if="assessData!.verification.reason" class="verify-reason">{{ assessData!.verification.reason }}</p>
              <ul
                v-if="assessData!.verification.sources && assessData!.verification.sources.length"
                class="verify-sources"
              >
                <li v-for="(src, i) in assessData!.verification.sources" :key="i">
                  <a :href="src.url" target="_blank" rel="noopener">{{ src.title || src.url }}</a>
                </li>
              </ul>
            </div>
          </div>
          <p v-else class="side-placeholder">回答后由评估节点实时生成</p>
        </div>

        <div class="card side-card">
          <h4 class="side-title">会话信息</h4>
          <div class="info-row"><span class="info-label">面试官</span><span class="info-value">DeepSeek</span></div>
          <div class="info-row">
            <span class="info-label">面试场景</span>
            <span class="info-value">{{ session ? sceneLabel(session.scene) : '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">面试类型</span>
            <span class="info-value">{{ session ? interviewTypeLabel(session.interview_type) : '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">知识库</span>
            <span class="info-value">{{ kbLabel }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">简历</span>
            <span class="info-value">{{ resumeLabel }}</span>
          </div>
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
  max-width: 1160px;
  margin: 0 auto;
  padding: 0 28px;
  position: relative;
  z-index: 1;
}

.chat-layout {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 28px;
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
  gap: 14px;
  padding-top: 20px;
  overflow-y: auto;
}

.side-card {
  padding: 18px 20px;
}

.side-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.side-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--soft-ink);
  margin: 0 0 12px;
  letter-spacing: -0.01em;
}

.side-card-head .side-title {
  margin: 0;
}

.score-chip {
  font-size: 12px;
  font-weight: 700;
  color: var(--soft-accent);
  background: var(--soft-accent-bg);
  padding: 2px 10px;
  border-radius: var(--r-full);
}

.dim-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.dim-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  font-size: 13px;
}

.dim-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.dim-row.good .dim-dot {
  background: var(--success);
  box-shadow: 0 0 0 3px oklch(90% 0.08 145 / 0.5);
}

.dim-row.warn .dim-dot {
  background: var(--warning);
  box-shadow: 0 0 0 3px oklch(90% 0.08 70 / 0.5);
}

.dim-name {
  flex: 1;
  color: var(--soft-ink);
  font-weight: 500;
}

.dim-score {
  color: var(--soft-muted);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 12px;
}

.assess-comment {
  font-size: 12.5px;
  color: var(--soft-muted);
  line-height: 1.7;
  border-top: 1px solid var(--soft-hairline);
  padding-top: 12px;
  margin: 10px 0 0;
}

.assess-fallback,
.side-placeholder {
  font-size: 13px;
  color: var(--soft-faint);
  margin: 0;
  line-height: 1.6;
  font-style: italic;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 0;
  font-size: 12.5px;
}

.info-label {
  color: var(--soft-faint);
}

.info-value {
  color: var(--soft-ink);
  font-weight: 500;
  text-align: right;
  max-width: 55%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 960px) {
  .chat-side {
    display: none;
  }
}

/* ===== Header ===== */
.chat-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 18px 0 12px;
  border-bottom: 1px solid var(--soft-hairline);
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 10px;
  color: var(--soft-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: all var(--transition-fast);
}

.back-btn:hover {
  background: var(--soft-accent-bg);
  color: var(--soft-accent);
}

.chat-title {
  flex: 1;
  min-width: 0;
}

.chat-heading {
  font-size: 17px;
  font-weight: 700;
  color: var(--soft-ink);
  letter-spacing: -0.01em;
  margin-bottom: 4px;
}

.chat-sub {
  font-size: 12px;
  color: var(--soft-muted);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.chat-sub-text {
  color: var(--soft-faint);
}

.hint-used {
  color: var(--warning);
  font-weight: 500;
}

.finish-btn {
  color: var(--soft-faint);
  border: 1px solid var(--soft-hairline);
  background: var(--soft-surface);
  backdrop-filter: blur(12px);
}

.finish-btn:hover {
  color: var(--danger);
  border-color: oklch(55% 0.22 25 / 0.3);
  background: var(--danger-bg);
}

/* ===== Progress ===== */
.progress-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0 4px;
}

.progress-label {
  font-size: 12px;
  color: var(--soft-muted);
  white-space: nowrap;
  font-weight: 500;
}

/* ===== Chat Scroll ===== */
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 8px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.chat-empty {
  text-align: center;
  color: var(--soft-faint);
  padding: 60px 0;
}

/* ===== Bubbles ===== */
.bubble-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.bubble-row.user {
  justify-content: flex-end;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-weight: 700;
  font-size: 12px;
}

.ai-avatar {
  background: var(--soft-accent-grad);
  color: #fff;
  box-shadow: var(--soft-shadow-sm);
}

.user-avatar {
  background: oklch(45% 0.02 280);
  color: #fff;
  font-size: 13px;
}

.bubble-col {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  max-width: calc(100% - 90px);
}

.bubble-row.user .bubble-col {
  align-items: flex-end;
}

.bubble {
  max-width: 100%;
  padding: 12px 16px;
  border-radius: 16px;
  font-size: 14.5px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.bubble.ai {
  background: var(--soft-bubble-ai);
  border: 1px solid oklch(70% 0.2 280 / 0.15);
  border-top-left-radius: 4px;
  color: var(--soft-ink);
}

.bubble.user {
  background: var(--soft-bubble-user);
  color: #fff;
  border-top-right-radius: 4px;
  box-shadow: 0 4px 14px oklch(55% 0.2 275 / 0.3);
}

.msg-meta {
  font-size: 11px;
  color: var(--soft-faint);
  margin-top: 5px;
  padding: 0 4px;
  font-variant-numeric: tabular-nums;
}

.typing {
  color: var(--soft-faint);
  font-size: 14px;
}

.report-pending {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--soft-accent);
  font-weight: 600;
}

.report-pending::before {
  content: '';
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid oklch(70% 0.2 280 / 0.3);
  border-top-color: var(--soft-accent);
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.typing-row {
  padding-left: 46px;
}

.typing-dots {
  display: inline-flex;
  gap: 4px;
}

.typing-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--soft-accent);
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

/* ===== Citation ===== */
.cite-block {
  margin-top: 8px;
  max-width: 520px;
}

.cite-toggle {
  background: var(--soft-accent-bg);
  color: var(--soft-accent);
  border: none;
  border-radius: var(--r-full);
  padding: 4px 12px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  transition: all var(--transition-fast);
}

.cite-toggle:hover {
  background: oklch(70% 0.2 280 / 0.25);
}

.cite-arrow {
  display: inline-block;
  transition: transform 0.2s var(--ease-out);
  font-size: 10px;
}

.cite-arrow.open {
  transform: rotate(90deg);
}

.cite-list {
  margin-top: 8px;
  border-radius: 12px;
  overflow: hidden;
  padding: 4px 8px;
}

.cite-item {
  display: flex;
  gap: 10px;
  padding: 10px 8px;
  font-size: 12.5px;
  line-height: 1.6;
  border-bottom: 1px solid var(--soft-hairline);
}

.cite-item:last-child {
  border-bottom: none;
}

.cite-badge {
  color: var(--soft-accent);
  font-weight: 700;
  font-size: 11px;
  flex-shrink: 0;
}

.cite-body {
  min-width: 0;
}

.cite-file {
  font-weight: 600;
  color: var(--soft-ink);
  font-size: 12px;
  margin-bottom: 2px;
}

.cite-text {
  color: var(--soft-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 12px;
}

.assess-cites {
  margin-top: 10px;
  border-top: 1px solid var(--soft-hairline);
  padding-top: 10px;
}

.cite-list-side {
  background: oklch(97% 0.012 280 / 0.5);
}

/* ===== Verify ===== */
.verify-box {
  margin-top: 12px;
  padding: 12px;
  border-radius: 12px;
  background: oklch(97% 0.012 280 / 0.6);
  font-size: 12px;
  border: 1px solid var(--soft-hairline);
}

.verify-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.verify-badge {
  font-size: 11px;
  padding: 2px 9px;
  border-radius: var(--r-full);
  font-weight: 600;
}

.verify-badge.verified {
  background: var(--success-bg);
  color: oklch(48% 0.14 145);
}

.verify-badge.uncertain {
  background: var(--warning-bg);
  color: oklch(55% 0.16 70);
}

.verify-badge.unconfirmed {
  background: oklch(94% 0.015 280);
  color: var(--soft-faint);
}

.verify-skip {
  font-size: 11px;
  color: var(--soft-faint);
}

.verify-reason {
  margin: 8px 0 0;
  color: var(--soft-muted);
  line-height: 1.6;
}

.verify-sources {
  margin: 8px 0 0;
  padding-left: 16px;
}

.verify-sources li {
  margin: 2px 0;
}

.verify-sources a {
  color: var(--soft-accent);
  font-size: 11.5px;
}

/* ===== 集成式输入底栏 ===== */
.chat-input-card {
  margin: 16px 0 24px;
  background: var(--soft-surface);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid oklch(100% 0 0 / 0.5);
  border-radius: var(--r-xl);
  box-shadow: var(--soft-shadow-md);
  overflow: hidden;
}

.chat-input {
  width: 100%;
  padding: 16px 20px 12px;
  border: none;
  background: transparent;
  resize: none;
  line-height: 1.6;
  max-height: 160px;
  overflow-y: auto;
  font-size: 14px;
  color: var(--soft-ink);
  outline: none;
  font-family: inherit;
}

.chat-input::placeholder {
  color: var(--soft-faint);
}

.chat-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 12px 12px;
  gap: 10px;
}

.toolbar-left {
  display: flex;
  gap: 6px;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: var(--r-md);
  font-size: 12.5px;
  font-weight: 500;
  color: var(--soft-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.toolbar-btn:hover:not(:disabled) {
  background: var(--soft-accent-bg);
  color: var(--soft-accent);
}

.toolbar-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.send-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: var(--r-md);
  font-size: 13px;
  font-weight: 600;
  color: #fff;
  background: var(--soft-accent-grad);
  border: none;
  cursor: pointer;
  box-shadow: var(--soft-shadow-accent);
  transition: all var(--transition-fast);
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 12px 28px oklch(55% 0.2 275 / 0.45);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}

/* ===== Toast ===== */
.toast {
  position: fixed;
  top: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: oklch(25% 0.03 280 / 0.9);
  color: #fff;
  padding: 10px 20px;
  border-radius: var(--r-md);
  font-size: 13px;
  box-shadow: var(--soft-shadow-lg);
  z-index: 200;
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
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

/* ===== 响应式 ===== */
@media (max-width: 640px) {
  .chat-page {
    padding: 0 12px;
  }

  .bubble-col {
    max-width: calc(100% - 60px);
  }

  .bubble {
    font-size: 14px;
  }
}
</style>
