# AI 面试官 · 项目阶段状态

> 全局上下文三文档之一：`docs/prd.md`（需求）· `docs/architecture.md`（架构）· `docs/project-status.md`（本文档，进度）
> **同步约定：PRD / 架构 / 项目阶段任何一方发生大改动，三份文档必须同步更新，并在 CHANGELOG 记录。**
> 最近更新：2026-09-17

---

## 1. 项目概览

模拟面试 Agent 全栈项目（复用自电商问数项目 shopkeeper-agent 基建）。AI 基于简历 + 知识集进行多轮模拟面试，支持断点续聊。产品名 **AI 面试官**，单机本地工具。

技术栈（详见 `docs/prd.md` §2 与 `docs/architecture.md`）：Vue 3 + Vite / FastAPI + SSE / LangGraph / DeepSeek / bge-large-zh-v1.5 / Qdrant + ES（P1）/ SqliteSaver（P2）/ uv + ruff + loguru + omegaconf。

## 2. 里程碑时间线

| 日期 | 里程碑 | 产出 |
|---|---|---|
| 2026-09-15 | 方向敲定 | 技术决策 12 项锁定（不落文件） |
| 2026-09-15 | PRD V1.0 | `prd/prd.html`（交互原型 + 五章节 + 27 项验收标准） |
| 2026-09-15 | 边界 + 非功能确认 | 概览「项目边界」小节 + N 组扩为 9 条 |
| 2026-09-16 | P0 需求澄清 | 8 项决策确认，产品名「AI 面试官」 |
| 2026-09-16 | 技术栈整理 | PRD「技术方案」章节补全 + 存储三块划分 |
| 2026-09-16 | 架构草案 v0.1 | `docs/architecture.md` |
| 2026-09-16 | 全局上下文三文档 | `docs/prd.md` + `docs/project-status.md` + 互链 |
| 2026-09-16 | Embedding 模型决策 | 本地 / 外部 API 可配置（方案 A 绑定+重建），PRD 新增 P1-7 |

## 3. 当前阶段

**阶段：P2 交付完成 + 端到端验收通过（2026-09-18 复跑确认）——简历解析入库（P2-1）/ 双来源出题（P2-2）/ SqliteSaver 跨重启持久化（P2-3）/ web_verify 事实核验（P2-4）/ 端到端链路（P2-5）全部落地。第 2 轮审查首次暴露的 app 侧缺陷（流式 skip 出题失败）**已修复（`8e2933a`）**，2026-09-18 全量复跑实测：**门禁 passed=14 failed=0（退出码 0）、观察项 1 项 PASS、依赖缺失 dep=0**——原唯一门禁 FAIL「P2-5 skip 推进（无 error 事件）」已转为 PASS；P1-3（28%，标准 ≥90%）与 P1-4 decline 子项搁置项顺延，待真实检索环境恢复后复测（标准未调整）**

P2 交付物：20 份多格式简历语料（15 MD + 2 TXT + 1 DOCX + 2 PDF）+ 金标 `tests/acceptance/resume_gold.json`；验收脚本 `_acceptance_p2.py`（`--only`/`--keep` + 退出码 0/1 + 默认清理验收数据）；后端简历域（解析/抽取/考点清单/双来源出题/持久化/核验）与前端简历页 + 会话关联 + 核验展示。

按用户 3 阶段工作流（需求澄清 → 分步执行 → 验收总结）。P0 已具备执行条件：边界、非功能、8 项产品决策、技术栈、架构草案全部落档。

**实测项延后决策（2026-09-16）**：A-4 浏览器控制台无报错 / N-1 性能 P95 / N-6 浏览器兼容 / P0-2 二十轮串扰与 P0-5 五并发压测，统一留待阶段收尾实测——N-1 待 P1 检索链路稳定后测更准（回复耗时构成将加入检索耗时）；A-4 在 P1 前端开发时随手自查。

**P2 收尾环境偏差（2026-09-17 首记，2026-09-18 复跑复核）**：P2 验收期间 Qdrant(6333)/ES(9200)/TEI(8081) 均未监听（Docker Desktop 未运行；沙箱内无法启动 Docker Desktop，其数据目录访问被拦截），2026-09-18 复跑前再次探测三项仍为 False，故 P2-1~P2-5 全部在不依赖检索服务的路径下完成（P2 五项本身不要求真实检索；P2-5 的 kb 参数在缺失时被显式省略并静默降级）；**P2-5 的事实核验为真实触发**（自设占位 verify-key + `BochaClient.search` 补丁，走通 LLM 判定 → 搜索 → 二次判定全链路，不依赖检索服务）；**P1 验收脚本复跑因此仍无法执行**，P1 侧回归证据为 pytest 全量（267 例）+ ruff + 前端 build，P1-3/P1-4 既有 FAIL 记录维持不变。

## 4. 已完成事项

