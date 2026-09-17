<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getApiKey, getEmbeddingConfig, setApiKey, setEmbeddingConfig } from '../api/client'
import type { EmbeddingConfig } from '../api/types'

const router = useRouter()

const keyInput = ref('')
const masked = ref('')
const isSet = ref(false)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

const API_KEY_PATTERN = /^sk-/

// ---- Embedding 配置 ----
const emb = ref<EmbeddingConfig | null>(null)
const embForm = ref({
  provider: 'local' as 'local' | 'external',
  base_url: '',
  api_key: '',
  model_id: '',
  dims: 1024,
  timeout: 10,
})
const embSaving = ref(false)
const embError = ref('')
const embSaved = ref(false)
const switchOpen = ref(false)
const switching = ref(false)
const originalModel = ref('')

const LOCAL_PRESET = {
  base_url: 'http://127.0.0.1:8081/v1',
  model_id: 'bge-large-zh-v1.5',
  dims: 1024,
}

const embChanged = computed(
  () =>
    embForm.value.provider !== (emb.value?.provider ?? '') ||
    embForm.value.base_url.trim() !== (emb.value?.base_url ?? '') ||
    embForm.value.model_id.trim() !== (emb.value?.model_id ?? ''),
)

async function load() {
  try {
    const info = await getApiKey()
    masked.value = info.masked_key
    isSet.value = info.is_set
  } catch {
    // 忽略加载失败，保持默认态
  }
  try {
    const cfg = await getEmbeddingConfig()
    emb.value = cfg
    embForm.value = {
      provider: cfg.provider,
      base_url: cfg.base_url,
      api_key: '',
      model_id: cfg.model_id,
      dims: cfg.dims,
      timeout: cfg.timeout,
    }
    originalModel.value = cfg.model_id
  } catch {
    // 保持默认表单
  }
}

onMounted(load)

