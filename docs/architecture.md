# AI 面试官 · 架构草案

> 版本：v0.5（P1 步骤 5 澄清：知识库元数据落 SQLite kb.db，后台任务入库 + 切换即重建）
> 状态：草案，随项目迭代；**每次迭代必须在本文件「迭代记录」小节 + CHANGELOG 中记录触发原因、变更内容与验证结果。**
> 全局上下文三文档之一：`docs/prd.md`（需求）· 本文档（架构）· `docs/project-status.md`（进度）。三者任一发生大改动，三份 + CHANGELOG 同步更新。

---

## 1. 总体架构

单进程 Monolith，按层分包，路由薄、领域厚。前端仅渲染与 SSE 接收，不持有业务状态。

```
┌──────────────────────────────────────────┐
│  前端 Vue 3 + Vite（浏览器，127.0.0.1）    │
│  会话列表 / 对话 / 报告 / 环境配置          │
│  SSE 客户端 + REST 客户端                  │
└──────────────────┬───────────────────────┘
                   │ HTTP + SSE（心跳 15s）
┌──────────────────▼───────────────────────┐
│  后端 FastAPI（单进程，绑定 127.0.0.1）    │
│  ┌─────────────┐                         │
│  │ api/ 路由层  │  薄：参数校验/序列化/SSE  │
│  └──────┬──────┘                         │
│  ┌──────▼──────┐                         │
│  │interview/   │  领域层：LangGraph 图    │
│  │ nodes/prompts│  开场/出题/评估追问/报告  │
│  └──────┬──────┘                         │
│  ┌──────▼──────┐  ┌───────────────────┐  │
│  │ llm/        │  │ store/            │  │
│  │ DeepSeek封装 │  │ 会话元数据+checkpointer│
│  └──────┬──────┘  └─────────┬─────────┘  │
│         │                   │            │
│  config/（.env+omegaconf）  │            │
│  logging/（loguru JSON）    │            │
└─────────┼───────────────────┼────────────┘
          │                   │
          ▼                   ▼
   DeepSeek API       MemorySaver（P0 内存）
                       SqliteSaver（P2 interview.db）
```

P1 追加 `retrieval/`（Embedding 抽象 + Qdrant/ES 双路召回客户端，知识库集合绑定 model_id + 维度，切换模型重建索引）；P2 追加 `resume/`（简历解析与题库）。

**P1 关键抽象（2026-09-16 澄清确认，v0.4 范围调整）**：
- `llm/` **不做抽象**：本轮仅支持 DeepSeek（`DeepSeekClient` 保持），LLMProvider 统一客户端方案取消——换供应商的需求当前不存在，不做过度设计。
- `retrieval/embedding.py`：**`EmbeddingProvider` 抽象**（`embed_documents / embed_query / model_id / dimensions`），两个实现：本地 `bge-large-zh-v1.5`（langchain-huggingface 进程内推理；本机亦存在电商问数 TEI 服务，可作为 OpenAI-compatible 端点复用）/ 外部 OpenAI-compatible embedding。知识库绑定 model_id + 维度，查询模型 ≠ 库绑定模型时拒绝；切换触发重建索引；外部 API 展示数据外发提示。
- 文档解析**轻量渐进**（Docling 重依赖后置）：MD/TXT 直接切块、DOCX 用 python-docx、PDF 用 pdfplumber 提取文字层（无文字层提示失败）。
- 检索链路：**仅出题注入**（评估复用出题检索结果做事实校准，不新增检索调用；无引用完全退化纯 LLM 评估）；双路召回（语义 Qdrant + 关键词 ES，默认权重 语义 0.6 / 关键词 0.4，可配置）→ 合并去重 → 相关性阈值 0.6 四级降级（normal/weak/fallback/decline）→ 知识出题 + [1][2] 引用角标 + 出题消息附「知识来源」折叠列表。
- 会话关联知识库：`SessionMeta`/`InterviewState` 增加 `knowledge_base_id`（可空 = 通用题库模式，P0 行为保留）。
- 知识库元数据（v0.5 澄清）：`store/knowledge.py` 以 **SQLite kb.db** 持久化（`knowledge_bases` + `kb_files` 两表）；入库走后台任务（上传即返 processing，轮询至 ready/failed，失败保留原文件可重试）；Embedding 切换即自动重建（确认弹窗 → 后台逐库重嵌入 + 更新绑定 model_id）。