- [x] 方向敲定（技术栈 12 项）
- [x] PRD V1.0（交互 HTML）
- [x] 项目边界确认（部署/数据/并发/单用户/Key 存储）
- [x] 非功能 N-1~N-9
- [x] P0 需求澄清 8 项
- [x] 技术栈 + 存储三块落档 PRD
- [x] 架构草案 v0.1
- [x] 全局上下文三文档体系
- [x] Embedding 模型可配置决策（本地 bge / 外部 API，方案 A 绑定+重建 + 外发提示，P1）
- [x] P0 步骤 1：工程脚手架（uv + pyproject + ruff/pre-commit + .env(.example) + 目录骨架，pre-commit 全钩子通过）
- [x] P0 步骤 2：配置 + 日志层（omegaconf 默认值<文件<env 三层合并、.env 注入、loguru 结构化 JSON ISO8601、TTFT>5s 告警、Key 脱敏）
- [x] P0 步骤 3：LLM 客户端（DeepSeek 封装：超时/重试/流式/用量打点 + keys.py Key 校验掩码与会话级快照）
- [x] P0 步骤 4a：InterviewState + 图骨架（5 节点 + 条件路由 + 开场白可跳过 + P1/P2 预留字段）
- [x] P0 步骤 4b：节点实现 + prompts（opening 固定文案 / ask_question 实习·全职双版 / evaluate 四维+追问判断 / follow_up / report Markdown，prompt 待 P1 RAG 后优化）
- [x] P0 步骤 5：SSE 接口（chat.py 流式端点 + 全局单流式锁 + 心跳 15s + token/heartbeat/done/error 四事件）
- [x] P0 步骤 6a/6b：会话管理（sessions CRUD + settings Key 配置 + KeyStore 会话快照 + checkpointer thread_id 恢复 + 首次调用初始化）
- [x] P0 步骤 7：报告生成（提前结束 `POST /finish` + 导出 `GET /report` + 图拓扑缺陷修复——`route_after_start` 按 `current_question` 路由到 evaluate）
- [x] P0 步骤 8a-8f：Vue 3 前端四页面（会话列表/对话 SSE/配置/报告 + vue-router + API 封装层 + Soft UI 紫色主题）
- [x] P0 步骤 8g：联调收尾（hint 每题限 1 次 / skip 推进题号+末题生成报告 / skip_opening 开关；FastAPI 托管 dist + SPA 兜底；修复 2 个真 bug：首次调用开场白丢失、skip 后题号未写回 checkpointer）
- [x] P0 真实 LLM 冒烟联调：完整主流程 9 步全通；修复 2 个真实调用缺陷（`stream_options` 仅限流式、`complete_sync` 跨事件循环）
- [x] P0 步骤 8g 续·流式改造：题干/追问逐 token 流式输出（`TokenStreamHandler` 回调转发 + run 树溯源节点名 + 「【主题】」标记截断）；报告「生成中占位 + 一次性输出」；新增 `GET /sessions/{id}/messages` 历史消息接口（刷新可续聊）；113 例 pytest 通过
- [x] P0 步骤 8g 续·H1~H5 需求对齐缺口：右侧评估面板（SSE `assess` 事件实时下发维度/评语/得分）+ 题目进度条（当前题/总数）+ 会话列表筛选与进度字段 + 报告结构化可视化（环形图/维度条/双栏优缺点/回顾表，缺摘要时降级 Markdown）+ 多行输入 textarea；117 例 pytest 通过
- [x] L1~L3 视觉细节对齐：消息气泡头像对称（AI/我）+ 时间戳 + 对话页状态徽标与场景 chip + 会话列表显式操作按钮
- [x] M1~M4 后续任务计划入档（`docs/project-status.md` §6.5，执行前逐项澄清授权）
- [x] P0 步骤 9 验收核对：对照 PRD P0-1~P0-8 + A-1~A-5 + N-1~N-9 全量检查——功能层全部完成且多项超额（assess 事件/历史消息接口/thinking 占位/会话级 Key 快照/H4 报告可视化等）；N-4 属 P1、N-2/N-9 上传校验属 P1/P2（P0 无上传功能）；4 项实测类待运行环境验证（A-4 浏览器控制台、N-1 性能 P95、N-6 浏览器兼容、P0-2 二十轮串扰与 P0-5 五并发的专项压测）
- [x] N-8 缺口修复：`delete_session` 三处同步物理删（SessionStore + KeyStore + checkpointer）；`delete_thread` 由 no-op 改为真实调用 `MemorySaver.delete_thread`（langgraph 1.x per-thread 接口），P2 SqliteSaver 无缝替换
- [x] 实测项延后决策：A-4 / N-1 / N-6 / P0-2·P0-5 压测统一留待阶段收尾实测（见 §3），进入 P1 需求澄清
- [x] P1 需求澄清完成（8 项确认）：Docker 环境（docker-compose 起 Qdrant+ES）/ 知识库 UI 最小可行集 / 仅出题注入 / 降级阈值 0.6 / 引用角标+来源折叠 / OpenAI-compatible 双抽象 / 轻量解析 / 关联知识库单选可空 → 落档 PRD §7 + 架构 v0.3
- [x] P1 步骤 1（基建）：docker-compose.yml（Qdrant v1.12.4 + ES 7.17.10 ik 分词 Dockerfile，healthcheck + 数据卷）；`app/retrieval/` 目录（`__init__.py` 定义 RetrievalUnavailable + `qdrant.py`/`es.py` 懒加载 manager：is_available 探测结果缓存 30s + get_client 降级抛错）；`app/config.py` 新增 retrieval 配置节（urls/超时/es_index/语义权重 0.6/阈值 0.6/top_k 5 + env 覆盖）；main.py lifespan 挂载 manager（不探测不阻塞）；.env.example 补 retrieval 项；125 例 pytest + ruff + docker compose config 验证通过
- [x] P1 步骤 4（解析 + 入库）：`app/retrieval/parsers.py`（MD/TXT/DOCX/PDF 轻量解析）+ `chunking.py`（混合父子切块：段落→句子→滑动窗口兜底→overlap 补偿→父块聚合 ≤800 字）+ `ingest.py`（按文件路径哈希幂等重建，Qdrant 子块向量 + ES 父块正文 ik 双写）；qdrant/es 新增 ensure_collection/ensure_index；config 新增 chunking 节；154 例 pytest + ruff 全通过 + 真实环境冒烟（含幂等）→ 踩坑 #15-17
- [x] P1 步骤 5 需求澄清完成（4 项确认）：知识库元数据存 SQLite kb.db / 入库后台任务 + 状态轮询 / Embedding 切换即自动重建（确认弹窗）/ 先建库后传文件（一库多文件）→ 落档 PRD §7 + 架构 v0.5
- [x] P1 步骤 5（知识库管理 API + UI）：`store/knowledge.py`（SQLite kb.db 两表 + 状态机 + 绑定 model_id）+ `api/knowledge.py`（建库/列表/上传 ≤50MB 后台入库/重试/删除级联，检索缺失降级）+ `retrieval/tasks.py`（后台入库 + 切换重建）+ `api/settings.py` GET/PUT /settings/embedding + 前端知识库页与配置页 Embedding 区块；183 例 pytest + ruff + 前端 build 全通过，新增 29 例（store 16 / API 12 / tasks 3）
- [x] P1 步骤 6（检索服务）：`app/retrieval/retrieve.py`——双路召回（Qdrant 语义 + ES 关键词 ik）→ 方案 B 合并（双路命中 min-max 归一化加权和 / 单路命中 fallback）→ 四级降级（normal/weak/fallback/decline）→ 引用元数据 + 耗时打点；同步补入库端 kb_id/file_name 字段 + ES mapping 升级 + Qdrant query_points API；200 例 pytest + 真实服务冒烟通过（单查询 ~150ms，远低于 P1-6 P95≤2s）
- [x] P1 步骤 7（出题节点改造）：仅出题注入——`ask_question_node` 接入 `RetrievalContext`（会话 kb_id 时检索，查询词已问主题延续/首题场景默认词）+ 参考资料区块注入 prompt（`{reference_block}` 占位，无命中完全退化）+ 四级降级出题（normal/weak 知识出题 / fallback 弱提示语 / decline 纯通用）+ 题干 `[n]` 角标 + SSE `citations` 事件 + 前端引用来源折叠列表 + 新建会话关联知识库（下拉可选）；211 例 pytest + ruff + 真实服务冒烟通过（`_smoke_tip7.py`）
- [x] P1 步骤 8（答案增强）：评估节点复用出题检索结果（方案 A：检索仍仅出题节点，不新增调用）+ 取向 1（知识库优先、自身知识兜底）事实校准——评语 `[n]` 角标 + SSE `assess` 事件携带 citations + 右侧评估面板引用来源折叠；无 kb/decline 完全退化为纯 LLM 评估；217 例 pytest + ruff + 前端 build 通过
- [x] P1 验收执行（2026-09-17）：自建 5 篇多栈 MD 语料（50 考点）+ 50 题预标出处题库 + 独立脚本 `_acceptance_p1.py` 全量串行，实测 **passed=11 failed=3**——P1-1 入库 5/5=100%、P1-2 召回 50/50=100%、P1-5 删除级联三处 0 拋留、P1-6 P95=134ms、P1-7 切换重建（ok=5/绑定一致/抽样 5/5）通过；**FAIL 3 项**：P1-3 引用准确率 12%（引用文本取命中子块→大量裸 Markdown 标题，应用缺陷）、P1-4 decline 子项（语义路无相似度截断→decline 在 Qdrant 在线时不可达，应用缺陷）、P1-7 观察项（查询模型≠绑定模型拒绝校验未实现，记录型 FAIL）；验收报告 `docs/acceptance/p1-acceptance-report.md`
- [x] P1-3 引用上卷修复 + P1-4 降级阈值调优（2026-09-17）：`retrieve.py` 新增 `_backfill_parent_text`（语义路命中后按 parent_id mget ES 父块全文，失败回退子块文本）；`nodes/__init__.py` `_SNIPPET_LEN` 120→0（不截断，父块全文≤800 字直接注入 prompt）；`config.py` 新增 `score_threshold=0.0`（Qdrant 不过滤）+ `min_should_match=25%`（ES 泛匹配过滤）；223 例 pytest + ruff + 前端 build 全通过。复测结果：P1-3 从 12%→28%（judged=50/50，cites=40/144）、P1-4 前 3 子项 PASS（双路 normal/语义 fallback/关键词 fallback）、decline 子项仍 FAIL（score_threshold=0 不过滤→无关查询仍返回 top-k 命中）。**P1-3 28% 与 P1-4 decline 子项按用户裁决搁置，待 P2 完成后排查文档/题库质量 + 重新设计降级策略后复测**

