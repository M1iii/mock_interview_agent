<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadReport, getReportContent, listSessions } from '../api/client'
import type { ReportSummary, SessionMeta } from '../api/types'

const route = useRoute()
const router = useRouter()

const sessionId = String(route.params.id)
const report = ref('')
const summary = ref<ReportSummary | null>(null)
const session = ref<SessionMeta | null>(null)
const loading = ref(true)
const error = ref('')

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function inline(s: string): string {
  return s
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
}

function splitRow(row: string): string[] {
  const trimmed = row.trim().replace(/^\||\|$/g, '')
  return trimmed.split('|').map((c) => c.trim())
}

function isSeparatorRow(row: string): boolean {
  return /^[\s|:|-]+$/.test(row.trim())
}

/** 轻量 Markdown 渲染：标题/列表/表格/粗体/行内代码/分隔线/段落（已 HTML 转义）。 */
function renderMarkdown(src: string): string {
  const lines = src.split('\n')
  let html = ''
  let listType = ''
  let tableRows: string[] = []

  const flushList = () => {
    if (listType) {
      html += `</${listType}>`
      listType = ''
    }
  }

  const flushTable = () => {
    if (tableRows.length === 0) return
    flushList()
    const rows = tableRows
    tableRows = []
    const isTable = rows.some((r) => r.trim().startsWith('|')) && rows.length >= 2
    if (!isTable) {
      html += `<p>${inline(escapeHtml(rows.join(' ')))}</p>`
      return
    }
    const headIdx = 1
    const sepIdx = isSeparatorRow(rows[headIdx]) ? headIdx : -1
    const headCells = splitRow(rows[0])
    html += '<div class="md-table-wrap"><table>'
    html += `<thead><tr>${headCells.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead>`
    html += '<tbody>'
    for (let i = sepIdx === -1 ? 1 : 2; i < rows.length; i++) {
      const cells = splitRow(rows[i])
      html += `<tr>${cells.map((c, j) => `<td>${inline(c) || '&nbsp;'}</td>`).join('')}</tr>`
    }
    html += '</tbody></table></div>'
  }

  for (const raw of lines) {
    if (raw.trim().startsWith('|')) {
      tableRows.push(raw)
      continue
    }
    flushTable()

    const line = escapeHtml(raw)
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    if (heading) {
      flushList()
      const level = heading[1].length
      html += `<h${level}>${inline(heading[2])}</h${level}>`
      continue
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      if (listType !== 'ul') {
        flushList()
        html += '<ul>'
        listType = 'ul'
      }
      html += `<li>${inline(line.replace(/^\s*[-*+]\s+/, ''))}</li>`
      continue
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      if (listType !== 'ol') {
        flushList()
        html += '<ol>'
        listType = 'ol'
      }
      html += `<li>${inline(line.replace(/^\s*\d+[.)]\s+/, ''))}</li>`
      continue
    }
    if (/^\s*[-*_]{3,}\s*$/.test(line)) {
      flushList()
      html += '<hr/>'
      continue
    }
    if (line.trim() === '') {
      flushList()
      continue
    }
    flushList()
    html += `<p>${inline(line)}</p>`
  }
  flushTable()
  flushList()
  return html
}

const rendered = computed(() =>
  renderMarkdown(report.value.replace(/```json[\s\S]*?```/g, '')),
)

const scorePct = computed(() => Math.min(100, Math.max(0, summary.value?.total_score ?? 0)))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const resp = await getReportContent(sessionId)
    report.value = resp.report
    summary.value = resp.summary ?? null
  } catch (e) {
    error.value = e instanceof Error ? e.message : '报告加载失败'
  } finally {
    loading.value = false
  }
}

async function loadMeta() {
  try {
    const list = await listSessions()
    session.value = list.find((s) => s.id === sessionId) ?? null
  } catch {
    session.value = null
  }
}

async function handleDownload() {
  try {
    await downloadReport(sessionId)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '导出失败'
  }
}

function goHome() {
  router.push('/')
}

onMounted(() => {
  void loadMeta()
  void load()
})
</script>