## 2. 目录架构分层

```
mock_interview_agent/
├── pyproject.toml
├── .env                    # API Key（gitignore，不入库）
├── .env.example            # 配置项模板
├── docker-compose.yml      # P1：Qdrant + ES（ik 分词）
├── app/                    # 后端
│   ├── main.py             # FastAPI 入口（挂路由、全局异常、CORS 不开放）
│   ├── api/                # 路由层：只做校验与序列化
│   │   ├── deps.py         # 依赖注入（取 Key、取会话）
│   │   ├── sessions.py     # 会话 CRUD / 列表
│   │   ├── chat.py         # SSE 对话流、全局单流式锁
│   │   ├── config.py       # 环境配置读写（掩码返回）
│   │   └── knowledge.py    # P1：知识库管理（建库/列表/上传/删除级联/重试）
│   ├── interview/          # 领域层：面试编排（核心）
│   │   ├── graph.py        # LangGraph 图定义与编译
│   │   ├── state.py        # InterviewState 定义
│   │   ├── nodes/          # 开场/出题/评估追问/结束报告 节点
│   │   └── prompts/        # 各节点 prompt（含场景差异）
│   ├── llm/                # 基础设施：LLM 接入
│   │   ├── client.py       # DeepSeek 客户端（仅 DeepSeek，本轮不做供应商抽象）
│   │   └── keys.py         # Key 校验（sk-）/掩码/按会话快照取 Key
│   ├── retrieval/          # P1：知识库检索（新目录）
│   │   ├── embedding.py    # EmbeddingProvider 抽象：本地 bge / OpenAI-compatible embedding，维度感知
│   │   ├── qdrant.py       # Qdrant client manager（复用电商问数基建）+ 父子块写入/查询
│   │   ├── es.py           # ES client manager（ik 分词）+ 块正文写入/关键词查询
│   │   ├── ingest.py       # 轻量解析（MD/TXT 直切 / python-docx / pdfplumber）+ 父子切块入库
│   │   └── retrieve.py     # 双路召回 → 合并去重 → 阈值降级 → 引用元数据
│   ├── store/              # 存储抽象
│   │   ├── sessions.py     # 会话元数据（P0 内存 dict / P2 SQLite 表）+ knowledge_base_id（P1）
│   │   ├── checkpointer.py # checkpointer 抽象（P0 MemorySaver / P2 SqliteSaver）
│   │   └── knowledge.py    # P1：知识库元数据（SQLite kb.db：knowledge_bases + kb_files 两表）
│   ├── config.py           # omegaconf 加载 + .env 注入
│   └── logging.py          # loguru 结构化 JSON（ISO8601、耗时明细、慢请求告警）
├── web/                    # 前端（Vue 3 + Vite）
│   ├── src/
│   │   ├── api/            # SSE + REST 客户端
│   │   ├── stores/         # Pinia（仅 UI 状态）
│   │   ├── views/          # 会话列表 / 对话 / 报告 / 配置
│   │   └── components/
│   └── vite.config.ts
└── tests/                  # pytest 自动化验收（N 组标准）
```

依赖方向：`api → interview → llm/store`；`interview` 不依赖 `api`；存储走抽象接口，图代码不感知 P0/P2 实现差异。

## 3. 核心模块

| 模块 | 职责 | 关键约束 |
|---|---|---|
| `api/chat.py` | SSE 事件流（token/heartbeat/done/error）、全局单流式锁 | 不写业务逻辑；流式回复期间拒绝其他会话（N-7） |
| `interview/graph.py` | 图定义：开场 → 出题 → 评估+追问（循环）→ 结束报告 | 节点幂等；状态变更只经 checkpointer |
| `interview/nodes/` | 出题（按场景/题目数量）、评估评分、追问（≤1–2 轮）、报告生成（总分+四维+优缺点） | 评分与提示计数真源在服务端 |
| `llm/client.py` | DeepSeek 客户端：超时/重试/流式/token 用量（本轮仅 DeepSeek，不做抽象） | 超时降级为业务文案（N-3） |
| `llm/keys.py` | Key 校验（`sk-`）、掩码、按会话快照取 Key | 新会话新 Key；进行中沿用旧 Key |
| `retrieval/embedding.py`（P1） | EmbeddingProvider 抽象：本地 bge / OpenAI-compatible embedding，维度感知 | 查询模型必须等于库绑定模型；切换模型触发重建索引；外部 API 展示数据外发提示 |
| `retrieval/retrieve.py`（P1） | 双路召回（Qdrant 语义 + ES 关键词，默认权重 0.6/0.4 可配）→ 合并去重 → 阈值 0.6 四级降级 → 引用元数据 | 单路故障降级 + 告警（R6）；检索耗时打点（N-5/P1-6） |
| `store/checkpointer.py` | checkpointer 抽象：save/get/list/delete | P0 MemorySaver；P2 SqliteSaver 无缝替换 |
| `store/sessions.py` | 会话元数据（标题/场景/状态/时间） | P0 内存；P2 SQLite 表 |
| `config.py` | omegaconf + .env；端口 8000 可配 | Key 不落日志/响应体 |
| `logging.py` | 结构化 JSON；LLM/检索耗时与 token 明细；TTFT>5s 告警 | 日志脱敏 |