- [x] P2 设计定稿 + 11 任务实施计划（2026-09-17）：`docs/superpowers/specs/2026-09-17-p2-resume-persistence-design.md` + `docs/superpowers/plans/2026-09-17-p2-resume-persistence-plan.md`——简历解析 + 考点清单 / 双来源出题配比 / SqliteSaver 持久化 / web_verify / 前端三页；含 Task 3/6 前置修正（ResumeStore 建表顺序）
- [x] P2 Task 1：依赖 + 配置扩展（2026-09-17）：新增 `langgraph-checkpoint-sqlite` 依赖；`app/config.py` 增 `interview.db` / `resume.*`（db、upload_dir、max_upload_mb=20、ratio 三档） / `verify.*` 配置节 + 环境变量覆盖（`INTERVIEW_DB` / `RESUME_DB` / `RESUME_UPLOAD_DIR` / `RESUME_MAX_MB` / `RESUME_RATIO_*` / `VERIFY_*`）；`.env.example` 同步补项
- [x] P2 Task 2：会话元数据落 SQLite（2026-09-17）：`app/store/sessions.py` 新增 `SqliteSessionStore`（sessions 表含 `interview_type` / `resume_id`）；lifespan 改用 SQLite 存储；会话 Key 快照缺失时回退全局 Key（支撑重启后续聊）
- [x] P2 Task 3：checkpointer 换 SqliteSaver（2026-09-17）：`app/store/checkpointer.py` 传 cfg 时返回 `SqliteSaver`（与会话元数据同库 interview.db 异表），无 cfg 回退 `MemorySaver`；`delete_thread` 级联删除仍生效（N-8）
- [x] P2 Task 4：简历域存储（2026-09-17）：`app/store/resume.py`——resumes + resume_points 两表（考点清单独立成表支撑 COUNT 验收），`point_count` 冗余计数，删除级联（FK CASCADE）返回原文件路径供物理删
- [x] P2 Task 5：简历解析 + LLM 结构化抽取（2026-09-17）：`app/resume/parsers.py` 复用 P1 轻量解析（MD/TXT/DOCX/PDF）；`app/resume/extract.py` EXTRACT_PROMPT → basic/skills/projects + 考点清单（≥10 项，含 category/title/detail/source_snippet）
- [x] P2 Task 6：简历后台任务 + 简历 API（2026-09-17，P2-1）：`app/resume/tasks.py`（processing→ready/failed 状态机，失败保留原文件可重试）+ `app/api/resume.py`（上传 ≤20MB，md/txt/docx/pdf；列表 / 重试 / 删除级联物理删）
- [x] P2 Task 7：双来源出题（2026-09-17，P2-2）：`app/interview/ratio.py`（`resume_question_indices` 配比落位：技术面 3 / 行为面 8 / 综合面 5，按 10 题计）+ `ask_question_node` 简历题/知识库题分支 + 降级链（简历不可用→知识库→纯通用）
- [x] P2 Task 8：web_verify 后端（2026-09-17，P2-4）：`app/verify/bocha.py`（博查 Web Search 客户端，Key 缺失/网络异常抛 `BochaError`）+ `app/verify/verify.py`（LLM 事实性判定 → 搜索 → LLM 二次判定三态 verified/uncertain/unconfirmed）+ `evaluate_node` 接入 + `PUT/GET /api/settings/verify-key`；未配置 Key / 失败一律静默降级不阻断评估
- [x] P2 Task 9：前端·简历管理页 + 会话关联（2026-09-17，P2-1/P2-2 UI）：`web/src/views/ResumeView.vue`（上传/状态轮询/重试/删除）+ ChatView 新建会话支持面试类型与简历下拉 + `api/client.ts` 简历接口；轮询对齐 KnowledgeView 模式（setInterval + 卸载清理）
- [x] P2 Task 10：前端·核验展示 + 搜索 Key 配置 + 报告汇总（2026-09-17，P2-4 UI）：评估面板核验徽标与信源列表 + 配置页搜索 Key 区块 + 报告页核验汇总（`ReportSummary.verified` 类型修正为 `{question, reason}[]`，由系统在摘要解析后填充）
- [x] P2 Task 11：端到端验收 + 语料 + 文档落档（2026-09-17，P2-5）：20 份多格式简历语料（15 MD + 2 TXT + 1 DOCX + 2 PDF，手写最小合法 PDF 文字层）+ 金标 `tests/acceptance/resume_gold.json`（20 stem：file_name/name/skills≥5/points≥10）+ 独立验收脚本 `_acceptance_p2.py` + PRD 四处漂移修订（含 §8 清空，`docs/prd.md` 5 处改动）随提交 `20216a5`（`feat(p2): acceptance corpus/script P2-1~P2-5, doc drift fixes, changelog`）纳入版本控制并逐条核验 + CHANGELOG / 本文档落档
- [x] P2 端到端验收执行（2026-09-17，首轮）：`uv run python _acceptance_p2.py` → **passed=12 failed=0（退出码 0）**：P2-1 解析成功率 20/20=100%、字段命中 20/20=100%、考点清单落表一致；P2-2 考点清单 ≥10 全通过、配比复算 [1,4,7]/[1,2,3,4,6,7,8,9]/[1,3,5,7,9]、简历来源题干含考点关键词 38/40=95%（题干命中 3/3）；P2-3 会话记录 + 对话历史（同库重建）恢复；P2-4 事实核验 status=verified（3 claims / 6 sources）+ 未配置 Key 跳过（verification=null）；P2-5 端到端（报告 1402 字符 + 结构化摘要 dict + GET /report 200）；**本次无 FAIL 项**（详见 CHANGELOG 顶部条目）
- [x] P2 验收审查修复（2026-09-17，第 1 轮，F3/F4/F6/F7 + limitation 落档）：**F3** P2-5 自设占位 verify-key + `BochaClient.search` 补丁，第 1 题真实走通 VerifyContext 全链路（新增独立断言项），报告断言补强为「含『面试报告』+ `_report_summary` 5 键齐全 + total_score 0–100 + 四维键齐全」，`finally` 还原补丁与 Key；**F4** P2-4 未配置 Key 对照组复用同一条 answer + 旁证 `GET verify-key → is_set=False`；**F6** 本次上传 resume_id 显式记录，P2-1/P2-2/P2-5 只使用本次上传 id，清理只删本次上传的记录与文件；**F7** 更正 CHANGELOG/本文档中 PRD 修订的表述（原文与实际提交 `docs/prd.md` 5 处改动不符）；**F1/F2/F5/F8** 落档为 §5 limitation。复跑 `_acceptance_p2.py` → **passed=13 failed=0**（P2-1 19/20=95%[首份 LLM 抽取超时，非应用缺陷] / P2-2 注入链路一致性 40/45=89% / P2-4 同一 answer 对照 / **P2-5 核验 status=verified、claims 3、sources 6**、报告 1864 字符 + 摘要四维齐全）；`pytest 266` + `ruff` 全通过；未改任何 `app/` 代码
- [x] P2 验收审查修复（2026-09-17，第 2 轮，脚本健壮性 + retry 观察项）：**minor-1** `_scoped_ready` 为空（依赖缺失/用法错误）改记 `kind="dep"`，不计入 failed、不影响退出码（P2-2 考点清单 / P2-2 抽样 / P2-5 三处），SUMMARY 分列门禁/观察/依赖三类；**minor-2** P2-5 skip 循环命中 error 事件先 `report.add` 内容（门禁项）再 break；**minor-3** p2_4/p2_5 五处 `assert` 改「记录 FAIL + 提前 return」+ main 每项兜底 `try/except`（保证总有 SUMMARY 与退出码）；**minor-4** `_check_report_summary` detail 打印原始 `summary`（截断 400 字符）；**minor-5** 「随本提交…纳入版本控制」补 `20216a5` 消歧；**复审建议** 新增 `kind="obs"` 观察项覆盖 `POST /api/resumes/{id}/retry`（无 failed 简历时构造探针）。复跑 `_acceptance_p2.py` → **门禁 passed=13 failed=1 / 观察项 1 PASS / dep 0（退出码 1）**：P2-1 20/20=100% + 字段命中 20/20 + 落表一致；retry 观察项 探针→http 200 / processing→ready 30.5s；P2-2 注入链路一致性 41/45=91%；P2-3 两项；P2-4 核验 verified + 未配置 Key 对照；P2-5 第 1 题核验 verified + 报告 1728 字符四维摘要齐全 + 导出 200；**唯一门禁 FAIL 为 skip 出题 error**——minor-2 新增记录项首次暴露的 app 侧既有缺陷（见 §5「缺陷·流式 skip 出题」）。空库隔离复跑 `--only p2-2 p2-5` → `gate_failed=0 / dep=3`（依赖缺失与真实 FAIL 已分离）；`pytest 266` + `ruff` 全通过；未改任何 `app/` 代码

