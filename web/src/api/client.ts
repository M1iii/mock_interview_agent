import type {
  CreateSessionRequest,
  EmbeddingConfig,
  EmbeddingConfigRequest,
  KbFile,
  KeyInfo,
  KnowledgeBase,
  MessagesResponse,
  ReportInfo,
  Resume,
  SSEEvent,
  SessionMeta,
} from './types'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init)
  if (!resp.ok) {
    let detail = `请求失败（HTTP ${resp.status}）`
    try {
      const body = await resp.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      // 非 JSON 响应，保留默认信息
    }
    throw new ApiError(resp.status, detail)
  }
  return (await resp.json()) as T
}

export async function listSessions(): Promise<SessionMeta[]> {
  return request<SessionMeta[]>('/api/sessions')
}

export async function createSession(req: CreateSessionRequest): Promise<SessionMeta> {
  return request<SessionMeta>('/api/sessions', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(req),
  })
}

export async function deleteSession(id: string): Promise<void> {
  await request(`/api/sessions/${id}`, { method: 'DELETE' })
}

export async function getSessionMessages(id: string): Promise<MessagesResponse> {
  return request<MessagesResponse>(`/api/sessions/${id}/messages`)
}

export async function getApiKey(): Promise<KeyInfo> {
  return request<KeyInfo>('/api/settings/api-key')
}

export async function setApiKey(apiKey: string): Promise<KeyInfo> {
  return request<KeyInfo>('/api/settings/api-key', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ api_key: apiKey }),
  })
}

export async function getVerifyKey(): Promise<KeyInfo> {
  return request<KeyInfo>('/api/settings/verify-key')
}

export async function setVerifyKey(verifyKey: string): Promise<KeyInfo> {
  return request<KeyInfo>('/api/settings/verify-key', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ verify_key: verifyKey }),
  })
}

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return request<KnowledgeBase[]>('/api/knowledge')
}

export async function createKnowledgeBase(name: string): Promise<KnowledgeBase> {
  return request<KnowledgeBase>('/api/knowledge', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name }),
  })
}

export async function uploadKnowledgeFile(kbId: string, file: File): Promise<{ file: KbFile }> {
  const form = new FormData()
  form.append('file', file)
  return request<{ file: KbFile }>(`/api/knowledge/${kbId}/files`, {
    method: 'POST',
    body: form,
  })
}

export async function retryKnowledgeFile(kbId: string, recordId: string): Promise<{ file: KbFile }> {
  return request<{ file: KbFile }>(`/api/knowledge/${kbId}/files/${recordId}/retry`, {
    method: 'POST',
  })
}

export async function deleteKnowledgeBase(kbId: string): Promise<{ deleted: number }> {
  return request<{ deleted: number }>(`/api/knowledge/${kbId}`, { method: 'DELETE' })
}

export async function listResumes(): Promise<Resume[]> {
  return request<Resume[]>('/api/resumes')
}

export async function uploadResume(file: File): Promise<{ resume: Resume }> {
  const form = new FormData()
  form.append('file', file)
  return request<{ resume: Resume }>('/api/resumes', { method: 'POST', body: form })
}

export async function deleteResume(id: string): Promise<void> {
  await request(`/api/resumes/${id}`, { method: 'DELETE' })
}

export async function retryResume(id: string): Promise<{ resume: Resume }> {
  return request<{ resume: Resume }>(`/api/resumes/${id}/retry`, { method: 'POST' })
}

export async function getEmbeddingConfig(): Promise<EmbeddingConfig> {
  return request<EmbeddingConfig>('/api/settings/embedding')
}

export async function setEmbeddingConfig(req: EmbeddingConfigRequest): Promise<EmbeddingConfig> {
  return request<EmbeddingConfig>('/api/settings/embedding', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(req),
  })
}

export async function finishSession(id: string): Promise<ReportInfo> {
  return request<ReportInfo>(`/api/sessions/${id}/finish`, { method: 'POST' })
}

export async function getReportContent(id: string): Promise<ReportInfo> {
  return request<ReportInfo>(`/api/sessions/${id}/report`)
}

export async function downloadReport(id: string): Promise<void> {
  const info = await request<ReportInfo>(`/api/sessions/${id}/report`)
  const blob = new Blob([info.report], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `interview_report_${id.slice(0, 8)}.md`
  a.click()
  URL.revokeObjectURL(url)
}

export interface ChatOptions {
  answer?: string
  action?: 'hint' | 'skip'
}

/**
 * POST + SSE 流式对话（EventSource 不支持 POST，用 fetch ReadableStream 解析）。
 * 事件协议：token / done / error / heartbeat。
 * body：{ answer } 提交回答；{ action: 'hint' } 请求提示；{ action: 'skip' } 跳过此题。
 */
export async function chatStream(
  sessionId: string,
  options: ChatOptions,
  onEvent: (e: SSEEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`/api/chat/${sessionId}`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(options),
    signal,
  })
  if (!resp.ok || !resp.body) {
    throw new ApiError(resp.status, `对话请求失败（HTTP ${resp.status}）`)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let eventName = 'message'

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''

    for (const frame of frames) {
      let data = ''
      for (const line of frame.split('\n')) {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          data += line.slice(5).trim()
        }
      }
      if (!data) continue
      try {
        const payload = JSON.parse(data) as Record<string, unknown>
        onEvent({ event: eventName, ...payload } as SSEEvent)
      } catch {
        onEvent({ event: eventName, message: String(data) } as SSEEvent)
      }
    }
  }
}