## 4. 数据模型

### 4.1 InterviewState（LangGraph 状态，经 checkpointer 存取）

```
InterviewState:
  messages:        list[Message]      # 对话消息序列（唯一真源）
  scene:           "intern"|"fulltime" # 会话创建时固定
  question_count:  int                # 题目数量（5–30，默认 10）
  question_index:  int                # 当前题号（0-based）
  current_question: str | None        # 当前题干
  hints_used:      int                # 当前题已用提示次数（≤1）
  followups:       int                # 当前题已追问轮数（≤2）
  scores:          list[Score]        # 每题评分
  status:          "ongoing"|"finished"
  config:          dict               # 场景/数量/Key 快照（会话级）
  knowledge_base_id: str | None       # P1：关联知识库（None = 通用题库模式）
  retrieval_level: str | None         # P1：本轮出题降级级（normal/weak/fallback/decline）
  citations:       list[Citation] | None  # P1：本轮引用（题干 [1][2] 角标 → 知识来源列表）
Score:
  question, answer, score, comment, dimensions: dict
Citation:
  index, title, source, block_id
```

### 4.2 SessionMeta（会话列表，P0 内存 dict / P2 SQLite 表）

```
SessionMeta:
  id:          str        # thread_id（如 20260916-01）
  title:       str        # 自动生成（场景+第 N 场）
  scene:       str
  status:      "ongoing"|"finished"
  created_at:  datetime
  question_count: int
  knowledge_base_id: str | None   # P1：关联知识库（可空 = 通用题库）
```

P2 的 SQLite 表：`sessions`（SessionMeta）+ LangGraph `SqliteSaver` 的 `checkpoints` 表，两表以 `thread_id` 关联。

### 4.3 知识库（P1，Qdrant + ES 双写）

```
KnowledgeBase:
  id:        str                # 如 kb-20260916-01
  name:      str                # 用户命名（默认文件名）
  files:     list[KbFile]       # 文件条目（状态：processing/ready/failed）
  model_id:  str                # Embedding 模型标识（库绑定）
  dims:      int                # 向量维度（与 model_id 绑定）
  created_at: datetime
KbFile:
  id, name, size, status, error, block_count
块（父子切块）：
  父块 ≤800 字（Qdrant 父块向量 + ES 父块正文 ik 分词）——引用单元
  子块 ≤200 字（Qdrant 子块向量）——召回单元，经父块聚合去重
```

**元数据存储（v0.5 澄清）**：上表元数据由 `store/knowledge.py` 持久化到 **SQLite kb.db**（`knowledge_bases` / `kb_files` 两表，线程安全访问）；原始文件保留在 `data/kb_files/{file_id}/`（R6 失败可重试）；Qdrant/ES 仅存块数据，删除级联由 kb.db 中的 file_id 清单驱动。

## 5. 必须服务端的逻辑