<template>
  <div class="page report">
    <header class="report-header">
      <button class="btn btn-ghost" @click="goHome">← 会话列表</button>
      <div class="report-title">
        <h1 class="page-title">面试报告</h1>
        <p v-if="session" class="page-sub">
          {{ session.title }} · {{ session.question_count }} 题
        </p>
      </div>
      <div class="report-actions">
        <button class="btn" @click="handleDownload">下载 Markdown</button>
        <button class="btn btn-primary" @click="goHome">再面试一次</button>
      </div>
    </header>

    <div v-if="loading" class="state-hint">报告加载中…</div>

    <div v-else-if="error" class="card error-card">
      <p>{{ error }}</p>
      <button class="btn btn-primary" @click="goHome">返回会话列表</button>
    </div>

    <article v-else class="report-body">
      <div v-if="summary" class="summary">
        <div class="summary-head">
          <div
            class="score-ring"
            :style="{ background: `conic-gradient(var(--soft-accent) ${scorePct}%, oklch(90% 0.015 280) 0)` }"
          >
            <div class="score-ring-inner">
              <b>{{ summary.total_score }}</b>
              <span>总分</span>
            </div>
          </div>
          <div class="dim-bars">
            <div v-for="(val, key) in summary.dimensions" :key="key" class="dim-bar">
              <span class="dim-bar-name">{{ key }}</span>
              <div class="dim-bar-track">
                <div class="dim-bar-fill" :style="{ width: val + '%' }"></div>
              </div>
              <span class="dim-bar-value">{{ val }}</span>
            </div>
          </div>
        </div>

        <div class="summary-cols">
          <div class="col">
            <h3 class="col-title good">✓ 优点</h3>
            <ul class="col-list">
              <li v-for="(s, i) in summary.strengths" :key="i">{{ s }}</li>
            </ul>
          </div>
          <div class="col">
            <h3 class="col-title warn">○ 待改进</h3>
            <ul class="col-list">
              <li v-for="(w, i) in summary.weaknesses" :key="i">{{ w }}</li>
            </ul>
          </div>
        </div>

        <div v-if="summary.verified && summary.verified.length" class="verify-summary">
          <h3 class="col-title">事实核验</h3>
          <ul class="verify-list">
            <li v-for="(v, i) in summary.verified" :key="i">
              <b>{{ v.question }}</b> — {{ v.reason }}
            </li>
          </ul>
        </div>

        <div v-if="summary.review && summary.review.length" class="review">
          <h3 class="col-title">关键问题回顾</h3>
          <div class="md-table-wrap">
            <table>
              <thead>
                <tr>
                  <th>题目</th>
                  <th>你的回答</th>
                  <th>评语</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(r, i) in summary.review" :key="i">
                  <td>{{ r.question }}</td>
                  <td>{{ r.answer }}</td>
                  <td>{{ r.comment }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="card report-card md" v-html="rendered"></div>
    </article>
  </div>
</template>

<style scoped>
.report-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.report-title {
  flex: 1;
}

.report-actions {
  display: flex;
  gap: 10px;
}

.state-hint {
  text-align: center;
  color: var(--text-2);
  padding: 60px 0;
}

.error-card {
  padding: 40px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  color: var(--text-2);
}

.report-card {
  padding: 36px 40px;
}

.report-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.summary {
  background: var(--soft-surface);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  backdrop-filter: blur(20px) saturate(180%);
  border: 1px solid oklch(100% 0 0 / 0.6);
  border-radius: var(--r-xl);
  box-shadow: var(--soft-shadow-md);
  padding: 32px 36px;
}

.summary-head {
  display: flex;
  align-items: center;
  gap: 36px;
  margin-bottom: 24px;
}

.score-ring {
  width: 120px;
  height: 120px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.score-ring-inner {
  width: 92px;
  height: 92px;
  border-radius: 50%;
  background: var(--soft-surface-solid);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px oklch(55% 0.15 280 / 0.1) inset;
}

.score-ring-inner b {
  font-size: 30px;
  font-weight: 800;
  line-height: 1;
  background: var(--soft-accent-grad);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.score-ring-inner span {
  font-size: 12px;
  color: var(--soft-faint);
  margin-top: 4px;
  font-weight: 500;
}

.dim-bars {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dim-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 13px;
}

.dim-bar-name {
  width: 76px;
  flex-shrink: 0;
  color: var(--text-1);
}

.dim-bar-track {
  flex: 1;
  height: 8px;
  border-radius: var(--r-full);
  background: oklch(90% 0.015 280);
  overflow: hidden;
}

.dim-bar-fill {
  height: 100%;
  border-radius: inherit;
  background: var(--soft-accent-grad);
  transition: width 0.4s var(--ease-out);
}

.dim-bar-value {
  width: 40px;
  text-align: right;
  color: var(--soft-muted);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  font-size: 12px;
}

.summary-cols {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-bottom: 24px;
}

.col-title {
  font-size: 15px;
  font-weight: 700;
  margin: 0 0 10px;
}

.col-title.good {
  color: oklch(52% 0.16 145);
}

.col-title.warn {
  color: oklch(60% 0.15 70);
}

.col-list {
  margin: 0;
  padding-left: 18px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-1);
}

.col-list li {
  margin: 4px 0;
}

.review .md-table-wrap {
  margin-top: 12px;
}

.verify-summary {
  margin-top: 20px;
  border-top: 1px solid var(--border);
  padding-top: 16px;
}

.verify-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}

.verify-list li {
  margin: 4px 0;
}

.verify-list b {
  color: var(--text-1);
  font-weight: 600;
}

@media (max-width: 760px) {
  .summary-head {
    flex-direction: column;
    align-items: flex-start;
    gap: 20px;
  }

  .summary-cols {
    grid-template-columns: 1fr;
  }
}

/* Markdown 渲染样式 */
.md h1,
.md h2,
.md h3 {
  font-weight: 700;
  letter-spacing: -0.01em;
  margin: 1.2em 0 0.5em;
}

.md h1 {
  font-size: 24px;
}

.md h2 {
  font-size: 19px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.md h3 {
  font-size: 16px;
}

.md p {
  font-size: 15px;
  line-height: 1.75;
  color: var(--text-1);
  margin: 0.6em 0;
}

.md ul,
.md ol {
  margin: 0.6em 0 0.6em 1.4em;
  font-size: 15px;
  line-height: 1.75;
}

.md li {
  margin: 4px 0;
}

.md strong {
  font-weight: 700;
}

.md em {
  font-style: italic;
}

.md code {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  padding: 1px 6px;
  border-radius: 4px;
}

.md hr {
  border: none;
  border-top: 1px solid var(--border);
  margin: 1.2em 0;
}

.md-table-wrap {
  overflow-x: auto;
  margin: 0.8em 0;
}

.md table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.md th,
.md td {
  border: 1px solid var(--border);
  padding: 8px 12px;
  text-align: left;
}

.md th {
  background: var(--surface-2);
  font-weight: 600;
}

.md a {
  color: var(--primary);
  text-decoration: underline;
}
</style>