- [x] **P2 收尾·skip 缺陷修复 + 验收复跑确认（2026-09-18）**：第 2 轮暴露的 app 侧缺陷「跳过非末题后下一题出题失败」**已修复**（`8e2933a`：`app/api/chat.py` skip 分支裸 `handler` → `[handler]`，1 行；根因 `langchain ensure_config` 对 `callbacks` 调 `copy()` 而 `TokenStreamHandler` 无 `copy` → `AttributeError` → `LLMError` → SSE error；回归用例 `tests/test_chat_actions.py::test_skip_non_last_question_passes_callback_list`）。全量复跑 `uv run python _acceptance_p2.py` → **门禁 passed=14 failed=0（退出码 0）／观察项 total=1 failed=0／dep=0**：P2-1 解析 20/20=100%（≥90%）、字段命中 20/20=100%（≥85%）、落表一致；retry 观察项 探针 http=200 / processing→ready 31.3s；P2-2 考点清单 ≥10（ready=20 scope=run）、配比复算 [1,4,7]/[1,2,3,4,6,7,8,9]/[1,3,5,7,9]、注入链路一致性 36/45=80%（≥80%，题干命中 3/3）；P2-3 会话记录 + 对话历史恢复；P2-4 `verified`（claims 3／sources 6）+ 未配置 Key 对照 `verification=null`；P2-5 第 1 题核验 `verified`、**skip 全程无 error（原 FAIL 项转 PASS）**、末题 skip 自动出报告（收口路径 `GET /report` 200，已无需 `POST /finish` 兜底）、报告 1848 字符 + `summary` dict（`total_score=13`、四维齐）、导出 200。回归：`pytest 267 passed` + `ruff` 全通过 + `npm run build` 成功；本轮未改 `app/` 与既有用例断言

## 5. 已知问题 / 待确认 / 风险

