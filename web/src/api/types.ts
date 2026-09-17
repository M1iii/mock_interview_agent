export type Scene = 'intern' | 'fulltime'

export type SessionStatus = 'ongoing' | 'finished'

export interface SessionMeta {
  id: string
  title: string
  scene: Scene
  status: SessionStatus
  question_count: number
  created_at: string
  message_count: number
  question_index: number
  kb_id?: string
  resume_id?: string
  interview_type?: InterviewType
}

export interface CreateSessionRequest {
  scene: Scene
  question_count?: number
  skip_opening?: boolean
  kb_id?: string
  resume_id?: string
  interview_type?: InterviewType
}

export interface Citation {
  file_name: string
  text: string
  score: number
}

export interface KeyInfo {
  masked_key: string
  is_set: boolean
}

export type KbFileStatus = 'processing' | 'ready' | 'failed'

export interface KbFile {
  id: string
  kb_id: string
  file_id: string
  name: string
  size: number
  status: KbFileStatus
  error: string | null
  block_count: number | null
  created_at: string
}

export interface KnowledgeBase {
  id: string
  name: string
  model_id: string
  dims: number
  created_at: string
  files: KbFile[]
}

export type InterviewType = 'technical' | 'behavioral' | 'comprehensive'
export type ResumeStatus = 'processing' | 'ready' | 'failed'

export interface Resume {
  id: string
  file_name: string
  size: number
  status: ResumeStatus
  error: string | null
  point_count: number | null
  created_at: string
}

export interface Verification {
  status: 'verified' | 'uncertain' | 'unconfirmed'
  reason: string
  claims: string[]
  sources: { title: string; url: string; snippet: string }[]
  skipped: boolean
}

export interface EmbeddingConfig {
  provider: 'local' | 'external'
  base_url: string
  model_id: string
  dims: number
  timeout: number
  masked_api_key: string
  available: boolean
  rebuilding?: boolean
}

export interface EmbeddingConfigRequest {
  provider: 'local' | 'external'
  base_url: string
  api_key: string
  model_id: string
  dims: number
  timeout: number
}

export interface ReportSummary {
  total_score: number
  dimensions: Record<string, number>
  strengths: string[]
  weaknesses: string[]
  review: { question: string; answer: string; comment: string }[]
  verified: { question: string; reason: string }[] | null
}

export interface ReportInfo {
  report: string
  status: string
  summary: ReportSummary | null
}

export interface MessageItem {
  role: 'ai' | 'user'
  content: string
}

export interface MessagesResponse {
  messages: MessageItem[]
  hints_used: number
  status: SessionStatus
  question_index: number
}

export interface AssessPayload {
  dimensions: Record<string, number>
  comment: string
  score: number
  citations?: Citation[] // Tip 8：本题引用元数据，评估面板展示来源折叠
  verification?: Verification | null
}

export type SSEEvent =
  | { event: 'token'; content: string }
  | { event: 'status'; kind: 'thinking' | 'report'; message?: string }
  | { event: 'done'; node: string; finished?: boolean; question_index?: number }
  | {
      event: 'assess'
      dimensions: Record<string, number>
      comment: string
      score: number
      citations?: Citation[]
      verification?: Verification | null // P2-4：本题事实性核验结论（ChatView 评估面板展示）
    }
  | { event: 'citations'; citations: Citation[] }
  | { event: 'error'; message: string }
  | { event: 'heartbeat' }