async function save() {
  const value = keyInput.value.trim()
  if (!value) {
    error.value = '请输入 API Key'
    return
  }
  if (!API_KEY_PATTERN.test(value)) {
    error.value = 'API Key 必须以 sk- 开头'
    return
  }
  saving.value = true
  error.value = ''
  saved.value = false
  try {
    const info = await setApiKey(value)
    masked.value = info.masked_key
    isSet.value = info.is_set
    keyInput.value = ''
    saved.value = true
    setTimeout(() => (saved.value = false), 2500)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

function applyLocalPreset() {
  embForm.value.base_url = LOCAL_PRESET.base_url
  embForm.value.model_id = LOCAL_PRESET.model_id
  embForm.value.dims = LOCAL_PRESET.dims
}

function switchProvider(kind: 'local' | 'external') {
  embForm.value.provider = kind
  if (kind === 'local') applyLocalPreset()
}

function askSaveEmbedding() {
  embError.value = ''
  if (!embForm.value.base_url.trim() || !embForm.value.model_id.trim()) {
    embError.value = '请填写服务地址与模型标识'
    return
  }
  if (!embForm.value.dims || embForm.value.dims < 1) {
    embError.value = '请填写向量维度（正整数）'
    return
  }
  if (embForm.value.provider === 'external' && !embForm.value.api_key.trim()) {
    embError.value = '外部服务需要填写 API Key'
    return
  }
  switchOpen.value = true
}

async function confirmSwitch() {
  switching.value = true
  embError.value = ''
  try {
    const cfg = await setEmbeddingConfig({
      provider: embForm.value.provider,
      base_url: embForm.value.base_url.trim(),
      api_key: embForm.value.api_key.trim(),
      model_id: embForm.value.model_id.trim(),
      dims: Number(embForm.value.dims),
      timeout: Number(embForm.value.timeout) || 10,
    })
    emb.value = cfg
    embForm.value.api_key = ''
    originalModel.value = cfg.model_id
    switchOpen.value = false
    embSaved.value = true
    setTimeout(() => (embSaved.value = false), 3500)
  } catch (e) {
    embError.value = e instanceof Error ? e.message : '保存失败'
    switchOpen.value = false
  } finally {
    switching.value = false
  }
}

function goHome() {
  router.push('/')
}
</script>

<template>
  <div class="page settings">
    <header class="settings-header">
      <button class="btn btn-ghost" @click="goHome">← 返回</button>
      <h1 class="page-title">环境配置</h1>
    </header>

    <div class="card settings-card">
      <h2 class="card-title">LLM API Key</h2>
      <p class="card-desc">
        配置 DeepSeek API Key，用于面试问答生成。Key 仅保存在本地环境，前端与日志均以掩码显示。
      </p>

      <div class="field">
        <label class="label" for="api-key">API Key</label>
        <input
          id="api-key"
          v-model="keyInput"
          class="input key-input"
          type="password"
          placeholder="sk-xxxxxxxxxxxxxxxx"
          autocomplete="off"
        />
        <p class="field-hint">必须以 sk- 开头</p>
      </div>

      <div v-if="isSet" class="current-key">
        <span class="current-label">当前已配置：</span>
        <code class="masked">{{ masked }}</code>
        <span class="ok-badge">已生效</span>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="saved" class="success">保存成功，新会话将使用新的 Key</p>

      <div class="actions">
        <button class="btn btn-primary" :disabled="saving" @click="save">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>
    </div>

    <div class="card settings-card">
      <h2 class="card-title">Embedding 模型</h2>
      <p class="card-desc">
        知识库文档的向量化模型。切换模型后全部知识库索引将自动重建（后台执行，耗时取决于文件数量）。
      </p>

      <div v-if="emb" class="current-key">
        <span class="current-label">当前模型：</span>
        <code class="masked">{{ emb.model_id }}</code>
        <span v-if="emb.available" class="ok-badge">可用</span>
        <span v-else class="off-badge">不可用</span>
        <span v-if="emb.rebuilding" class="warn-badge">重建中</span>
      </div>

      <div class="field">
        <label class="label">提供方式</label>
        <div class="radio-row">
          <label class="radio-item">
            <input v-model="embForm.provider" type="radio" value="local" @change="switchProvider('local')" />
            本地 TEI（bge-large-zh-v1.5）
          </label>
          <label class="radio-item">
            <input v-model="embForm.provider" type="radio" value="external" @change="switchProvider('external')" />
            外部 API
          </label>
        </div>
      </div>

      <p v-if="embForm.provider === 'external'" class="external-notice">
        注意：选择外部服务后，知识库文档内容将发送到外部接口进行向量化。请确认数据外发合规。
      </p>

      <div class="field">
        <label class="label" for="emb-base-url">服务地址（OpenAI-compatible /v1）</label>
        <input
          id="emb-base-url"
          v-model="embForm.base_url"
          class="input"
          placeholder="http://127.0.0.1:8081/v1"
        />
      </div>

      <div class="field">
        <label class="label" for="emb-api-key">API Key（外部服务必填，本地可留空）</label>
        <input
          id="emb-api-key"
          v-model="embForm.api_key"
          class="input key-input"
          type="password"
          placeholder="sk-xxxxxxxxxxxxxxxx"
          autocomplete="off"
        />
      </div>

      <div class="field-row">
        <div class="field">
          <label class="label" for="emb-model">模型标识</label>
          <input id="emb-model" v-model="embForm.model_id" class="input" />
        </div>
        <div class="field">
          <label class="label" for="emb-dims">向量维度</label>
          <input id="emb-dims" v-model.number="embForm.dims" class="input" type="number" min="1" />
        </div>
        <div class="field">
          <label class="label" for="emb-timeout">超时（秒）</label>
          <input id="emb-timeout" v-model.number="embForm.timeout" class="input" type="number" min="1" max="120" />
        </div>
      </div>

      <p v-if="embError" class="error">{{ embError }}</p>
      <p v-if="embSaved" class="success">
        {{ emb?.rebuilding ? '已保存，正在后台重建全部知识库索引…' : '已保存' }}
      </p>

      <div class="actions">
        <button class="btn btn-primary" :disabled="!embChanged || embSaving" @click="askSaveEmbedding">
          {{ embSaving ? '保存中…' : '保存配置' }}
        </button>
      </div>
    </div>

    <div class="card settings-card notes">
      <h2 class="card-title">说明</h2>
      <ul class="note-list">
        <li>变更 Key 后：<b>新会话</b>使用新 Key，进行中的会话沿用旧 Key</li>
        <li>Key 存储于本地 <code>.env</code>（不纳入版本控制）</li>
        <li>日志与前端界面一律以 <code>sk-•••</code> 掩码展示</li>
        <li>未配置 Key 时无法新建面试会话</li>
        <li>Embedding 切换将重建全部知识库（Qdrant 向量 + ES 正文），期间可继续使用</li>
      </ul>
    </div>

    <div v-if="switchOpen" class="modal-mask" @click.self="switchOpen = false">
      <div class="modal card">
        <h3 class="modal-title">切换 Embedding 模型</h3>
        <p class="modal-desc">
          将从 <b>{{ originalModel }}</b> 切换到 <b>{{ embForm.model_id }}</b>，
          全部知识库文件将重新向量化（后台执行）。确定继续吗？
        </p>
        <div class="modal-actions">
          <button class="btn btn-ghost" @click="switchOpen = false">取消</button>
          <button class="btn btn-primary" :disabled="switching" @click="confirmSwitch">
            {{ switching ? '切换中…' : '确认切换并重建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings {
  max-width: 640px;
}

.settings-header {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.settings-header .page-title {
  margin: 0;
}

.settings-card {
  padding: 28px;
  margin-bottom: 20px;
}

.card-title {
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 8px;
}

.card-desc {
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.6;
  margin-bottom: 20px;
}

.key-input {
  font-family: 'JetBrains Mono', Consolas, monospace;
}

.field-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-3);
}

.current-key {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  font-size: 14px;
}

.current-label {
  color: var(--text-2);
}

.masked {
  font-family: 'JetBrains Mono', Consolas, monospace;
  background: var(--surface-2);
  border: 1px solid var(--border);
  padding: 2px 10px;
  border-radius: 6px;
  color: var(--text-1);
}

.ok-badge {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--r-full);
  background: #dcfce7;
  color: #15803d;
}

.error {
  color: var(--danger);
  font-size: 13px;
  margin-top: 14px;
}

.success {
  color: var(--success);
  font-size: 13px;
  margin-top: 14px;
}

.actions {
  margin-top: 20px;
}

.note-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.6;
}

.note-list code {
  font-family: 'JetBrains Mono', Consolas, monospace;
  background: var(--surface-2);
  padding: 1px 6px;
  border-radius: 4px;
}
</style>