| 类别 | 内容 | 状态 |
|---|---|---|
| 已确认 | P2 web_verify 触发方式：评估节点自动核验，静默降级 | 2026-09-17 确认（PRD §5 R4 / §8） |
| 待确认 | 降级相关性阈值（默认 0.6） | P1 启用时确认 |
| 搁置·P1-3 | 引用准确率 28%（标准≥90%），judged=50/50——回查父块全文已生效但准确率仍低，需排查文档/题库质量 + 裁判口径 | P2 完成后回来排查复测 |
| 搁置·P1-4 | decline 子项：bge cosine 分布与分级阈值不匹配，score_threshold 任何值都两难（过滤则误杀正常查询，不过滤则无关查询走 fallback）；需重新设计降级策略 | P2 完成后回来重新设计 |
| 环境阻塞·P1 复跑 | P2 收尾期间 Qdrant(6333)/ES(9200)/TEI(8081) 未监听（Docker Desktop 未运行，且 TRAE 沙箱拦截 Docker Desktop 数据目录致无法启动；2026-09-18 复跑前再次探测三项仍为 False）→ `_acceptance_p1.py` 复跑无法执行；P1 侧回归证据降级为 pytest 全量（267 例）+ ruff + 前端 build（P1-3/P1-4 既有 FAIL 记录与标准均不变） | 待用户在真实环境启动三服务后复跑 P1 并复测两项搁置 |
| 已知限制 | P0 断点续聊为内存态，后端重启会话丢失（前端提示） | 已由 P2 Task 2/3 解决（会话元数据 + checkpoint 落 SQLite） |
| 已知限制 | P0 会话元数据存内存，重启后会话列表清空 | 已由 P2 Task 2 解决（sessions 表落 SQLite interview.db） |
| limitation·F1 | P2-2「题干含金标考点关键词」口径为**注入链路一致性**（fake LLM 原样回显考点清单块），不是真实「题目与清单相关性」证据；实测随抽取结果（LLM 非确定性）波动：89% → 91% → 80%（2026-09-18 36/45，标准 ≥80%，贴近阈值） | 真实相关性待后续用真实 LLM 抽样判定；建议同时固定抽样语料与缓解抖动 |
| limitation·F2 | P2 语料与 gold 均由实现者自产自标（规整纯文本），P2-1 100% / P2-2 80% 只能证明「自产规整样本链路可通」，不能外推到真实复杂版式/扫描件；字段命中口径为「name 子串 + skills 任意 ≥1 命中」，判决力有限 | 建议后续补真实来源简历（含复杂版式/扫描件）复测 |
| limitation·F8 | 2 份 PDF 语料为纯 ASCII（规避 CJK 字面串编码风险），**中文 PDF 解析链路未覆盖** | 后续补中文 PDF 语料（含 CJK 字体嵌入）复测 |
| limitation·F5 | P2-3 为「进程内跨实例恢复 + noop 合成图 + 临时库」，**未覆盖**真实 interview 图 / lifespan / API 恢复路径 | 后续可在真实 uvicorn 进程重启场景复测（Windows 环境不稳定，暂搁置） |
| 观察项·retry 路径 | `POST /api/resumes/{id}/retry`（R6「失败保留原文件可重试」）此前 pytest 与验收脚本均无覆盖；第 2 轮起由 `_acceptance_p2.py` 以**不计入门禁成功率**的观察项覆盖（对本次 failed 简历调用 retry → 断言 200 且状态 processing/ready + 原文件仍在磁盘；本次无 failed 简历时先构造 failed 探针覆盖该路径） | 已纳入验收脚本观察项（第 3 轮实测 PASS：探针 → http=200 / processing → ready 31.3s / 原文件保留=True）；后续可提升为门禁项并补 pytest 用例 |
| **缺陷·流式 skip 出题** | **已修复（`8e2933a`，2026-09-18 验收确认 PASS）**：原现象为跳过非末题后下一题出题失败（SSE `error{"message": "服务异常，请重试"}`、题号不推进）。根因：`app/api/chat.py` skip 分支传**裸 `handler`**（非 `[handler]`）→ `app/llm/client.py` `config={"callbacks": handler}` → `langchain ensure_config` 对 `COPIABLE_KEYS`（含 callbacks）执行 `v.copy()` → `TokenStreamHandler` 无 `copy` → `AttributeError` 被包装为 `LLMError`。修复：skip 分支改传 `[handler]`（1 行）+ 回归用例 `tests/test_chat_actions.py::test_skip_non_last_question_passes_callback_list` | 已修复；全量复跑该门禁项 FAIL → PASS（门禁 14/14、退出码 0），末题 skip 已能自动出报告（收口路径 `GET /report`，无需 `POST /finish` 兜底） |
| 风险 | 全局单流式为进程内锁，多进程部署需换外部锁 | 已知扩展点，当前单进程无影响 |
| 风险 | DeepSeek 限流触发时按 R2 重试 + fallback | 验收基线需正常配额 |
| 环境注意 | TRAE 沙箱对 `~/.cache` 与 `%LOCALAPPDATA%\Temp` 只读，pre-commit 需重定向 `PRE_COMMIT_HOME`/`TMP`/`TEMP` 到项目内 `.tmp/` 并以 Conda base Python（`D:\miniconda\python.exe -m pre_commit`）运行 | 步骤 1 已绕行，后续会话沿用；git commit 钩子同样受限（P2 收尾沿用） |

## 6. 下一步（P0 分步执行）

按 `docs/architecture.md` 分层拆分 Tips（执行前逐项授权）：

1. ~~**工程脚手架**~~ ✅ 已完成（2026-09-16）：uv 初始化、pyproject 依赖、ruff/pre-commit、.env.example、目录骨架
2. ~~**配置 + 日志层**~~ ✅ 已完成（2026-09-16）：omegaconf 加载、.env 注入、loguru 结构化 JSON（ISO8601/耗时/慢请求告警）
3. ~~**LLM 客户端**~~ ✅ 已完成（2026-09-16）：DeepSeek 封装（超时/重试/流式/Token 用量）+ Key 校验掩码与按会话快照
4. ~~**LangGraph 图**~~ ✅ 已完成（2026-09-16）：InterviewState + 图骨架 + 节点实现 + prompts
   - 4a：~~InterviewState + 图骨架~~ ✅（State 含 P1/P2 预留字段、skip_opening、difficulty_stage；图 5 节点 + 2 条件路由编译通过）
   - 4b：~~节点实现 + prompts~~ ✅（5 节点函数 + 实习/全职双版出题 prompt + 四维评估 + 追问 + Markdown 报告；opening 固定文案不调 LLM）
