# P2 设计定稿 · 简历解析与题库 + 跨重启持久化 + web_verify

> 日期：2026-09-17 ｜ 状态：设计已确认（用户批准），待转实施计划
> 上游文档：`docs/prd.md`（§2 P2 范围 / §4 F3·F5 / §6 P2-1~P2-5 / §8 待确认项）、`docs/architecture.md`（§3 模块结构 / §4 存储抽象 / §8 P0/P2 切换点）

---

## 1. 范围

P2 交付五项，退出条件为 P2-1~P2-5 验收通过：

| 编号 | 交付内容 |
|---|---|
| P2-1 | 简历上传（PDF 含文字层 / DOCX ≤20MB）→ 轻量解析 → LLM 结构化抽取 + 考点清单 |
| P2-2 | 出题节点双来源（简历考点清单 + 知识库检索）按面试类型配比混合 |
| P2-3 | 会话元数据 + LangGraph checkpointer 落 SQLite，后端重启后完整恢复 |
| P2-4 | web_verify 事实性陈述联网核验（已核验 / 存疑 / 无法确认 + 信源链接） |
| P2-5 | 端到端链路：上传简历 → 建会话 → 面试 → 报告 |

**不在本期范围**：简历批量筛选、多份简历对比、面试录音/视频、账号体系（沿用 PRD §2 边界）。

---

## 2. 已确认决策（2026-09-17）

| # | 决策点 | 结论 | 理由 |
|---|---|---|---|
| 1 | 出题来源组合 | **按面试类型定配比混合** | 复用现有「面试类型」字段（技术/行为/综合），无新增 UI |
| 2 | 简历解析方案 | **轻量组合（pdfplumber + python-docx）+ LLM 抽取** | 复用 P1 已验证解析链路，零新依赖、无模型下载 |
| 3 | 题库构建方式 | **存结构化简历 + 考点清单（≥10 项），题面由出题节点实时生成** | 持久化「素材」而非「题目」：满足覆盖度可验收，保留实时生成的灵活性 |
| 4 | web_verify 触发时机 | **评估节点自动核验** | 与 R4「事实性回答联网校验」一致，反馈即时 |
| 5 | 联网搜索服务 | **博查 Bocha**（国内备案、中文友好、开发者版限时免费） | 单机本地 + 中文面试场景，国内直连无需代理 |
| 6 | 持久化迁移策略 | **直接替换为 SqliteSaver**（架构文档原计划） | 图代码零改动，路径最干净 |
| 7 | 出题图结构 | **方案 A：单节点内部分支** | 图拓扑保持 5 节点不变，改动面最小 |

---

## 3. 模块结构

```
app/resume/                     ← 新增（architecture §3 已预留）
├── parsers.py                  复用 app/retrieval/parsers.py（pdfplumber + python-docx）
├── extract.py                  LLM 结构化抽取：基本信息 / 技能 / 项目经历 + 考点清单
└── tasks.py                    后台解析任务（仿 retrieval/tasks.py 的 processing→ready/failed 状态机）

app/verify/                     ← 新增
├── bocha.py                    博查 Web Search 客户端（Key 缺失/失败 → 抛可捕获异常）
└── verify.py                   事实性判定 + 核验结论（已核验 / 存疑 / 无法确认）+ 信源

app/store/
├── resume.py                   ← 新增：简历域 SQLite（resumes / resume_points 两表）
├── sessions.py                 ← 改造：内存 dict → SQLite 表
└── checkpointer.py             ← 改造：MemorySaver → SqliteSaver

app/api/resume.py               ← 新增：上传 / 列表 / 删除 / 重试
app/interview/nodes/__init__.py ← 改造：ask_question 双来源分支 + evaluate 接入核验
```

依赖方向不变（`api → interview → llm/store`）；`resume` 与 `verify` 为被 `interview` 依赖的叶子模块。

**单位职责**（各自可独立理解与测试）：

| 单元 | 做什么 | 依赖 |
|---|---|---|
| `resume/parsers` | 文件 → 纯文本（复用 P1） | pdfplumber / python-docx |
| `resume/extract` | 纯文本 → 结构化简历 + 考点清单（LLM） | `llm/client` |
| `resume/tasks` | 编排解析→抽取→落库，维护状态机 | `resume/*`、`store/resume` |
| `store/resume` | 简历域持久化与级联删除 | SQLite |
| `verify/bocha` | 查询 → 搜索结果（标题/URL/摘要） | HTTP |
| `verify/verify` | 回答 + 结果 → 核验结论 | `llm/client`、`verify/bocha` |