| # | 逻辑 | 原因 |
|---|---|---|
| 1 | LLM API 调用与流式转发 | Key 不落前端；CORS 不开放 |
| 2 | API Key 的存储/校验/掩码 | 安全边界（N-2）；前端仅收掩码值 |
| 3 | LangGraph 状态机与 checkpointer | 会话状态唯一真源；前端刷新可恢复 |
| 4 | 全局单流式并发控制 | N-7 验收；跨会话互斥必须进程内统一裁决 |
| 5 | 评分与报告生成 | LLM 评估调用；数据完整性与防篡改 |
| 6 | 提示次数 / 追问轮次计数 | 业务规则真源，前端展示可能被绕过 |
| 7 | 面试结束判定与状态流转 | 状态机唯一入口 |
| 8 | SSE 心跳与连接生命周期 | 15s 心跳；断连释放单流式锁 |
| 9 | 日志与耗时打点（LLM/检索） | N-5 可观测性；前端无法感知服务端耗时明细 |

前端只允许持有：UI 状态（当前 tab、输入框内容、流式渲染缓冲）与展示用的掩码 Key。

## 6. 架构原则

1. **服务端状态唯一真源**：前端所有业务状态（题目、评分、提示计数、场景）均来自服务端响应。
2. **存储抽象先行**：checkpointer 与会话元数据先定义接口，P0 内存实现、P2 SQLite 实现，图代码零改动切换。
3. **路由薄、领域厚**：api/ 不出现业务规则；面试规则全部在 interview/。
4. **Key 会话级快照**：会话创建时快照 Key，变更不影响进行中会话。
5. **单进程约束**：全局单流式锁为进程内锁；若未来多进程部署需换外部锁（记录为已知扩展点）。

## 7. 迭代记录

| 版本 | 日期 | 触发原因 | 变更内容 | 验证 |
|---|---|---|---|---|
| v0.1 | 2026-09-16 | P0 需求澄清完成，进入执行前的架构定稿 | 初始草案：分层、目录、核心模块、数据模型、服务端边界、原则 | 结构评审（需求对齐：P0 8 项决策 + 边界 5 项 + N-1~N-9 全部覆盖） |
| v0.2 | 2026-09-16 | 用户确认 Embedding 模型可配置（本地 bge-large-zh-v1.5 / 外部 API，方案 A 绑定+重建；外部 API 加数据外发提示） | 总体架构 P1 追加说明补充 Embedding 抽象与 model 绑定/重建；核心模块表新增 `retrieval/embedding.py` 行 | 结构评审：与 PRD F4/F6 及新增 P1-7 验收对齐 |
| v0.3 | 2026-09-16 | P1 需求澄清完成（8 项确认：Docker 环境 / 最小可行集 UI / 仅出题注入 / 阈值 0.6 / 角标+来源折叠 / OpenAI-compatible + 双抽象 / 轻量解析 / 关联库单选可空） | `llm/client.py` 升级为 LLMProvider 抽象（OpenAI-compatible 统一客户端，仅单一协议）；新增 `retrieval/` 目录五模块（embedding/qdrant/es/ingest/retrieve）；InterviewState 与 SessionMeta 增加 knowledge_base_id/retrieval_level/citations；新增 §4.3 知识库数据模型（父子块：父块 ≤800 字引用单元 / 子块 ≤200 字召回单元） | 结构评审：8 项决策全部映射到模块/数据模型；与 PRD F1/F2/F4/F6 及 P1-1~P1-7 对齐 |
| v0.4 | 2026-09-16 | 用户调整 P1 范围：LLM 不做抽象，本轮仅支持 DeepSeek；Embedding 抽象保留（本地 bge / OpenAI-compatible embedding） | 撤销 LLMProvider 抽象：`llm/client.py` 恢复为 DeepSeek 客户端（硬编码供应商，不做过度设计）；EmbeddingProvider 抽象保留并补充说明（本地可走 langchain-huggingface 或复用电商问数 TEI 服务作为 OpenAI-compatible 端点） | 结构评审：与用户调整后决策一致；PRD §7 同步 |
| v0.5 | 2026-09-17 | P1 步骤 5 需求澄清（4 项确认：SQLite 元数据 / 后台任务入库 / 切换即重建 / 先建库多文件） | §1 P1 关键抽象补知识库元数据说明；§2 目录补 `api/knowledge.py` 与 `store/knowledge.py`；§4.3 补元数据存储说明（kb.db 两表 + 原始文件保留 + 级联删除驱动） | 结构评审：与 PRD §7 P1 澄清 4 项对齐；`store/knowledge.py` 映射 §4.3 模型 |

---
*已知扩展点（暂不实现，记录原因备用）：多进程部署（需外部单流式锁）、MySQL 升级（批量筛候选人时）、多用户隔离（偏离单机本地边界）。*