5. **SSE 接口** ✅ 已完成（2026-09-16）：chat.py SSE 端点 + 全局单流式锁 + 心跳 15s + 4 种事件类型（token/heartbeat/done/error）+ 会话存储抽象（InMemorySessionStore + MemorySaver checkpointer）+ lifespan 初始化 + 依赖注入
6. **会话管理** ✅ 已完成（2026-09-16）：sessions API（新建/列表/删除）+ settings API（全局 Key 设置/获取掩码）+ KeyStore 全局 Key + 会话级快照 + checkpointer thread_id 恢复 + 首次调用初始化 state
7. **报告生成** ✅ 已完成（2026-09-16）：结束流程 + 基础报告（总分/四维/优缺点）+ Markdown 导出
   - 完成内容：sessions API 新增 `POST /{id}/finish`（提前结束，方案 A 直接调 report_node + `update_state` 写回 checkpointer）+ `GET /{id}/report`（Markdown 文件下载）；chat.py 报告生成后同步 SessionStore status=finished
   - **关键修复**：图拓扑缺陷——`evaluate` 节点原无入口（每次 invoke 从 START 重新出题，评估永不执行）。修复：`route_after_start` 依据 `current_question` 非空 → 走 evaluate（回答后重新 invoke 进入评估而非重新出题）
8. ~~**Vue 3 前端**~~ ✅ 已完成（2026-09-16）：会话列表/对话页（SSE 流式）/配置页/报告页 + Apple 风格 UI（已导入 design skill 可用）
   - 8a-8f：~~工程初始化 + API 封装 + 四页面~~ ✅（vue-router 4 四路由、8 个 API 函数、SSE 解析、hint/skip 交互、Markdown 报告渲染）
   - 8g：~~联调收尾~~ ✅（hint/skip/skip_opening 后端缺口 + FastAPI 静态托管 dist + SPA 兜底 + 修复开场白丢失与 skip 题号 bug）
   - 8g 续·流式改造：~~题干/追问流式 + 报告占位一次性输出 + 历史消息接口~~ ✅（`TokenStreamHandler` 回调路由；前端 `status` 占位「报告生成中，请稍候…」+ 全文替换；刷新续聊）
9. ~~**验收**~~ ✅ 已完成（2026-09-16）：P0-1~P0-8 + A-1~A-5 + N 组对照核对——功能层全部满足且多项超额（见 §4）；N-4 属 P1、N-2/N-9 上传校验属 P1/P2；**待运行环境实测**：A-4 前端控制台无报错、N-1 完整回复 P95≤15s 与 TTFT P95≤3s、N-6 Chrome/Edge/Safari 兼容、P0-2 二十轮串扰与 P0-5 五并发压测；N-8 缺口已补（delete_session 级联清 checkpointer）

## 6.5 后续任务计划：M1~M4 交互 / 视觉打磨

来源：`docs/frontend-prd-gap-analysis/frontend-prd-gap-analysis.html` 第四节「中等偏差」（原型可见 / P0 裁剪 / 交互流程差异）。L1~L3 已完成（2026-09-16），M1~M4 列入后续打磨计划，执行前逐项需求澄清 + 授权。

1. **M1 · 全局信息架构——侧边栏 / 最近会话常驻入口**（待执行，P0 收尾后评估）
   - 现状：无全局侧边栏；每页独立顶部 header + 返回按钮；会话切换需回列表页
   - 原型：左侧固定栏（Logo + 导航 面试对话/简历管理/知识库 + 最近会话列表 + 底部环境配置入口）
   - 建议：P0 验收后评估引入侧边栏，或维持返回式导航（交互等价，形态不同）；涉及 `App.vue` 布局 + 四页面 header 改造

2. **M2 · 新建弹窗——面试类型 / 岗位方向**（需需求澄清）
   - 现状：弹窗仅面试场景（实习/全职）+ 题目数量 + 跳过开场白
   - 原型：面试类型（技术面/行为面/综合，必填）+ 岗位方向文本（必填）
   - 说明：该字段属 P0 已裁剪范围（2026-09-16 确认），重新引入将扩展场景模型（state 字段）、出题 prompt 与报告 prompt，需先澄清是否纳入及必填性

3. **M3 · 首页 / 配置页——未配置 Key 引导弹窗**（待执行）
   - 现状：新建 / 继续会话时后端拦截提示，可达但体验弱
   - 原型 / F6：首次进入应用时若无可用 Key，弹出引导前往环境配置页
   - 建议：首页挂载时 `GET /api/settings/api-key` 检测，未配置则弹引导；涉及 `HomeView.vue` + `client.ts`

4. **M4 · 配置页——「测试连接」按钮 + 密码「显示」切换**（待执行，体验增强）
   - 现状：仅「保存」（sk- 前缀前端校验），密码框固定掩码
   - 原型 / F6：底部「测试连接」+「保存配置」；Key 输入框带「显示」切换（掩码保留后 4 位）
   - 建议：新增轻量连接探测（调 LLM 或 /health）+ 掩码显示切换；涉及 `SettingsView.vue` + 后端 settings 接口（如需探测端点）

## 6.6 P1 分步执行计划

按 `docs/architecture.md` v0.3 拆分 Tips（执行前逐项授权，P1-1~P1-7 验收）：