---

## 4. 数据模型

三域各自独立，删除级联有据（R5 物理删）：

| 库文件 | 表 | 字段要点 |
|---|---|---|
| `data/resume.db`（新增） | `resumes` | `id` / `file_name` / `path` / `size` / `status`(processing·ready·failed) / `error` / `created_at` / `profile_json`（基本信息·技能·项目经历） |
| `data/resume.db` | `resume_points` | `id` / `resume_id`(FK) / `seq` / `category`(项目·技能·基础) / `title` / `detail` / `source_snippet` |
| `data/interview.db`（新增） | `sessions` | SessionMeta 全字段 + `resume_id`（新增，可空） |
| `data/interview.db` | `checkpoints` 等 | LangGraph `SqliteSaver` 自建表，与 `sessions` 以 `thread_id` 关联 |

设计取舍：
- **考点清单独立成表**（而非 JSON 字段）：`SELECT COUNT(*) FROM resume_points WHERE resume_id=?` 即可支撑 P2-2 的「≥10 项」验收，避免 JSON 解析。
- **`source_snippet` 保留原文片段**：出题时可回溯依据，与 P1 引用标注的「可核对」精神一致。
- **`resumes.profile_json`**：结构化简历整体存 JSON（字段形态灵活、随 LLM 输出演进），清单因需按项检索/计数才拆表。

---

## 5. 出题配比与降级链

`ask_question_node` 内部（方案 A）按会话 `interview_type` 决定本轮走「简历考点清单出题」还是「知识库检索出题」：

| 面试类型 | 知识库 : 简历 | 简历题侧重 |
|---|---|---|
| 技术面 | 7 : 3 | 项目中的技术选型与实现细节 |
| 行为面 | 2 : 8 | 项目经历、协作、难点复盘 |
| 综合面 | 5 : 5 | 均衡 |

- 开场按 `question_count` 换算各类题数并按题号落位（10 题技术面 → 7 知识库 + 3 简历），保证整场配比稳定而非随机漂移。
- **落位规则（明确定义）**：简历题**均匀交错**分散在前中后段（避免后半场集中），取整余数补知识库侧。计数可逐题核对，供 P2-2 验收使用。
- 配比写入配置（可调），不暴露到前端（延续 P1「权重滑块后置」的取向）。
- **降级链**：无简历 → 纯知识库（P1 行为，保持不变）；无知识库 → 纯简历；两者皆无 → P0 通用题库。简历 `status != ready` 时等同于无简历。

---

## 6. web_verify 流程

```
evaluate_node
  ├─ 既有：四维评估 + 追问判断（P0/P1 逻辑不变）
  ├─ 新增判定：本条回答是否含事实性陈述（LLM 结构化输出 is_factual + claims[]）
  │     └─ 否 → 跳过核验
  ├─ 是 → 博查搜索（每条 claim 取 top-3 结果）
  ├─ LLM 二次判定：结合搜索结果输出 已核验 / 存疑 / 无法确认 + 理由
  └─ 结果并入 SSE assess 事件 payload（不新增事件类型）
        → 前端评估面板：核验徽标 + 信源链接（可点击）
        → 报告汇总核验结果
```

**降级与边界**：未配置搜索 Key / 请求失败 / 超时 → 静默跳过核验（不阻断评估，日志 warning）；核验结果标记为「无法确认」时仍展示信源以便用户自查。

配置入口：F6 配置页新增「联网搜索 Key」（博查），可选填；Key 存储沿用既有 KeyStore 会话快照机制。

---

## 7. 验收映射与语料

| 验收项 | 口径（本次修订后） |
|---|---|
| P2-1 | 20 份简历解析成功率 ≥90%；结构化字段抽取正确率 ≥85% |
| P2-2 | 每份简历考点清单 ≥10 项；按配比产生的简历来源题目（技术面 3 道 / 行为面 8 道 / 综合面 5 道），≥80% 与简历考点清单对应且相关 |
| P2-3 | 重启后端进程后，会话列表与对话历史完整恢复（含进行中会话的断点续聊） |
| P2-4 | web_verify 返回信源链接且核验标记正确 |
| P2-5 | 上传简历 → 建会话（关联简历 + 知识库）→ 面试 → 报告，端到端可用 |

语料与脚本（仿 P1 模式）：
- `tests/acceptance/resumes/` 自建 20 份简历（MD / PDF / DOCX 混合，覆盖不同版式与字段完整度）
- `tests/acceptance/resume_gold.json` 预标每份简历的关键字段与考点，作为 P2-1/P2-2 判定依据
- `_acceptance_p2.py` 独立验收脚本（`--only` / `--keep`，全量串行 P2-1~P2-5），不参与 pytest 收集

---

## 8. 需同步修订的文档漂移（3 处）

| 位置 | 现状 | 修订为 |
|---|---|---|
| PRD §4 F3 | 「Docling 解析 → 结构化抽取 → 自动构建题库（≥10 题）」 | 「轻量解析 → LLM 结构化抽取（基本信息/技能/项目经历）+ 考点清单 ≥10 项；题面由出题节点实时生成」 |
| PRD §6 P2-2 | 「每份简历 ≥10 题且 ≥80% 相关」 | 「考点清单 ≥10 项；按配比产生的简历来源题目 ≥80% 与清单对应且相关」（口径需与 §2 决策 3 的实时生成一致，且不与 §5 配比冲突） |
| PRD §6 N-9 | 「上传 ≤10MB」 | 分档：知识库 ≤50MB / 简历 ≤20MB（与 §4 F4·F3 对齐） |

PRD §8 待确认项「P2 web_verify 触发方式」本次已确认，从待确认区移除。

---

## 9. 测试策略

| 层 | 覆盖 |
|---|---|
| 单测 | 解析器（PDF/DOCX/无文字层失败）、LLM 抽取（mock）、考点清单落库与计数、简历删除级联、配比换算与降级链、SqliteSaver 迁移与会话恢复、核验结论判定（mock 搜索）、降级（无 Key / 搜索失败） |
| 集成 | 上传 → 后台任务 → ready 状态轮询；重启后 sessions + checkpoints 恢复（真实 SQLite 文件） |
| 端到端 | `_acceptance_p2.py` 全量串行 P2-1~P2-5（真实服务） |
| 回归 | 全量 pytest + ruff + 前端 build；P1 验收脚本复跑确认无回归 |

**持久化迁移的验证重点**：现有 P0 测试以 MemorySaver 为默认，迁移后需确认 `store/checkpointer.py` 抽象接口未变（图代码零改动），MemorySaver 仅保留为测试 fake。

---

## 10. 风险与已知边界

| 风险 | 说明 | 应对 |
|---|---|---|
| 简历版式多样导致解析失败 | pdfplumber 对双栏/表格版式可能串行 | 无文字层或抽取失败 → `failed` 状态 + 原因展示 + 可重试（沿用 P1 状态机） |
| LLM 抽取字段不稳定 | 同一简历多次抽取结果可能不一致 | `profile_json` 允许缺字段；抽取 prompt 用结构化输出约束；P2-1 判定用关键字段命中率而非逐字一致 |
| 核验引入评估延迟 | 每轮多 1 次搜索 + 1 次 LLM 判定 | 核验在评估后段执行，不阻塞题干流式；失败静默跳过 |
| 博查免费额度 | 开发者版限时免费，超额按量计费 | Key 可选填；未配置即不核验（功能优雅降级） |
| 会话数据落盘后无法「重启即清」 | 单机工具用户可能期望清空 | 会话删除仍为物理删（含 checkpoints），与 R5 一致 |
| 双来源配比在小题目量下失衡 | 如 5 题技术面 → 3.5 知识库题 | 按题号取整分配，余数补知识库侧；配比可配置 |

---

## 11. 实施顺序（供 writing-plans 展开）

1. 存储先行：`store/sessions` 落 SQLite + `store/checkpointer` 换 SqliteSaver（P2-3 主体，图代码零改动）
2. 简历域：`resume/parsers` + `resume/extract` + `resume/tasks` + `store/resume` + `api/resume`（P2-1）
3. 双来源出题：`ask_question_node` 分支 + 配比配置 + 降级链（P2-2）
4. web_verify：`verify/bocha` + `verify/verify` + `evaluate_node` 接入 + 前端展示 + 配置页 Key（P2-4）
5. 端到端与验收：`_acceptance_p2.py` + 语料 + 文档落档（P2-5）