1. ~~**P1 基建**~~ ✅ 已完成（2026-09-16）：docker-compose.yml（Qdrant + ES ik 分词，N-4 一键起）+ `app/retrieval/` client manager（qdrant/es 两个 manager，懒加载 + 连通性探测缓存 + RetrievalUnavailable 降级）+ retrieval 配置节 + lifespan 挂载（不阻塞）。**冒烟通过**：复用本机运行中的电商问数服务（qdrant v1.16 + shopkeeper-elasticsearch 8.19.10+ik），`is_available()` 双 True、ik 插件确认
2. ~~**LLMProvider 抽象改造**~~ ❌ 取消（2026-09-16 用户调整：本轮仅支持 DeepSeek，不做供应商抽象，避免过度设计）
3. ~~**EmbeddingProvider 抽象**~~ ✅ 已完成（2026-09-16）：`app/retrieval/embedding.py`——`EmbeddingProvider` 抽象 + `OpenAICompatEmbedding`（本地 TEI / 外部 API 共用 HTTP 实现，方案 A）；暴露 model_id/dims/provider（知识库绑定用 P1-7）；内置维度表（bge→1024）；探测缓存 30s；缺失降级不阻塞。真实 TEI 冒烟通过（1024 维）
4. ~~**解析 + 入库**~~ ✅ 已完成（2026-09-17）：`app/retrieval/parsers.py`（MD/TXT 直切 / python-docx / pdfplumber）+ `chunking.py` 混合父子切块（父 ≤800 字 / 子 ≤200 字）→ Qdrant 子块向量 + ES 父块正文 ik 分词双写 + 按文件路径哈希幂等重建（先清旧再入库）；154 例 pytest + 真实冒烟通过
5. ~~**知识库管理 API + UI**~~ ✅ 已完成（2026-09-17）：`store/knowledge.py`（SQLite kb.db 元数据）+ `api/knowledge.py`——建库（命名）/ 上传（≤50MB，后台任务 + 状态轮询 processing→ready/failed，失败保留原文件可重试）/ 列表 / 删除级联（Qdrant+ES+元数据，P1-5）/ Embedding 切换即自动重建（P1-7，确认弹窗）+ 前端知识库页 + 配置页 Embedding 区块（最小可行集）。183 例 pytest + ruff + 前端 build 通过
6. ~~**检索服务**~~ ✅ 已完成（2026-09-17）：`app/retrieval/retrieve.py` 双路召回（语义 Qdrant + 关键词 ES，默认权重 0.6/0.4 可配）→ 方案 B 合并（双路命中 min-max 归一化加权和 / 单路命中 fallback）→ 阈值 0.6 四级降级（normal/weak/fallback/decline）→ 引用元数据（file_id/file_name/parent_id/text/score）；检索耗时打点（真实 ~150ms，P1-6 P95≤2s 满足）；200 例 pytest + 真实服务冒烟通过
7. ~~**出题节点改造**~~ ✅ 已完成（2026-09-17）：仅出题注入——会话关联知识库时检索 → 参考资料区块注入 prompt + 题干 `[n]` 角标 + 来源折叠列表；四级降级出题（normal/weak 知识出题 / fallback 注入+弱提示语 / decline 纯通用）；新建会话关联知识库下拉；211 例 pytest + 真实冒烟通过（`_smoke_tip7.py`）
8. ~~**会话关联知识库**~~ ✅ 已完成（并入步骤 7，2026-09-17）：`InterviewState` + `SessionMeta` 增加 `kb_id`（可空）+ 新建弹窗下拉单选可不关联
9. ~~**答案增强（评估复发出题检索）**~~ ✅ 已完成（2026-09-17）：`evaluate_node` 复用出题检索结果（方案 A：不新增检索调用，检索仍仅出题节点）→ 取向 1（知识库优先、自身知识兜底）事实校准 + 评语 `[n]` 角标 + `assess` 事件携带 citations + 评估面板引用来源折叠；无 kb/decline 纯 LLM 评估；217 例 pytest + ruff + 前端 build 通过
10. **~~P1 验收~~** ✅ 已完成（2026-09-17，passed=11 failed=3，P1 未整体通过）：P1-1 入库成功率 5/5=100%（幂等块数一致）/ P1-2 50 题 Top-K=5 召回命中率 50/50=100%（gold 定位 50/50）/ P1-3 normal 级引用准确率 **12% FAIL**（应用缺陷：引用文本取命中子块→大量裸 Markdown 标题，不改 app 记 FAIL 落档）/ P1-4 四级降级 3/4 PASS（**decline 子项 FAIL**：语义路无相似度截断致不可达，不改 app 记 FAIL 落档）/ P1-5 删除级联 0 命中 PASS（文件级+库级三处 0 残留）/ P1-6 单次检索 P95=134ms PASS（≤2s）/ P1-7 Embedding 切换重建 PASS（rebuild ok=5、绑定一致、抽样 5/5）+ 观察项 FAIL（查询模型≠绑定模型拒绝校验未实现，待用户裁决）；验收脚本 `_acceptance_p1.py` + 语料/题库 `tests/acceptance/` + 报告 `docs/acceptance/p1-acceptance-report.md`（草稿）

## 7. 文档体系与维护约定

| 文档 | 位置 | 更新时机 |
|---|---|---|
| PRD | `prd/prd.html`（交互完整版）+ `docs/prd.md`（同步镜像） | 需求/验收/决策变更 |
| 架构 | `docs/architecture.md`（含迭代记录表） | 架构迭代必须记录原因 |
| 项目阶段 | `docs/project-status.md`（本文档） | 里程碑 / 阶段切换 / 风险变化 |
| CHANGELOG | `CHANGELOG.md` | 每次修改（格式：日期/标题/描述/变更/验证/结构） |

**规则**：大改动 = 涉及需求范围、架构形态、阶段状态三者任一的变化。触发时三文档 + CHANGELOG 四份同步更新；验收结论与通过清单记入 CHANGELOG。

## 8. 决策日志索引

- 2026-09-15 技术决策 12 项 → `docs/prd.md` §2 + 项目记忆
- 2026-09-15 边界 5 项 + N-1~N-9 → `docs/prd.md` §3/§6
- 2026-09-16 P0 决策 8 项 → `docs/prd.md` §7
- 2026-09-16 架构 v0.1 → `docs/architecture.md` §7 迭代记录
- 2026-09-16 Embedding 模型可配置（本地 / 外部 API，库绑定 model_id，切换重建，外发提示）→ `docs/prd.md` §7 + P1-7 / 架构 v0.2
- 2026-09-16 H1~H5 需求对齐缺口 + L1~L3 视觉细节（assess 事件/评估面板/进度条/列表筛选/报告可视化/多行输入/头像对称/时间戳/状态徽标/显式按钮）→ PRD F 组 + gap 分析第四节
- 2026-09-16 M1~M4 后续任务计划（侧边栏/面试类型与岗位方向/Key 引导弹窗/测试连接+密码显示）→ `docs/project-status.md` §6.5
- 2026-09-16 P0 验收核对：功能层全部完成且超额；4 项实测类待运行环境验证；N-8 补 checkpointer 级联删除（`MemorySaver.delete_thread`）→ `docs/project-status.md` §3/§4/§6-9
- 2026-09-16 实测项延后至阶段收尾（A-4/N-1/N-6/P0-2·P0-5，N-1 待 P1 检索链路稳定后测）→ `docs/project-status.md` §3/§4，进入 P1 需求澄清
- 2026-09-16 P1 需求澄清 8 项（Docker 环境 / 最小可行集 UI / 仅出题注入 / 阈值 0.6 / 角标+来源折叠 / OpenAI-compatible 双抽象 / 轻量解析 / 关联库单选可空）→ `docs/prd.md` §7 + 架构 v0.3 + `docs/project-status.md` §6.6
- 2026-09-16 范围调整：LLM 不做抽象（仅 DeepSeek，LLMProvider 取消），Embedding 抽象保留 → `docs/prd.md` §7 + 架构 v0.4 + §6.6 Tip 2 取消
- 2026-09-17 电商问数迁移：TEI 模型（bge-large-zh-v1.5）移入本项目 `docker/embedding/`，compose 起 ai-interviewer 三容器（qdrant/es/embedding）；shopkeeper 容器已停用；旧数据卷 6 个已删；`shopkeeper-agent` 目录沙箱拦截待用户手动删除 → CHANGELOG + 踩坑 #12-14
- 2026-09-17 P1 步骤 4（解析 + 入库）完成：轻量解析 + 混合父子切块 + Qdrant/ES 双写 + 幂等重建 → `docs/project-status.md` §4/§6.6 + 踩坑 #15-17
- 2026-09-17 P1 步骤 5 需求澄清 4 项：知识库元数据 SQLite kb.db / 入库后台任务 + 状态轮询 / Embedding 切换即自动重建（确认弹窗）/ 先建库后传文件（一库多文件）→ `docs/prd.md` §7 + 架构 v0.5 + §6.6 Tip 5 更新
- 2026-09-17 P1 步骤 5 完成：SQLite kb.db 元数据层 + 知识库管理 API（上传/重试/删除级联）+ Embedding 切换重建 + 前端知识库页与配置页 Embedding 区块；183 例 pytest（新增 29）→ CHANGELOG + §4/§6.6
- 2026-09-17 P1 步骤 6 完成：检索服务（双路召回 + 方案 B 合并 + 四级降级 + 引用元数据 + 耗时打点）；补入库端 kb_id/file_name + Qdrant query_points API；200 例 pytest + 真实服务冒烟（~150ms/查询）→ CHANGELOG + §4/§6.6
- 2026-09-17 P1 步骤 7 完成：出题节点改造（仅出题注入：RetrievalContext 注入 + 参考资料区块 + [n] 角标 + 四级降级出题 fallback 弱提示 / decline 纯通用 + SSE citations 事件 + 前端来源折叠 + 会话关联知识库）；211 例 pytest + 真实服务冒烟（`_smoke_tip7.py`）→ CHANGELOG + §4/§6.6
- 2026-09-17 P1 步骤 8 完成：答案增强——评估节点复用出题检索结果（方案 A：检索仍仅出题节点、不新增调用；取向 1：知识库优先、自身知识兜底）→ 评语 [n] 角标 + assess 事件携带 citations + 评估面板来源折叠；无 kb/decline 纯 LLM 评估；217 例 pytest + ruff + 前端 build → CHANGELOG + §4/§6.6
- 2026-09-17 P1 验收执行（passed=11 failed=3，未整体通过）：P1-3 引用准确率 12% 与 P1-4 decline 不可达判定为应用层真实缺陷，用户裁决「不改 app、记 FAIL 落档待后续修复」；P1-7 查询拒绝校验缺口记录为观察项待用户裁决 → `docs/acceptance/p1-acceptance-report.md` + CHANGELOG + §3/§4/§6.6
- 2026-09-17 P2 设计定稿（简历解析 + 考点清单 / 双来源出题配比 / SqliteSaver 持久化 / web_verify 评估节点自动核验静默降级）→ `docs/superpowers/specs/2026-09-17-p2-resume-persistence-design.md` + 计划 11 任务 + PRD §5 R4 / §8
- 2026-09-17 P2 Task 1~10 完成（配置扩展 / 会话元数据 SQLite / SqliteSaver / 简历域存储 / 解析抽取 / 简历 API / 双来源出题 / web_verify / 前端简历页·会话关联·核验展示）→ CHANGELOG + §4
- 2026-09-17 P2 Task 11 端到端验收通过（`_acceptance_p2.py` passed=12 failed=0）+ PRD 四处漂移修订核验（§4 F3 / §5 R4 / §6 P2 / §6 N-9 + §8）→ CHANGELOG + §3/§4/§5
- 2026-09-17 P2 收尾环境偏差记录：Qdrant/ES/TEI 未监听致 P1 复跑无法执行（沙箱无法启动 Docker Desktop），P1 既有 FAIL 维持 → §3/§5
- 2026-09-17 P2 验收审查修复（第 1 轮）：F3 核验端到端（P2-5 自设 verify-key + 搜索补丁，真实走通 VerifyContext 全链路 + 报告摘要必备键/四维校验 + finally 还原）；F4 对照组收紧（同一 answer + `is_set=False` 旁证）；F6 验收数据隔离（只用本次上传 resume_id）；F7 更正 PRD 修订表述（实际 5 处改动随 20216a5 提交）；F1/F2/F5/F8 落档 limitation → CHANGELOG + §3/§4/§5
- 2026-09-17 P2 验收审查修复（第 2 轮）：验收脚本健壮性——依赖缺失（无 ready 语料）归类 `dep` 不计入 failed、skip 循环 error 事件显式记录（门禁项）、5 处 `assert` 改「记录 FAIL + 提前 return」+ main 每项兜底 try/except（保证总有 SUMMARY 与退出码）、摘要 detail 打印原始 `summary`（截断）；新增 retry 路径观察项（`kind="obs"`，不计入成功率门禁，无 failed 简历时构造探针）；CHANGELOG / 本文档「随本提交」表述补 `20216a5` 消歧 → CHANGELOG + §3/§4/§5。**副产物：minor-2 记录项首次暴露 app 侧既有缺陷「流式 skip 出题失败」**（`chat.py` 传裸 handler → `TokenStreamHandler` 无 `copy` → `AttributeError` → SSE error；非本轮引入、两轮 100% 复现，此前被 skip 静默 break + `POST /finish` 兜底掩盖），本轮禁改 `app/` 故仅落档 §5 待裁决 → 该缺陷后于 `8e2933a` 修复（见下条）
- 2026-09-18 **P2 收尾：skip 缺陷修复 + 全量验收复跑确认**：`app/api/chat.py` skip 分支裸 `handler` → `[handler]`（根因：`langchain ensure_config` 对 `callbacks` 执行 `copy()`，`TokenStreamHandler` 无 `copy` → `AttributeError` → `LLMError` → SSE error）+ 回归用例 `tests/test_chat_actions.py::test_skip_non_last_question_passes_callback_list`；全量复跑 `_acceptance_p2.py` → **门禁 passed=14 failed=0／观察项 1 PASS／dep=0（退出码 0）**，原 skip 门禁项 FAIL → PASS，末题 skip 自动出报告（收口走 `GET /report`）；`pytest 267` + `ruff` + `npm run build` 全通过；P1 复跑环境仍未恢复（三服务未监听），P1-3/P1-4 搁置与标准不变 → CHANGELOG + §3/§4/§5
