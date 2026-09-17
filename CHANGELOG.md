# CHANGELOG

## 2026-09-17 · P1 验收执行完成（P1-1~P1-7 真实环境）

**描述**：自建 5 篇多栈 MD 验收语料（redis/mysql/java-concurrency/network/os 各 10 考点）+ 50 题预标出处题库（`gold_snippet`）+ 独立验收脚本 `_acceptance_p1.py`（CLI `--only`/`--keep`，全量串行 P1-1~P1-7）在真实服务（Qdrant + ES ik + TEI bge + DeepSeek）上执行七项退出标准。实测 **passed=11 failed=3**：P1-1 入库 5/5=100%（幂等块数一致）、P1-2 gold 定位 50/50 + 召回 50/50=100%、P1-5 文件/库级删除三处 0 残留、P1-6 检索 P95=134ms、P1-7 切换重建 ok=5 + 绑定一致 + 抽样命中 5/5 均通过；**P1-3 引用准确率 12%（FAIL）** 与 **P1-4 decline 子项（FAIL）** 为应用层真实缺陷（引用文本取自命中的子块导致大量裸 Markdown 标题、语义路无相似度截断致 decline 级在 Qdrant 在线时不可达），按用户裁决**不改 app、记 FAIL 落档**待后续修复；P1-7 观察项（查询模型≠绑定模型拒绝校验未实现）记录型 FAIL 待用户裁决。

**变更内容**
- 新增 `tests/acceptance/corpus/redis.md` 等 5 篇语料（每篇 10 考点，二级标题 + 段落结构，父子切块入库）
- 新增 `tests/acceptance/questions.json`（50 题：id/topic/query/source_file/gold_snippet，预标标准出处）
- 新增 `_acceptance_p1.py`（独立验收脚本：Report 收集器 + CLI + 七项验收 + cleanup，`tests/acceptance/` 不参与 pytest 收集）
- 新增 `docs/acceptance/p1-acceptance-report.md`（验收报告草稿，含环境探测、七项数据表、FAIL 归因、观察项）
- 文档落档：`docs/prd.md`（§6 P1 验收结论标注）、`docs/project-status.md`（§3/§4/§6.6/§8）

**验证结果**
- 全量运行 `uv run python _acceptance_p1.py`：SUMMARY passed=11 failed=3（退出码 1，FAIL 均为已裁决应用缺陷/观察项，如实呈现未调阈值）
- P1-2 召回命中率 50/50=100%、P1-6 P95=134ms（P50=111ms max=143ms）、P1-7 rebuild ok=5 failed=0 + binding_ok + sample_hit=5/5
- 回归 pytest 全量通过（见下）

**项目结构更新**
- 新增：`tests/acceptance/corpus/`、`tests/acceptance/questions.json`、`_acceptance_p1.py`、`docs/acceptance/`
- 文档：`docs/prd.md`、`docs/project-status.md`、`CHANGELOG.md`

## 2026-09-17 · PRD/架构文档漂移修正（P1 表述同步）

**描述**：修正 P1 文档中两处与已确认决策不一致的旧表述：① 阶段表「Docling → 父子切块」对齐 §7「Docling 后置、轻量解析」决策，改为「轻量解析 MD/TXT/DOCX/PDF → 父子切块」；② 「评估维持四维通用标准，不额外检索」对齐 Tip 8 演进，改为「评估复用出题检索结果做事实校准（方案 A：不新增检索调用；无引用时完全退化纯 LLM 评估）」。

**变更内容**
- `docs/prd.md`：§2 阶段表 P1 行解析链路表述修正
- `docs/prd.md`：§7 P1 决策「RAG 注入点」表述修正（补充评估复用与退化语义）
- `docs/architecture.md`：P1 关键抽象「检索链路」表述同步修正

**验证结果**
- 纯文档变更；grep 复核无残留旧表述（阶段表「Docling」、决策表「评估维持四维通用标准，不额外检索」）

**项目结构更新**
- 文档：`docs/prd.md`、`docs/architecture.md`、`CHANGELOG.md`

## 2026-09-17 · P1 步骤 8（答案增强·评估节点复发出题检索结果）完成

**描述**：实现「答案增强」——评估节点复用出题节点的检索结果（方案 A：检索仍只发生在出题节点，不新增检索调用）+ 取向 1（知识库优先、自身知识兜底）事实校准评估：评语 `[n]` 角标标注 + SSE `assess` 事件携带引用元数据 + 右侧评估面板引用来源折叠列表；无知识库 / decline 级完全退化为纯 LLM 评估。

**变更内容**
- `app/interview/state.py`：`Score` 新增 `citations` 可选字段（本题引用元数据，评估面板 & 报告展示用）；`InterviewState` 新增 `_reference_block`（当前题参考资料文本，出题节点写入、评估节点复用）
- `app/interview/nodes/__init__.py`：`ask_question_node` 命中引用时写入 `_reference_block`（与 `_citations` 同条件）；两键**无条件写入**（未命中为空值 `""`/`[]`，防止 LangGraph 跨题残留上一题引用污染评估）；`evaluate_node` 读取 `_reference_block` 注入 prompt（空串完全退化），命中引用时将 `_citations` 原样写入 `score["citations"]`（不重新检索）
- `app/interview/prompts/evaluate.py`：模板新增 `{reference_block}` 占位 + 两条知识库优先评估规则（优先基于参考资料评估事实准确性、评语引用观点标注 `[n]` 角标）
- `app/api/chat.py`：SSE `assess` 事件载荷新增 `citations` 字段（透传 score 引用元数据，缺失为空数组）
- 前端：`web/src/api/types.ts` `AssessPayload` 与 `SSEEvent.assess` 新增 `citations?: Citation[]`；`web/src/views/ChatView.vue` 评估面板新增引用来源折叠区（复用题干 cite-* 类 + `.assess-cites` 微调）
- 新增测试：`tests/test_nodes.py` 评估注入 5 例（normal 注入 + 评语角标 / fallback 弱提示注入 / decline 纯通用 / 无 kb 纯通用 / citations 原样透传 identity）；`tests/test_stream_integration.py` 端到端 1 例（真实 SSE + 图 + checkpointer，仅 patch 检索函数，assess 事件 citations 逐字段透传）

**验证结果**
- pytest 217 passed（步骤 7 基线 211 → +6，其中节点评估注入 5 例 + 流式集成 1 例）、ruff check 全通过
- 前端 `npm run build` 通过（tsc + vite）

**项目结构更新**
- 更新：`app/interview/state.py`、`nodes/__init__.py`、`prompts/evaluate.py`、`app/api/chat.py`、`web/src/api/types.ts`、`web/src/views/ChatView.vue`、`tests/test_nodes.py`、`tests/test_stream_integration.py`
- 文档：`CHANGELOG.md`、`docs/project-status.md`（§4/§6.6/§8）

## 2026-09-17 · P1 步骤 7（出题节点改造）完成

**描述**：实现「仅出题注入」——会话关联知识库时，出题节点先检索再出题：四级降级出题（normal/weak 知识出题 + 引用角标；fallback 注入 + 弱提示语「以下内容基于有限资料生成」；decline 纯通用出题）+ 题干 `[n]` 角标标注 + 前端引用来源折叠列表（点击展开/收起，显示文件名称与文本片段）+ 新建会话关联知识库（下拉单选，可不关联）。

**变更内容**
- `app/retrieval/retrieve.py`：新增 `RetrievalContext` 数据类（cfg/qdrant/es/embedding 组件集合，图构建时注入，测试可替换 fake；从 `app/retrieval/__init__.py` 移入避免循环导入）
- `app/interview/nodes/__init__.py`：`ask_question_node` 新增 `retrieval` 参数——有 kb_id 且注入 RetrievalContext 时调 `retrieve`（查询词：已问主题延续 / 首题场景默认词），`result.level != DECLINE` 且命中引用时构建参考资料区块（`_build_reference_block`，[n] 角标 + 片段截断 120 字 + 使用指令，fallback 附加弱提示语）注入 prompt；`level == FALLBACK` 时题干前加弱提示语；`_citations`（≤3 条，file_name/text/score）写入 state 供前端折叠展示
- `app/interview/prompts/ask_question.py`：两版 prompt 新增 `{reference_block}` 占位（无命中为空，完全退化为纯通用出题）+ 「优先基于参考资料出题、取材处标注角标」指令
- `app/interview/graph.py`：`build_graph` 新增 `retrieval` 参数，`partial` 注入出题节点
- `app/main.py`：lifespan 后构造 `RetrievalContext` 注入 `compile_graph`
- `app/interview/state.py`：新增 `kb_id`（P1 会话关联知识库 ID）+ `_citations`（运行时注入，当前题引用元数据）
- `app/store/sessions.py` + `app/api/sessions.py`：`SessionMeta` 新增 `kb_id` 字段，创建会话支持 `kb_id` 参数并回显
- `app/api/chat.py`：SSE 新增 `citations` 事件（出题节点执行后下发当前题引用元数据）
- 前端：`web/src/api/types.ts` 新增 `Citation` 类型 + `citations` SSE 事件；`web/src/views/ChatView.vue` 引用来源折叠（`showCites` 展开/收起 + 角标/文件/片段样式）；`web/src/views/HomeView.vue` 新建弹窗新增知识库下拉（含文件数，可不关联）
- 新增测试：`tests/test_nodes.py` 出题检索注入 8 例（无 kb 纯通用 / 有 kb 无注入降级 / normal·weak 参数化注入 / fallback 弱提示 / decline 纯通用 / 引用截断 ≤3 / 首题默认查询词 / 引用块片段截断）；`tests/test_api_sessions.py` 创建会话关联知识库 1 例

**验证结果**
- pytest 211 passed（Tip 6 基线 200 → +11，其中节点检索注入 9 例 + API 关联知识库 1 例）、ruff check 全通过
- 真实服务冒烟（`_smoke_tip7.py`）：入库 Redis 面试知识 → `ask_question_node` 检索注入（真实 Qdrant+ES+TEI）→ 引用角标随题干生成 → 清理，检索注入链路全通

**项目结构更新**
- 新增：`_smoke_tip7.py`（冒烟脚本）
- 更新：`app/retrieval/retrieve.py`、`__init__.py`、`app/interview/nodes/__init__.py`、`prompts/ask_question.py`、`graph.py`、`state.py`、`app/main.py`、`app/api/chat.py`、`sessions.py`、`app/store/sessions.py`、`web/src/api/types.ts`、`views/ChatView.vue`、`views/HomeView.vue`、`tests/test_nodes.py`、`tests/test_api_sessions.py`
- 文档：`CHANGELOG.md`、`docs/project-status.md`（§4/§6.6/§8）

## 2026-09-17 · P1 步骤 6（检索服务）完成

**描述**：实现双路召回检索服务——语义（Qdrant 向量）+ 关键词（ES ik 全文）→ 方案 B 合并（双路命中 min-max 归一化加权和 / 单路命中直接该路归一化分，标记 fallback）→ 四级降级（normal/weak/fallback/decline，以最高分引用的命中类型为准）→ 引用元数据（file_id/file_name/parent_id/text/score + 各路分）+ 检索耗时打点（P1-6 P95≤2s）。同步补全入库端 payload：Qdrant/ES 新增 `kb_id` + `file_name` 字段，ES mapping 新增 `file_name`/`kb_id` keyword 类型；Qdrant 客户端升级到 query_points API（v1.x+ 新版）。

**变更内容**
- 新增 `app/retrieval/retrieve.py`：`retrieve(query, kb_id, cfg, qdrant, es, embedding) -> RetrievalResult` + `_merge_hits`（方案 B 合并）+ 四级分级（normal ≥threshold / weak ≥weak_threshold / fallback 单路 / decline 无命中）+ 引用元数据（Citation 数据类）+ 耗时打点（total_ms / semantic_ms / keyword_ms）
- `app/retrieval/ingest.py`：`ingest_document` 新增 `kb_id` 参数；Qdrant payload + ES 文档新增 `file_name` 与 `kb_id` 字段
- `app/retrieval/es.py`：`ensure_index` mapping 新增 `file_name`（keyword）+ `kb_id`（keyword），支撑按库过滤与来源折叠展示
- `app/retrieval/retrieve.py` Qdrant 查询：`search` → `query_points`（v1.x+ API），`resp.points` 取结果
- `app/retrieval/tasks.py`：后台入库/重建任务传入 `kb_id`
- `app/config.py`：新增 `retrieval.weak_threshold`（默认 0.45）+ `semantic_weight` / `threshold` / `top_k` 的环境变量覆盖（SEMANTIC_WEIGHT / RETRIEVAL_THRESHOLD / RETRIEVAL_WEAK_THRESHOLD / TOP_K）
- 新增测试：`tests/test_retrieval_retrieve.py`（17 例：_merge_hits 6 例 + retrieve 11 例，覆盖 normal/weak/fallback/decline 四级、双路/单路/无命中、服务不可用降级、top_k 截断、耗时打点）

**验证结果**
- pytest 200 passed（183 + 新增 17）、ruff check + format 全通过（61 文件）
- 真实服务冒烟：TEI + Qdrant + ES 端到端——入库（1 父块 5 子块）→ 相关查询 normal 级（0.886 分，sem=0.81 kw=1.0）→ 跨库过滤 decline（0 命中）→ 清理，全链路通
- 检索耗时：真实环境单查询 ~130-150ms（语义 ~110-135ms + 关键词 ~7-12ms），远低于 P1-6 P95≤2s 指标

**项目结构更新**
- 新增：`app/retrieval/retrieve.py`、`tests/test_retrieval_retrieve.py`
- 更新：`app/retrieval/ingest.py`、`es.py`、`tasks.py`、`app/config.py`、`CHANGELOG.md`、`docs/project-status.md`（§4/§6.6/§8）

## 2026-09-17 · P1 步骤 5（知识库管理 API + UI）完成

**描述**：实现知识库管理全链路——SQLite kb.db 元数据层（knowledge_bases / kb_files 两表，线程安全单连接+锁）+ 管理 API（建库绑定当前 Embedding 模型 / 列表 / 上传 ≤50MB 后台入库 / 失败重试 / 删除级联 Qdrant+ES+元数据+原文件，检索服务缺失降级不阻塞）+ Embedding 切换即自动重建（P1-7，PUT /settings/embedding 写 .env 并后台逐库重嵌入）+ 前端知识库页与配置页 Embedding 区块。

**变更内容**
- 新增 `app/store/knowledge.py`：`KnowledgeStore`（CRUD + 状态机 processing→ready/failed + `bind_model` + `delete_kb` 返回文件清单供级联）
- 新增 `app/retrieval/tasks.py`：`ingest_file_background/async`（asyncio.to_thread 后台入库，失败保留原文件置 failed）+ `rebuild_all_background/async`（Embedding 切换全库重建 + 更新全部库绑定 model_id/dims）
- 新增 `app/api/knowledge.py`：建库（命名 1-64 字）/ 列表 / 上传（md/txt/docx/pdf、≤50MB、空文件/格式校验、保存原文件→processing）/ 失败重试（仅 failed 可重试）/ 删除级联
- `app/api/settings.py`：新增 GET/PUT `/settings/embedding`（探测可用性→写 .env→切换生效→有文件则后台重建，api_key 掩码返回）
- `app/api/deps.py`：新增 knowledge_store/qdrant/es/embedding 依赖注入
- `app/main.py`：lifespan 挂载 `KnowledgeStore` + 注册 knowledge 路由
- `app/config.py`：新增 `retrieval.kb_dir`（data/kb_files）/ `kb_db`（data/kb.db）+ env 覆盖
- `.env.example`：补 EMBEDDING_* 与 KB_DIR/KB_DB 模板
- 前端：新增 `web/src/views/KnowledgeView.vue`（库卡片/文件列表/状态徽标/上传/重试/删除确认）、`SettingsView.vue` 新增 Embedding 配置区块（本地 TEI 预设/外部 API + 切换确认弹窗）、`client.ts`/`types.ts` 新增 API 与类型、路由与首页导航入口
- `pyproject.toml`：新增 python-multipart（multipart 表单解析）
- 新增测试：`tests/test_knowledge_store.py`（16 例）/ `test_knowledge_api.py`（12 例）/ `test_tasks.py`（3 例，失败不中断全库重建）

**验证结果**
- pytest 183 passed（154 + 新增 29）、ruff check + format 全通过（59 文件）
- 前端 `npm run build` 通过（含 KnowledgeView/SettingsView 产物）
- 隔离性：API 测试将数据目录/元数据库/入库任务全部隔离到 tmp_path，不污染真实 data/ 与 .env

**项目结构更新**
- 新增：`app/store/knowledge.py`、`app/retrieval/tasks.py`、`app/api/knowledge.py`、`web/src/views/KnowledgeView.vue`、`tests/test_knowledge_store.py`、`tests/test_knowledge_api.py`、`tests/test_tasks.py`
- 更新：`app/api/settings.py`、`deps.py`、`app/main.py`、`app/config.py`、`.env.example`、`pyproject.toml`、`web/src/api/client.ts`、`types.ts`、`router/index.ts`、`views/HomeView.vue`、`views/SettingsView.vue`、`CHANGELOG.md`
- 文档：`docs/project-status.md`（§4/§6.6/§8）、`docs/prd.md`（§7 决策表）、`docs/architecture.md`（v0.5）

## 2026-09-17 · P1 步骤 5（知识库管理 API + UI）需求澄清完成（4 项确认）

**描述**：P1 步骤 5 执行前需求澄清，4 项决策树式确认：① 知识库元数据存 **SQLite kb.db**（库/文件条目/processing·ready·failed 状态/绑定 model_id·dims，跨重启可靠，删除级联有据）；② 入库走**后台任务 + 状态轮询**（上传即返 processing，前端轮询至 ready/failed，失败保留原文件可重试）；③ **Embedding 切换即自动重建**（配置页保存新模型弹确认 → 后台逐库重新嵌入并更新绑定 model_id，满足 P1-7）；④ 知识库组织为**先建库后传文件**（一库多文件，会话关联单选到「库」粒度，引用标注显示所属文件）。

**变更内容**
- `docs/prd.md`：§7 P1 已确认决策表新增 4 行（元数据存储 / 入库执行 / 切换重建 / 库组织）
- `docs/architecture.md`：v0.4 → v0.5——§4.3 知识库数据模型补充元数据存储（SQLite kb.db，新增 `store/knowledge.py`）；目录架构补 `api/knowledge.py` 与 `store/knowledge.py`；迭代记录 v0.5
- `docs/project-status.md`：§4 追加 Tip 4 完成 + Tip 5 澄清；§6.6 Tip 4 标记完成、Tip 5 标注澄清决策；§8 追加决策日志

**验证结果**
- 文档更新，无代码改动（无需 pytest / build）

**项目结构更新**
- `docs/prd.md`、`docs/architecture.md`、`docs/project-status.md`：更新

## 2026-09-17 · P1 步骤 4（文档解析 + 父子切块入库）完成

**描述**：实现知识库入库全链路——轻量解析（MD/TXT 直读、DOCX 用 python-docx、PDF 用 pdfplumber 提取文字层，无文字层提示失败）+ 混合父子切块（段落优先 → 句子细切 → 超长单句滑动窗口兜底 → 段内相邻子块可选 overlap 补偿 → 相邻子块聚合父块 ≤800 字）+ Qdrant 子块向量 / ES 父块正文（ik 分词）双写 + 按文件路径哈希幂等重建（先清旧再入库）。

**变更内容**
- 新增 `app/retrieval/parsers.py`：`SUPPORTED_EXTENSIONS` + `parse_document`（统一换行/去零宽字符/空文本报错）+ `ParseError`（含 PDF 无文字层）
- 新增 `app/retrieval/chunking.py`：`Block`（子块 ≤200 字召回单元）/ `ParentBlock`（父块 ≤800 字引用单元）+ `chunk_document` 五阶段算法
- 新增 `app/retrieval/ingest.py`：`file_id_of`（路径哈希 16 位）+ `ingest_document`（解析→切块→ensure 集合/索引→清旧→双写，嵌入批量 64）
- `app/retrieval/qdrant.py`：新增 `ensure_collection`（按 embedding.dims 建集合，Cosine）
- `app/retrieval/es.py`：新增 `ensure_index`（ik_max_word 索引 + parent_id/file_id/text 映射）
- `app/config.py`：新增 `retrieval.chunking` 配置节（parent_max 800 / child_max 200 / overlap 0 / slide_window 180 / slide_overlap 20 + env 覆盖）
- `pyproject.toml`：新增 python-docx + pdfplumber 依赖；ruff `exclude = ["docker"]`（供应商模型 README 不参与检查/格式化）
- `.env.example`：补切块配置环境变量模板
- 新增 `tests/test_retrieval_chunking.py`（段落/句子细切/滑动窗口/父块聚合边界）+ `tests/test_retrieval_ingest.py`（解析器/双写/幂等/集合索引创建）
- `docs/troubleshooting.md`：新增 #15-17（Qdrant delete 过滤参数 / 集合不存在 404 / mock 向量长度不匹配）

**验证结果**
- pytest 154 passed（134 + 新增 20）、ruff check + format 全通过（补修 8 处规范：E501 ×3 / B905 / SIM113 / I001 / F401 / 格式 6 文件）
- 真实环境冒烟通过：MD/TXT/DOCX/PDF 解析 → 切块 → TEI 嵌入 → Qdrant/ES 双写 → 幂等重建 → 清理测试数据

**项目结构更新**
- 新增：`app/retrieval/parsers.py`、`chunking.py`、`ingest.py`、`tests/test_retrieval_chunking.py`、`tests/test_retrieval_ingest.py`
- 更新：`app/retrieval/qdrant.py`、`es.py`、`app/config.py`、`pyproject.toml`、`.env.example`、`docs/troubleshooting.md`

## 2026-09-17 · 电商问数容器资源迁移（shopkeeper-agent 停用）

**描述**：按用户要求将电商问数项目中可复用的容器资源迁移到本项目，项目本体（shopkeeper-agent）不再保留。迁移核心：TEI（bge-large-zh-v1.5）模型文件移入本项目，Qdrant/ES 复用镜像由本项目 compose 独立起服务。

**变更内容**
- `docker-compose.yml`：新增 `embedding` 服务（TEI，挂载 `./docker/embedding/bge-large-zh-v1.5`，端口 8081）；ES 直接引用 `shopkeeper-elasticsearch:latest` 镜像（用户确认，节省重构建时间）；qdrant 注释更新
- 模型文件迁移：删除冗余 `pytorch_model.bin`（TEI 仅加载 safetensors，省 1.3GB），`bge-large-zh-v1.5` 全套移入 `docker/embedding/`（safetensors 1.3GB + tokenizer 等）
- 容器切换：停用并删除 shopkeeper 的 qdrant/elasticsearch/embedding/kibana/mysql 容器（compose down 未匹配固定容器名，改 stop+rm）；本项目 `docker compose up -d` 起 `ai-interviewer-qdrant/es/embedding` 三容器
- 遗留处理：旧数据卷（shopkeeper_es_data/qdrant_data/mysql_data + docker_* 系列共 6 个，电商问数业务数据）已删；`shopkeeper-agent` 目录因沙箱拦截（卡在 .git 内部文件），**待用户手动删除**

**验证结果**
- pytest 134 passed、ruff 通过（代码未改）
- 三服务验证：qdrant healthz OK、es green + analysis-ik 插件、TEI warmup 后 `embed_query/embed_documents` 均 1024 维 → SMOKE OK
- 踩坑：compose 残留 Created 容器导致端口映射丢失与 ES 启动失败（down+up 重建解决，troubleshooting #12）；TEI warmup 期间 502（#13）；沙箱回收站 API 不可用 + 跨项目目录拦截（#14）

**项目结构更新**
- 新增：`docker/embedding/bge-large-zh-v1.5/`（模型全套）
- 更新：`docker-compose.yml`、`docs/troubleshooting.md`（#12-14）
- 删除（shopkeeper-agent）：`pytorch_model.bin`（冗余）

## 2026-09-16 · P1 步骤 3（EmbeddingProvider 抽象）完成

**描述**：按方案 A 实现 `app/retrieval/embedding.py`：OpenAI-compatible embedding 客户端（本地 TEI / 外部 API 共用同一 HTTP 实现，仅 base_url/api_key 不同）。本地默认 `http://127.0.0.1:8081/v1`（复用电商问数 TEI 的 bge-large-zh-v1.5），外部可配置。暴露 `model_id/dims/provider` 元数据（知识库绑定用，P1-7），内置维度表（bge-large-zh-v1.5 → 1024），探测结果缓存 30s，缺失时降级不阻塞核心对话。真实 TEI 冒烟通过。

**变更内容**
- 新增 `app/retrieval/embedding.py`：`EmbeddingProvider` 抽象（embed_documents/embed_query/model_id/dims/is_available）+ `OpenAICompatEmbedding` 实现（httpx POST /v1/embeddings，api_key 可选 Bearer，响应按 index 排序，探测缓存）
- `app/config.py`：`retrieval.embedding` 配置节（provider/base_url/api_key/model_id/dims/timeout）+ env 覆盖（EMBEDDING_*）
- `app/main.py`：lifespan 挂载 `app.state.embedding`（不探测不阻塞）
- `.env.example`：补 Embedding 配置模板
- 新增 `tests/test_retrieval_embedding.py`（9 例：维度映射/配置覆盖/排序/单条/空输入/Bearer 头/降级/探测缓存）

**验证结果**
- pytest 134 passed（125 + 9）、ruff check 全通过
- 真实 TEI 冒烟：provider=local、dims=1024、query/doc 向量均 1024 维 → SMOKE OK
- TEI 容器删除后的可用性已确认：核心对话不受影响（P0 不依赖 embedding）；知识库功能降级提示；可切 external 或 compose 预留 TEI 自起（预留待用户确认）

**项目结构更新**
- 新增：`app/retrieval/embedding.py`、`tests/test_retrieval_embedding.py`
- 更新：`app/config.py`、`app/main.py`、`.env.example`

## 2026-09-16 · P1 范围调整（LLM 不做抽象，仅 DeepSeek；Embedding 抽象保留）

**描述**：用户调整 P1 技术范围：取消 LLMProvider 抽象（本轮仅支持 DeepSeek，`DeepSeekClient` 保持，不做供应商抽象以避免过度设计）；Embedding 模型抽象保留（本地 bge-large-zh-v1.5 / OpenAI-compatible embedding 可切换，数据外发提示）。P1 执行计划 Tip 2 取消，Tip 3（EmbeddingProvider）顺位为下一执行项。

**变更内容**
- `docs/prd.md`：§7 P1 决策表「外部 Embedding 接入」行更新（Embedding 抽象保留 + LLM 不做抽象）
- `docs/architecture.md`：v0.3 → v0.4——撤销 LLMProvider 抽象（`llm/client.py` 恢复为 DeepSeek 客户端）；EmbeddingProvider 保留并补充本地可选复用电商问数 TEI 服务（OpenAI-compatible 端点）；迭代记录 v0.4
- `docs/project-status.md`：§6.6 Tip 2 标记取消（附原因）；§8 追加决策日志

**验证结果**
- 文档更新，无代码改动（无需 pytest / build）

**项目结构更新**
- `docs/prd.md`：更新
- `docs/architecture.md`：更新（v0.4）
- `docs/project-status.md`：更新

## 2026-09-16 · P1 步骤 1（基建）冒烟通过（复用运行中的电商问数服务）

**描述**：真实环境冒烟验证通过。发现本机电商问数项目（shopkeeper-agent）的 `qdrant`（v1.16）与 `elasticsearch`（shopkeeper-elasticsearch，8.19.10+ik）容器正在运行，端口 6333/9200 与我们的配置一致——直接复用运行中服务，无需重复拉起（原 compose 起容器时 6333 端口被占用，确认冲突来源后改为复用）。冒烟结果：`QdrantManager.is_available()==True`、`ESManager.is_available()==True`、ES 插件列表含 `analysis-ik`。

**变更内容**
- `docker-compose.yml`：ES 改为 `image: shopkeeper-elasticsearch:latest`（直接复用电商问数已构建镜像，含 ik 8.19.10；Dockerfile 保留为镜像不可用时的从零构建路径）；qdrant 补充「本机已有同名服务时复用」注释
- 构建失败记录：`FROM elasticsearch:8.19.10`（由 shopkeeper-elasticsearch tag 而来）再 RUN 装 ik 会因「插件已存在」失败——故不重建，直接复用镜像

**验证结果**
- 冒烟脚本：qdrant available: True / es available: True / es plugins: analysis-ik → SMOKE OK
- `docker compose down` 清理本项目失败容器，无残留；未触碰电商问数服务
- 无代码改动（无需 pytest / ruff）

**项目结构更新**
- `docker-compose.yml`：更新

## 2026-09-16 · P1 步骤 1（基建）ES 方案对齐电商问数（8.19.10 + 本地 ik zip）

**描述**：按用户确认，ES 镜像方案由 7.17.10（构建时 GitHub 下载 ik）改为对齐电商问数项目：`elasticsearch:8.19.10` + 本地 ik zip（`docker/es/plugins/elasticsearch-analysis-ik-8.19.10.zip`，4.4MB，从 shopkeeper-agent 复制）。构建零网络依赖，基础镜像层可复用，且与我们已装的 elasticsearch 8.19.3 客户端原生匹配。Qdrant 对齐 v1.16。

**变更内容**
- `docker/es/Dockerfile`：FROM `elasticsearch:8.19.10`，USER root → COPY 本地 zip → `elasticsearch-plugin install --batch file:///tmp/...zip` → chown → USER elasticsearch（对齐 shopkeeper-agent 写法）
- `docker-compose.yml`：Qdrant `v1.12.4` → `v1.16`；注释补充方案来源
- 新增 `docker/es/plugins/elasticsearch-analysis-ik-8.19.10.zip`（本地插件，零网络依赖构建）

**验证结果**
- `docker compose config -q` 通过；无代码改动（无需 pytest / ruff）

**项目结构更新**
- 新增：`docker/es/plugins/elasticsearch-analysis-ik-8.19.10.zip`
- 更新：`docker/es/Dockerfile`、`docker-compose.yml`

## 2026-09-16 · P1 步骤 1（基建）完成

**描述**：P1 基建落地：docker-compose 一键起 Qdrant + ES（ik 分词，N-4）；`app/retrieval/` 检索基建（qdrant/es 懒加载 manager，连通性探测结果缓存 30s，缺失时降级不阻塞启动与核心对话）；retrieval 配置节 + env 覆盖；lifespan 挂载 manager。

**变更内容**
- 新增 `docker-compose.yml`：Qdrant v1.12.4（6333/6334）+ ES 7.17.10（9200，单节点、关 security、heap 512m、healthcheck、数据卷）
- 新增 `docker/es/Dockerfile`：ES 7.17.10 + IK 中文分词插件（infinilabs analysis-ik v7.17.10）
- 新增 `app/retrieval/__init__.py`（`RetrievalUnavailable` 异常）、`app/retrieval/qdrant.py`、`app/retrieval/es.py`（懒加载 + `is_available()` 探测缓存 + `get_client()` 不可用抛错；ES 8.x `options()` 链式 ping、Qdrant `check_compatibility=False`）
- `app/config.py`：新增 `retrieval` 配置节（enabled/qdrant_url/qdrant_timeout/es_url/es_timeout/es_index/semantic_weight 0.6/threshold 0.6/top_k 5）+ `QDRANT_URL`/`ES_URL`/`ES_INDEX`/`RETRIEVAL_ENABLED` 等 env 覆盖
- `app/main.py`：lifespan 挂载 `QdrantManager`/`ESManager`（不探测不阻塞）
- `.env.example`：补 retrieval 配置模板
- 依赖：新增 `qdrant-client>=1.9`（1.19.1）、`elasticsearch>=8.13,<9`（8.19.3）
- 新增 `tests/test_retrieval_config.py`（2 例）+ `tests/test_retrieval_managers.py`（6 例：不可用降级 / 可用 mock / 探测缓存）

**验证结果**
- pytest 125 passed（117 + 8）、ruff check 全通过、`docker compose config -q` 通过
- 待真实服务冒烟：`docker compose up -d` 后验证 `is_available()==True`（下一步征求授权）

**项目结构更新**
- 新增：`docker-compose.yml`、`docker/es/Dockerfile`、`app/retrieval/`（__init__/qdrant/es）、`tests/test_retrieval_config.py`、`tests/test_retrieval_managers.py`
- 更新：`app/config.py`、`app/main.py`、`.env.example`、`pyproject.toml`、`uv.lock`

## 2026-09-16 · P1 需求澄清完成（8 项确认，三文档 + 架构 v0.3 同步）

**描述**：P1 需求澄清 8 项全部确认并落档：① 检索环境本机 Docker 就绪（docker-compose 起 Qdrant+ES ik 分词）；② 知识库 UI 最小可行集（权重滑块后置，后端可配置化）；③ RAG 仅出题注入；④ 降级相关性阈值 0.6（PRD §8 遗留项消解）；⑤ 引用角标 [1][2] + 来源折叠列表；⑥ 外部 Embedding 用 OpenAI-compatible 可配置，配套 `LLMProvider`/`EmbeddingProvider` 双抽象（仅单一协议）；⑦ 文档解析轻量渐进（Docling 后置）；⑧ 关联知识库单选 + 可不关联。P1 分步执行计划 9 步拆分入档，执行前逐项授权。

**变更内容**
- `docs/prd.md`：§7 新增「P1 已确认决策」表（8 项）；§8 待确认移除降级阈值
- `docs/architecture.md`：v0.2 → v0.3——`llm/client.py` 升级 LLMProvider 抽象（OpenAI-compatible 统一客户端）；新增 `retrieval/` 五模块（embedding/qdrant/es/ingest/retrieve）；InterviewState 增加 knowledge_base_id/retrieval_level/citations；SessionMeta 增加 knowledge_base_id；新增 §4.3 知识库数据模型（父子块：父 ≤800 字引用单元 / 子 ≤200 字召回单元）；迭代记录 v0.3
- `docs/project-status.md`：§3 阶段更新为「P1 需求澄清完成，进入 P1 分步执行」；§4 追加 P1 澄清完成；新增 §6.6 P1 分步执行计划（9 步 Tips 含 P1-1~P1-7 验收）；§8 追加决策日志

**验证结果**
- 文档更新，无代码改动（无需 pytest / build）；架构迭代原因已记录于迭代记录表

**项目结构更新**
- `docs/prd.md`：更新
- `docs/architecture.md`：更新（v0.3）
- `docs/project-status.md`：更新

## 2026-09-16 · 实测项延后决策 + 进入 P1 需求澄清

**描述**：将 4 项实测类验收（A-4 浏览器控制台 / N-1 性能 P95 / N-6 浏览器兼容 / P0-2·P0-5 压测）统一延后至阶段收尾验证——N-1 待 P1 检索链路稳定后测更准（回复耗时构成将加入检索耗时），A-4 在 P1 前端开发时随手自查。P0 验收收口，进入 P1 需求澄清阶段。

**变更内容**
- `docs/project-status.md`：§3 阶段更新为「P1 需求澄清中」+ 实测项延后决策说明；§4 追加延后决策记录；§8 追加决策日志

**验证结果**
- 文档更新，无代码改动（无需 pytest / build）

**项目结构更新**
- `docs/project-status.md`：更新

## 2026-09-16 · P0 验收核对 + N-8 缺口修复（checkpointer 级联删除）

**描述**：对照 PRD 完成 P0 步骤 9 验收核对（P0-1~8 + A-1~5 + N-1~9）：功能层全部完成且多项超额，N-4 属 P1、N-2/N-9 上传校验属 P1/P2，4 项实测类（A-4 浏览器控制台 / N-1 性能 P95 / N-6 浏览器兼容 / P0-2·P0-5 专项压测）待运行环境验证。同时修复核对中发现的 N-8 缺口：删除会话未级联清理 checkpointer 状态。

**变更内容**
- `app/store/checkpointer.py`：`delete_thread` 由 no-op 改为真实调用 `checkpointer.delete_thread(thread_id)`（langgraph 1.x MemorySaver 提供 per-thread 删除接口，P2 SqliteSaver 无缝替换）
- `app/api/sessions.py`：`delete_session` 新增 `request` 依赖，删除后经 `asyncio.to_thread` 级联清 checkpointer——SessionStore + KeyStore + checkpointer 三处同步物理删
- `tests/test_api_sessions.py`：`test_delete_session` 增强——先经 `compiled_graph.update_state` 写入状态，断言删除前 checkpointer 有状态、删除后 `get_tuple is None`
- `docs/project-status.md`：§3 阶段更新为 P0 完成；§4 追加 H1~H5/L1~L3/M 计划/验收核对/N-8 修复；§6 步骤 9 标记完成并列出 4 项待实测；§8 追加决策日志

**验证结果**
- pytest 117 passed（含增强的删除级联断言）、ruff check 全通过

**项目结构更新**
- `app/store/checkpointer.py`：更新
- `app/api/sessions.py`：更新
- `tests/test_api_sessions.py`：更新
- `docs/project-status.md`：更新

## 2026-09-16 · M1~M4 后续任务计划入档（project-status）

**描述**：将前端原型偏差分析中的 M1~M4（中等偏差）写入 `docs/project-status.md` 新增「6.5 后续任务计划」小节，作为 P0 验收后的打磨计划：M1 全局侧边栏/最近会话入口、M2 新建弹窗面试类型/岗位方向（P0 已裁剪，需需求澄清）、M3 未配置 Key 引导弹窗、M4 配置页测试连接 + 密码显示切换。每项含现状/原型/建议与涉及文件，执行前逐项澄清授权。

**变更内容**
- `docs/project-status.md`：新增「6.5 后续任务计划：M1~M4 交互 / 视觉打磨」小节（含来源说明与 4 项明细，L1~L3 已完成备注）

**验证结果**
- 文档更新，无代码改动（无需 pytest / build）

**项目结构更新**
- `docs/project-status.md`：更新

## 2026-09-16 · L1~L3 视觉细节对齐

**描述**：按前端原型对齐三项轻微视觉差异——① L1：对话页 AI 头像由「面」改为「AI」，用户气泡新增「我」头像对称排布（深色底区分）；② L2：每条消息气泡下方新增时间戳 meta（HH:MM 格式，流式结束后显示）；对话页顶部 sub 区新增「进行中」状态徽标与场景类型 chip（实习/全职）；③ L3：会话列表卡片右下由文字提示改为显式按钮「继续面试 / 查看报告」，整卡点击保留为辅助交互。

**变更内容**
- 前端 `web/src/views/ChatView.vue`：`Msg` 接口新增 `time` 字段（新消息 / 用户发送 / 历史加载时记录）；新增 `formatTime` 与 `msg-meta` 时间戳渲染；气泡布局改为 `bubble-col` 包裹（气泡 + 时间戳），AI/用户头像对称排布（`.ai-avatar`「AI」、`.user-avatar`「我」）；顶部 sub 区新增 `.type-chip` 场景 chip + `.status-badge.ongoing`「进行中」徽标
- 前端 `web/src/views/HomeView.vue`：`.session-action` 由文字提示改为 `.session-btn` 显式按钮（已完成→「查看报告」/ 进行中→「继续面试」，`@click.stop` 防与整卡点击冲突）
- 说明：历史消息时间戳为前端加载时刻近似（后端 checkpointer 不存消息时间，P0 范围外）；「进行中」徽标在面试进行中显示，完成后跳转报告页

**验证结果**
- pytest：117 passed（后端无改动，无回归）
- 前端：`npm run build`（tsc + vite）通过

**项目结构更新**
- `web/src/views/ChatView.vue`、`web/src/views/HomeView.vue`：更新

## 2026-09-16 · H1 右侧评估面板 + H4 报告结构化可视化

**描述**：两项功能增强——① H1：SSE 新增 `assess` 事件，评估完成后实时下发四维评分/评语/总分，前端对话页改为双栏布局，右侧新增「本轮评估要点」面板与「会话信息」卡；② H4：`report_node` 生成报告时在末尾附加结构化摘要 JSON（总分/四维/优缺点/关键问题回顾表，预留 `verified` 字段），报告接口返回结构化摘要，前端报告页渲染环形总分图、维度条、双栏优缺点与回顾表，摘要缺失时自动降级为纯 Markdown 展示。

**变更内容**
- `app/api/chat.py`：answer 路径在 `done` 事件后对比请求前后 `scores` 长度，有新增则下发 `assess` 事件（`dimensions`/`comment`/`score`），仅评估完成时触发、不重复
- `app/interview/nodes/__init__.py`：`report_node` 新增 `_report_summary` 输出（`_parse_report_summary` 从报告末尾提取 ```json 代码块解析，解析失败返回 None）；`app/interview/prompts/report.py`：报告 prompt 要求末尾附加结构化 JSON 摘要（含 `verified` 预留字段）
- `app/api/sessions.py`：`ReportResponse` 新增 `summary` 字段；`GET /{session_id}/report` 与 `POST /{session_id}/finish` 返回结构化摘要
- 前端：`web/src/api/types.ts`（新增 `ReportSummary`/`AssessPayload` 类型、`SSEEvent` 新增 `assess` 事件、`ReportInfo` 新增 `summary` 字段）；`web/src/api/client.ts`（`getReportContent`/`downloadReport` 适配结构化数据）；`web/src/views/ChatView.vue`（双栏布局 + 评估要点面板 + 会话信息卡，小屏隐藏侧栏）；`web/src/views/ReportView.vue`（环形总分图 + 维度条 + 双栏优缺点 + 回顾表，`summary` 为 null 时降级纯 Markdown，Markdown 渲染时剥离 ```json 块）
- 测试：`tests/test_stream_integration.py`（新增 `test_answer_emits_assess_event`、`test_followup_round_emits_assess_each_time` 2 例）；`tests/test_nodes.py`（新增 `test_report_parses_summary_block`）；`tests/test_report.py`（无 JSON 块时 `summary` 为 null 断言）

**验证结果**
- pytest：117 passed（原 113 + 新增 4 例）
- ruff check：全通过
- 前端：`npm run build`（tsc + vite）通过

**项目结构更新**
- `app/api/chat.py`、`app/api/sessions.py`、`app/interview/nodes/__init__.py`、`app/interview/prompts/report.py`：更新
- `web/src/api/types.ts`、`web/src/api/client.ts`、`web/src/views/ChatView.vue`、`web/src/views/ReportView.vue`：更新
- `tests/test_stream_integration.py`、`tests/test_nodes.py`、`tests/test_report.py`：更新

## 2026-09-16 · P0 前端对齐（H5 多行输入 + H2 题目进度 + H3 列表信息）

**描述**：按 PRD 需求详情对齐三项前端偏差——① 回答输入框由单行 input 改为多行 textarea（Enter 发送、Shift+Enter 换行、中文输入法组合键保护、自适应高度）；② 对话页顶部新增题目进度条与「第 N / M 题」（题号由后端经 messages 接口与 SSE done 事件下发）；③ 会话列表新增状态筛选（全部/进行中/已完成）与卡片消息数、当前进度信息（列表接口实时读 checkpointer，采用方案 a）。

**变更内容**
- `app/api/sessions.py`：`SessionResponse` 新增 `message_count`/`question_index` 字段；`list_sessions` 改为对每个会话并发读 checkpointer 实时取数（`model_copy(update=...)` 合并）；`MessagesResponse` 新增 `question_index` 字段
- `app/api/chat.py`：三处 `done` 事件载荷携带 `question_index`（正常结束 / 报告 finished / skip 最后一题）
- 前端：`web/src/api/types.ts`（`SessionMeta`/`MessagesResponse` 新增字段、`SSEEvent.done` 新增 `question_index?`）；`web/src/views/ChatView.vue`（textarea 多行输入 + Enter/Shift+Enter + IME 组合保护 + 自适应高度；顶部进度条 + 「第 N / M 题」；done 事件同步题号；历史加载初始化题号）；`web/src/views/HomeView.vue`（筛选 chips + 卡片消息数/进度）
- 测试：`tests/test_sessions_messages.py`（3 处补 `question_index` 断言）、`tests/test_api_sessions.py`（新增 `test_list_sessions_progress_fields`，验证列表消息数/题号随对话推进）

**验证结果**
- pytest：114 passed（原 113 + 新增 1）
- ruff check：全通过
- 前端：`npm run build`（tsc + vite）通过

**项目结构更新**
- `app/api/sessions.py`、`app/api/chat.py`：更新
- `web/src/api/types.ts`、`web/src/views/ChatView.vue`、`web/src/views/HomeView.vue`：更新
- `tests/test_sessions_messages.py`、`tests/test_api_sessions.py`：更新

## 2026-09-16 · P0 步骤 8g 续：thinking 占位事件（后端主动下发，覆盖 prefill/评估静默期）

**描述**：每次 SSE 请求的首事件改为后端主动下发 `status(thinking)`「正在思考…」占位，覆盖 LLM prefill 与评估阶段的静默等待；`status` 事件升级为带 `kind` 字段（`thinking`/`report`）的结构化负载；前端错误时清理空的「正在思考」占位气泡。

**变更内容**
- `app/api/chat.py`：`event_stream` 在校验 Key 后、图执行前先 `yield status(thinking)`；report 占位改发 `{"kind": "report", "message": "报告生成中，请稍候…"}`（`_item_to_sse` 相应改为透传 dict 负载）；模块文档字符串补充 thinking 约定
- 前端：`web/src/api/types.ts`（SSEEvent.status 改为 `{kind: 'thinking' | 'report'; message?}`）；`web/src/views/ChatView.vue`（`handleEvent` 区分两种占位——thinking 用空消息渲染「正在思考…」、report 沿用生成中占位并优先取 `message`；`error` 事件移除空的占位气泡）
- 测试：`tests/test_stream.py`（report 占位断言改结构化负载）、`tests/test_stream_integration.py`（普通流式请求首事件断言 `status(thinking)`；skip 最后一题断言 `["thinking", "report"]` 双占位顺序）

**验证结果**
- pytest：113 passed
- ruff check：全通过
- 前端：`npm run build`（tsc + vite）通过

**项目结构更新**
- `app/api/chat.py`、`web/src/api/types.ts`、`web/src/views/ChatView.vue`：更新
- `tests/test_stream.py`、`tests/test_stream_integration.py`：更新

## 2026-09-16 · P0 步骤 8g 续：题干/追问流式输出 + 报告占位一次性输出 + 历史消息接口

**描述**：将题干与追问改为 LLM 逐 token 流式输出（`TokenStreamHandler` 回调转发 + 节点路由），报告改为「生成中占位 + 一次性输出」；新增会话历史消息接口并接入前端（刷新可续聊）；顺带澄清 Python 3.14 `except A, B` 无括号语法非 bug。

**变更内容**
- `app/llm/client.py`：`complete_sync` 由 `invoke` 改为同步 `stream` 聚合，支持 `callbacks` 显式透传（逐 token 事件转发给节点回调）
- `app/interview/nodes/__init__.py`：`ask_question_node` 新增 `callbacks` 参数透传 `complete_sync`
- `app/api/chat.py`：流式架构重写——新增 `TokenStreamHandler`（LangChain 回调 → asyncio 队列；run 树溯源节点名；题干截断「【主题】」标记行（含跨 token 与行尾换行清理）；report 节点触发时先发 `status`「报告生成中，请稍候…」）；`_stream_task`（事件转发 + 15s 心跳 + 任务结束排空）；hint 改走 `llm.complete`；skip 出题直调 `ask_question_node` + fixed_node 流式；无流式 token（mock/兜底）回退从 checkpointer 提取最新 AI 消息
- `app/api/sessions.py`：新增 `GET /{session_id}/messages` 历史消息接口（checkpointer 读取，返回 role/content 列表 + hints_used + status）
- 前端：`web/src/api/types.ts`（`MessageItem`/`MessagesResponse` + SSEEvent 新增 `status` 事件）；`web/src/api/client.ts`（`getSessionMessages`）；`web/src/views/ChatView.vue`（挂载时加载历史续聊、`status` 占位「报告生成中，请稍候…」+ 报告全文一次性替换占位、finished 会话自动跳报告页）
- 测试：`tests/test_stream.py`（TokenStreamHandler 单测 8 例 + `_stream_task` 心跳/事件转发 2 例）、`tests/test_stream_integration.py`（skip 出题逐 token + 报告占位一次性输出 2 例）、`tests/test_sessions_messages.py`（历史接口 4 例）

**验证结果**
- pytest：113 passed（原 97 + 新增 16 例）
- ruff check + format：全通过（ruff 0.16 将 `except (A, B)` 规范化为 `except A, B`——Python 3.14 恢复无括号 except 元组语法，语义等价）
- 前端：`npm run build`（tsc + vite）通过

**项目结构更新**
- `app/api/chat.py`、`app/api/sessions.py`、`app/llm/client.py`、`app/interview/nodes/__init__.py`：更新
- `web/src/api/types.ts`、`web/src/api/client.ts`、`web/src/views/ChatView.vue`：更新
- `tests/test_stream.py`、`tests/test_stream_integration.py`、`tests/test_sessions_messages.py`：新增
- `docs/troubleshooting.md`（第 9~11 条）、`docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 真实 LLM 冒烟联调：修复 2 个仅真实调用暴露的问题

**描述**：启动服务用真实 DeepSeek Key 走通完整面试主流程（开场白 → 出题 → 回答评估追问 → hint → skip → 提前结束 → 导出报告 → 会话状态同步），期间修复 2 个 mock 测试无法暴露的真实调用缺陷。

**变更内容**
- `app/llm/client.py`：`stream_options` 从实例级 `model_kwargs` 移至 `stream()` 调用级（`astream(messages, stream_options=...)`），修复非流式请求携带 `stream_options` 被 DeepSeek 400 拒绝；`complete_sync` 改用同步 `llm.invoke()`（原 `asyncio.run` 每次新建事件循环，openai AsyncClient 缓存旧 loop 引用导致第二次调用 `Event loop is closed`）
- `tests/test_client.py`：`FakeChat.astream` 补 `**kwargs`；新增 `complete_sync` 成功/失败 2 例

**验证结果**
- pytest：96 passed（原 94 + 新增 2 例）
- ruff check + format：全通过
- 真实冒烟：9 步链路全部 200（首次对话 2.5s / 回答评估 8.7s / hint 2.7s / skip 4.8s / finish 11.1s / report 导出 2.5KB Markdown）
- `docs/troubleshooting.md` 回填第 7、8 条

**项目结构更新**
- `app/llm/client.py`、`tests/test_client.py`：更新
- `docs/troubleshooting.md`、`docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 8g：前后端联调收尾（hint/skip/skip_opening + 前端静态托管）

**描述**：修复 3 个后端缺口（hint 提示、skip 跳题、skip_opening 开场白开关）并完成前后端联调验证——FastAPI 托管前端 dist 产物 + SPA 路由兜底，浏览器可直接访问。

**变更内容**
- `app/api/chat.py`：首次调用返回全部 AI 消息（开场白 + 题干拼接，修复开场白被题干覆盖丢失）；hint 分支（LLM 生成提示、每题限 1 次、写回 checkpointer）；skip 分支（推进 `question_index`、末题直接调 `report_node` 生成报告）；**修复 skip 后题号未写回 checkpointer 的 bug**（`update_state` 结果并入 `question_index`，此前末题 skip 永远进不了 report 分支）
- `app/main.py`：`/assets` 静态文件挂载 + SPA 兜底路由（排除 `/api` 前缀）
- `tests/test_chat_actions.py`：新增 5 例（hint 锁定、skip 换题、末题 skip 生成报告、skip_opening 开/关）；修复 mock 未覆盖 `complete_sync`/`complete` 且 `app.state.llm_client` 未替换为 mock 导致真实 API 调用的问题

**验证结果**
- pytest：94 passed（含 8g 新增 5 例，修复 2 个真 bug：首次调用开场白丢失、skip 后题号不推进）
- ruff check + format：全通过
- 静态托管冒烟：`GET /`、`GET /chat/abc`（SPA 兜底）、`GET /assets/*.js` 均 200；`GET /api/*` 404 不误吞
- pre-commit：沙箱网络无法拉取 GitHub hook 仓库（已知环境问题），以 ruff + pytest 等价验证

**项目结构更新**
- `app/api/chat.py`、`app/main.py`：更新
- `tests/test_chat_actions.py`：新增
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · 新增踩坑记录文档 docs/troubleshooting.md

**描述**：建立踩坑记录文档，回填项目已踩 6 个坑（沙箱 pre-commit、loguru 花括号、evaluate 拓扑缺陷、mock 不一致、report 写回、count 校验）。

**变更内容**
- `docs/troubleshooting.md`：新增，格式固定为 现象/根因/修复/验证/涉及文件；增量文档，不参与三文档大改动同步约定

**验证结果**
- 无代码改动，文档内容核对无误

**项目结构更新**
- `docs/troubleshooting.md`：新增
- `CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 7：报告生成（结束流程 + 导出）+ 图拓扑缺陷修复

**描述**：完成报告生成链路——提前结束/自然结束/导出下载，并修复 evaluate 节点无入口的图拓扑缺陷。

**变更内容**
- `app/api/sessions.py`：新增 `POST /{id}/finish`（提前结束：直接调 report_node + `compiled.update_state` 写回 checkpointer 供导出）+ `GET /{id}/report`（Markdown 文件下载，Content-Disposition attachment）
- `app/api/chat.py`：报告生成后同步 `session_store.update_status("finished")`；`_extract_latest_ai` 修复（区分 AIMessage / dict 格式）
- `app/interview/graph.py`：**拓扑修复**——`route_after_start` 新增判断：`current_question` 非空 → 返回 `evaluate`（回答后重新 invoke 进入评估而非重新出题），条件边映射补 `evaluate`；原设计 evaluate 无入口导致评估永不执行（测试假通过）
- `app/interview/nodes/__init__.py`：修复 Python 2 语法 `except json.JSONDecodeError, TypeError:` → `except (json.JSONDecodeError, TypeError):`
- `tests/test_report.py`：新增 6 例（提前结束无分/有分/重复结束、导出未结束/成功、自然结束状态同步），mock LLM 覆盖多轮问答链路

**验证结果**
- `pytest tests`：89 passed（新增 6 例，含 count=5 完整 5 轮自然结束链路）
- ruff check + format：全通过（自动修复 2 处 + 格式化 2 文件）
- `pre-commit run --all-files`：五钩子全部通过（conda base 重装 pre-commit 后运行）

**项目结构更新**
- `app/api/sessions.py`、`app/api/chat.py`、`app/interview/graph.py`、`app/interview/nodes/__init__.py`：更新
- `tests/test_report.py`：新增
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 6b：SSE 端点集成会话管理完成

**描述**：chat.py 集成 Key 快照获取 + checkpointer thread_id 恢复 + 首次调用初始化 state + 运行时注入字段声明。

**变更内容**
- 重写 `app/api/chat.py`：首次调用检测（checkpointer 无状态 → `initial_state()` 初始化）+ Key 快照注入 state（`_api_key`）+ 后续调用注入用户回答 + 状态恢复 + `_extract_latest_ai` 修复（区分 AIMessage / dict 格式）
- 更新 `app/interview/state.py`：InterviewState 新增运行时注入字段声明（`_api_key` / `_topic` / `_needs_followup` / `_followup_reason` / `_report`），避免 LangGraph 丢弃未声明字段
- 更新 `app/interview/graph.py`：`compile_graph` 新增 `checkpointer` 参数
- 更新 `app/main.py`：`compile_graph` 传入 checkpointer
- 更新 `app/store/checkpointer.py`：新增 `delete_thread()` 占位（P0 no-op，P2 SqliteSaver 补齐）
- 更新 `tests/test_chat.py`：新增 6 例（`_extract_latest_ai` 3 + 首次调用初始化 1 + 第二次调用注入回答 1），mock LLM + checkpointer 集成测试

**验证结果**
- `pytest tests`：83 passed（新增 6 例，mock LLM 全链路集成测试通过）
- ruff check + format：全通过
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/api/chat.py`、`app/interview/state.py`、`app/interview/graph.py`、`app/main.py`、`app/store/checkpointer.py`：更新
- `tests/test_chat.py`：更新
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 6a：会话管理 API + 全局 Key 配置完成

**描述**：实现会话管理 API（新建/列表/删除）+ 全局 Key 配置端点（设置/获取掩码）+ KeyStore 全局 Key 存取 + 会话级快照绑定。

**变更内容**
- 更新 `app/llm/keys.py`：KeyStore 新增全局 Key 存取（`set_global_key` / `get_global_key` / `get_global_masked`）+ `snapshot_from_global`（新建会话时从全局 Key 快照绑定到 session_id）
- 新建 `app/api/sessions.py`：会话 CRUD API（POST 新建含场景/题目数/skip_opening 校验 + Key 快照绑定；GET 列表按创建时间倒序；DELETE 同步清理 SessionStore + KeyStore）
- 新建 `app/api/settings.py`：全局 Key 配置 API（PUT 设置含 sk- 前缀校验；GET 返回掩码 + is_set 状态）
- 更新 `app/main.py`：挂载 sessions_router + settings_router
- 新建 `tests/test_api_sessions.py`（14 例：Key 设置/校验/掩码 4 + 会话新建/列表/删除/校验 10）

**验证结果**
- `pytest tests`：77 passed（新增 14 例）
- ruff check + format：全通过（B904 raise from + E501 修复）
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/api/sessions.py`、`app/api/settings.py`：新建
- `app/llm/keys.py`、`app/main.py`：更新
- `tests/test_api_sessions.py`：新建
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 5：SSE 接口完成

**描述**：实现 SSE 对话端点（全局单流式锁 + 心跳 + 4 种事件类型）+ 会话存储抽象 + lifespan 初始化 + 依赖注入。

**变更内容**
- 新建 `app/store/checkpointer.py`：checkpointer 抽象（P0 MemorySaver / P2 SqliteSaver 可换）
- 新建 `app/store/sessions.py`：SessionMeta + SessionStore Protocol + InMemorySessionStore（create/get/list/update_status/delete）
- 新建 `app/api/deps.py`：依赖注入（get_llm_client / get_key_store / get_session_store / get_session）
- 新建 `app/api/chat.py`：SSE 端点 + `_stream_lock`（asyncio.Lock 全局单流式）+ 4 种事件（token/heartbeat/done/error）+ `_sse_event()` 格式化 + 异常路径释放锁
- 重写 `app/main.py`：lifespan 初始化全局单例（config/llm_client/key_store/session_store/checkpointer/compiled_graph）+ 挂载 chat router
- 更新 `pyproject.toml`：ruff lint ignore B008（FastAPI Depends 标准模式）
- 更新 `tests/test_config.py`：env 注入测试隔离环境变量（避免真实 .env 干扰）
- 新建 `tests/test_sessions.py`（6 例）+ `tests/test_chat.py`（7 例：SSE 事件格式 4 + 单流式锁类型 + 404 + health）

**验证结果**
- `pytest tests`：64 passed（新增 13 例）
- ruff check + format：全通过（B008 全局忽略）
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/store/`（2 文件）、`app/api/`（2 文件）：新建
- `app/main.py`、`pyproject.toml`、`tests/test_config.py`：更新
- `tests/test_sessions.py`、`tests/test_chat.py`：新建
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 4b：节点实现 + prompts 完成

**描述**：实现 5 个面试编排节点函数（opening 固定文案 / ask_question 实习·全职双版 LLM 出题 / evaluate 四维打分+追问判断 / follow_up 追问 / report Markdown 报告）+ prompt 模板文件。prompts 经用户过目定稿，待 P1 RAG 引入后再优化。

**变更内容**
- 新建 prompt 模板：`app/interview/prompts/opening.py`（固定文案）、`ask_question.py`（实习/全职双版）、`evaluate.py`、`follow_up.py`、`report.py`
- 重写 `app/interview/nodes/__init__.py`：5 节点函数实现；opening 不调 LLM；ask_question 按场景选 prompt + JSON 解析（容错 fallback）；evaluate 四维打分 + needs_followup 判断 + 无需追问时推进 question_index；follow_up 递增计数；report 输出 Markdown + status=finished
- `app/interview/graph.py`：占位 stub 替换为真实节点（`functools.partial` 注入 DeepSeekClient）；`build_graph` / `compile_graph` 新增 `llm` 参数；`route_after_evaluate` 边界调整（evaluate 推进后 `question_index >= question_count` → report）
- `app/llm/client.py`：新增 `complete_sync()`（同步包装，供节点函数使用；检测运行中的 event loop 时拒绝调用）
- 新建 `tests/test_nodes.py`（11 例，mock LLM `complete_sync`）；更新 `tests/test_graph.py`（适配新签名 + 边界条件）

**验证结果**
- `pytest tests`：51 passed（节点单测 11 + 路由 9 + 图构建/编译 2 + 原有 29）
- ruff check + format：全通过（prompt 模板 E501 用 noqa 抑制）
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/interview/prompts/`（5 文件）、`app/interview/nodes/__init__.py`：新建/重写
- `app/interview/graph.py`、`app/llm/client.py`：更新
- `tests/test_nodes.py`、`tests/test_graph.py`：新建/更新
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 4a：InterviewState + 图骨架完成

**描述**：实现 LangGraph 面试编排图的数据模型与图骨架——InterviewState（P0 核心字段 + P1/P2 预留）+ 5 节点占位 + 2 条件路由（开场白可跳过、evaluate 三向分支）+ 图编译通过。参考 Dify chatflow 设计：预留 question_bank/difficulty_stage/asked_ids/answered_qa 字段供 P1/P2 无缝接入。

**变更内容**
- 新建 `app/interview/state.py`：`InterviewState`（TypedDict，messages 用 `add_messages` reducer）+ `Score`（四维评分）+ `initial_state()` 工厂函数；P0 核心 10 字段 + P1/P2 预留 4 字段（difficulty_stage/question_bank/asked_ids/answered_qa）+ `skip_opening`
- 新建 `app/interview/graph.py`：5 节点占位 stub + `route_after_start()`（skip_opening 判断）+ `route_after_evaluate()`（追问/下一题/报告三向分支，追问优先级最高、追问耗尽后最后一题进 report）+ `build_graph()` + `compile_graph()`；图拓扑：START→[opening|ask_question]→END(暂停) | evaluate→[follow_up|ask_question|report] | follow_up→END(暂停) | report→END
- 新建 `tests/test_state.py`（4 例）、`tests/test_graph.py`（9 例）

**验证结果**
- `pytest tests`：41 passed（state 默认值/TypedDict/Score；路由 7 路径 + 图构建 + 编译）
- ruff check + format：全通过
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/interview/state.py`、`app/interview/graph.py`：新建
- `tests/test_state.py`、`tests/test_graph.py`：新建
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 3：LLM 客户端完成

**描述**：实现 DeepSeek 客户端封装（超时 / 重试 / 流式逐 token / Token 用量与 TTFT 打点、失败转业务异常）与 API Key 管理（sk- 前缀校验、掩码、会话级快照：新会话新 Key、进行中沿用旧 Key）。

**变更内容**
- 新建 `app/llm/keys.py`：`validate_api_key()`（sk- 前缀 + 非空内容校验）、`KeyStore`（会话 -> Key 快照，register/get/masked/delete，P0 内存态）
- 新建 `app/llm/client.py`：`DeepSeekClient`（按 Key 缓存 ChatDeepSeek 实例，会话间 Key 互不串用）+ `stream()`（流式逐 token、TTFT 打点、usage 记录、失败抛 `LLMError`）+ `complete()`（非流式，返回文本+用量）+ `LLMError`（N-3 业务降级边界）
- `app/config.py`：llm 配置新增 `max_retries=2`
- 新建 `tests/test_keys.py`（6 例）、`tests/test_client.py`（8 例，mock ChatDeepSeek 不真实调 API）

**验证结果**
- `pytest tests`：27 passed（-W error::ResourceWarning 无告警）
- ruff check + format：全通过
- 真实 `ChatDeepSeek` 实例化验证：model=deepseek-v4-flash、max_retries=2、timeout=60（未发请求）
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/llm/keys.py`、`app/llm/client.py`：新建
- `app/config.py`：更新（llm.max_retries）
- `tests/test_keys.py`、`tests/test_client.py`：新建
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 2：配置 + 日志层完成

**描述**：实现配置层（omegaconf 默认值 < conf/config.yaml < 环境变量三层合并、.env 注入、端口 8000 可配、Key 掩码）与日志层（loguru 结构化 JSON：ISO8601 时间戳、耗时明细、TTFT>5s 慢请求告警、Key 脱敏）。

**变更内容**
- 新建 `app/config.py`：`load_config()`（默认值 < conf/config.yaml（可选） < .env/环境变量）+ `mask_secret()`（sk-••• 掩码）；Key 不落日志/响应体
- 新建 `app/logging.py`：`setup_logging()`（stderr + logs/app_YYYYMMDD.log 滚动保留，JSON 单行输出：ts/level/logger/msg + extra 扁平）+ `log_ttft()`（阈值超限记 WARNING 告警）+ 脱敏正则（`sk-[A-Za-z0-9]{16,}` → `sk-•••`）
- 新建 `tests/test_config.py`（6 例）、`tests/test_logging.py`（6 例）
- 说明：loguru 对 callable format 返回值会再 `format_map`，故 JSON 生成与花括号转义分层（`_record_to_json` / `_json_formatter`），模板化后无损还原

**验证结果**
- `pytest tests`：12 passed（config 默认值/注入/优先级/非法值回退/掩码；logging JSON 结构/extra 扁平/脱敏/TTFT 告警/ISO8601）
- ruff check + format：全通过（修复 UP017 `datetime.UTC` 别名 6 处 + 格式 1 文件）
- 真实 `.env` 加载验证：port=8000、model_id=deepseek-v4-flash、Key 掩码 sk-•••、timeout=60
- `pre-commit run --all-files`：五钩子全部通过

**项目结构更新**
- `app/config.py`、`app/logging.py`：新建
- `tests/test_config.py`、`tests/test_logging.py`：新建
- `docs/project-status.md`、`CHANGELOG.md`：更新

## 2026-09-16 · P0 步骤 1：工程脚手架完成

**描述**：完成 P0 第 1 步工程脚手架（uv 初始化、pyproject 依赖、ruff/pre-commit 配置、.env/.env.example、目录骨架），并解决 pre-commit 在 TRAE 沙箱环境下的首次初始化问题。

**变更内容**
- 新建 `pyproject.toml`：运行时依赖（fastapi / uvicorn / langchain-deepseek / langgraph / omegaconf / python-dotenv / loguru）+ 开发依赖（pytest / pytest-asyncio / ruff / pre-commit）+ ruff / pytest 工具配置
- 新建 `.env`（LLM 配置，gitignore 排除）+ `.env.example`（配置模板）
- 新建 `.gitignore`：Python / Env / IDE / Node / OS / Logs / Runtime 规则，含 `.tmp/`、`.trae-html-share-packages/`
- 新建 `.pre-commit-config.yaml`：ruff + ruff-format + pre-commit-hooks（大文件 / EOF / 尾随空白）
- 新建 `app/` 分层目录骨架（api / interview / nodes / prompts / llm / store）+ `app/main.py`（FastAPI 入口 + `/health`）
- 新建 `tests/`、`web/` 空目录
- `uv sync` 完成依赖安装（.venv + uv.lock）
- git 状态整理：撤销 `.idea/` 意外暂存，暂存全部项目文件（.env / .tmp / .idea 按规则排除）
- pre-commit 沙箱绕行：`PRE_COMMIT_HOME` / `TMP` / `TEMP` 重定向至项目内 `.tmp/`，以 Conda base Python 完成首次 hook 初始化

**验证结果**
- `uv sync` 成功：venv 关键依赖（fastapi / langgraph / loguru / omegaconf）可导入，uv.lock 生成
- `pre-commit run --all-files` 五个钩子全部通过（ruff / ruff format / EOF / 尾随空白 / 大文件，EXIT 0）
- `git status` 暂存清单与预期一致（.idea 已移出跟踪，.env / .tmp 未纳入）

**项目结构更新**
- `pyproject.toml`、`.env`、`.env.example`、`.gitignore`、`.pre-commit-config.yaml`：新建
- `app/`（main.py + 分层包）、`tests/`、`web/`：新建
- `CHANGELOG.md`：更新

## 2026-09-16 · Embedding 模型可配置决策（方案 A 绑定+重建）

**描述**：确认 Embedding 模型可配置（本地 bge-large-zh-v1.5 / 外部 API 二选一），采用「知识库绑定 model_id + 切换重建索引」方案，外部 API 加数据外发提示；PRD 新增 P1-7 验收，架构迭代至 v0.2。

**变更内容**
- `docs/prd.md`：F4 补「Embedding 模型可配置 + 库绑定 model_id + 切换重建 + 外发提示」；F6 Embedding 配置改为「本地 bge / 外部 API 可选，切换触发重建」；已确认决策新增 Embedding 行；P1 退出条件 P1-1~P1-6 → P1-1~P1-7；验收标准新增 P1-7
- `prd/prd.html`：同步 12 处（原型检索设置卡、环境配置页 Embedding 卡新增二选一切片 + 外发提示 JS、已确认决策块、F4 业务逻辑/字段规则/边界异常、F6 页面布局/字段规则/边界异常、P1 验收 P1-7）；修正 F4 原「768 维」笔误为「1024 维」
- `docs/architecture.md`：v0.1 → v0.2（总体架构 P1 追加说明 + 核心模块新增 `retrieval/embedding.py` 行 + 迭代记录 v0.2 行）
- `docs/project-status.md`：里程碑时间线、已完成事项、决策日志索引各新增条目

**验证结果**
- `prd/prd.html` 标签配对（section 7/7、div 284/284、table 24/24、tr 138/138）+ JS 语法检查通过 + 关键字存在性通过
- 三文档关键字（model_id / 重建索引 / P1-7 / v0.2 / embedding.py）grep 命中

**项目结构更新**
- `docs/prd.md`：更新
- `prd/prd.html`：更新
- `docs/architecture.md`：更新
- `docs/project-status.md`：更新
- `CHANGELOG.md`：更新

## 2026-09-16 · 新增 AI 协作工作流约定

**描述**：在项目根目录新建 `AI_Workflow.md`，定义结对工程师协作工作流；约定此后每次执行代码修改任务前先查看该文档。

**变更内容**
- 新建 `AI_Workflow.md`：角色（结对工程师）、最高原则 3 条、三阶段工作流（需求沟通 → 执行计划 → 分步执行）、改动范围（仅项目根目录）、沟通格式（标注阶段、一次最多 3 问、用“我计划……是否同意？”确认）、验证要求（不假装运行过测试）
- 改动范围占位符 `<目录>` 按确认填为项目根目录 `d:\pycharm_project\mock_interview_agent`

**验证结果**
- 文件内容与用户提供的约定核对一致，占位符已替换

**项目结构更新**
- `AI_Workflow.md`：新建
- `CHANGELOG.md`：更新

## 2026-09-16 · 建立全局上下文三文档体系

**描述**：为 PRD / 项目架构 / 当前项目阶段创建 Markdown 文档，作为项目全局上下文；约定大改动时三文档 + CHANGELOG 同步更新。

**变更内容**
- 新建 `docs/prd.md`：PRD 同步镜像（产品定位、范围分期、项目边界、F1~F6 需求摘要、R1~R6 规则、A/P0/P1/P2/N 验收标准摘要、已确认决策、待确认项），注明完整交互版以 `prd/prd.html` 为准
- 新建 `docs/project-status.md`：项目阶段状态（里程碑时间线、当前阶段、已完成事项、已知问题/待确认/风险、P0 分步执行 9 步计划、文档维护约定、决策日志索引）
- `docs/architecture.md`：头部补全局上下文三文档互链说明
- 同步约定：大改动（涉及需求范围 / 架构形态 / 阶段状态任一）触发 `docs/prd.md` + `docs/architecture.md` + `docs/project-status.md` + `CHANGELOG.md` 四份同步更新

**验证结果**
- 三文档互链与内容覆盖检查通过：prd.md 覆盖 HTML 版全部关键章节；project-status.md 覆盖进度/已知问题/下一步；architecture.md 互链已补

**项目结构更新**
- `docs/prd.md`：新建
- `docs/project-status.md`：新建
- `docs/architecture.md`：更新（互链）
- `CHANGELOG.md`：更新

## 2026-09-16 · 架构草案 v0.1

**描述**：P0 执行前产出轻量架构草案，明确分层、核心模块、数据模型与服务端边界；约定迭代必须记录原因。

**变更内容**
- 新增 `docs/architecture.md`（v0.1）：单进程 Monolith 分层（api 薄路由 → interview 领域层 → llm/store 基础设施）；目录架构（app/ + web/ + tests/）；核心模块表（含关键约束）；数据模型（InterviewState + SessionMeta，P0 内存 / P2 SQLite）；9 项「必须服务端」逻辑清单（Key 管理、状态真源、全局单流式锁、评分报告、计数真源等）；6 条架构原则（服务端状态唯一真源、存储抽象先行、Key 会话级快照等）；文档内置「迭代记录」表，约定每次迭代同步记录触发原因与验证

**验证结果**
- 结构评审：草案覆盖 P0 8 项需求决策 + 边界 5 项 + 非功能 N-1~N-9（单流式锁、日志打点、掩码、重启提示均有关键约束对应）

**项目结构更新**
- `docs/architecture.md`：新建
- `CHANGELOG.md`：更新

## 2026-09-16 · 技术栈整理进 PRD

**描述**：将完整技术栈按层整理落档至 PRD「技术方案」章节，并补充存储三块划分说明。

**变更内容**
- `prd/prd.html`「技术方案」表格补齐：新增「分词（jieba，配合 ES ik，P1 用）」「简历存储（文件系统 / SQLite blob，暂不上 MySQL）」两行；工程行补充 python-dotenv 与 pytest（Key 明文存 .env + gitignore，pytest 用于自动化验收）
- 新增「存储三块划分」小节：对话历史/会话状态 → SqliteSaver（P0 MemorySaver / P2 SqliteSaver）；简历 → 文件系统 / SQLite blob；知识集 → Qdrant（子块向量）+ ES（父块正文，ik 分词）

**验证结果**
- PRD HTML 标签配对完整（section 7/7、div 280/280、table 24/24、tr 136/136）
- 新增内容存在性校验通过（jieba 行、存储三块划分、pytest 行）

**项目结构更新**
- `prd/prd.html`：更新
- `CHANGELOG.md`：更新

## 2026-09-16 · P0 需求澄清完成

**描述**：完成 P0 需求澄清（8 项决策树式确认），产品名定为「AI 面试官」，全部决策落档至 PRD V1.0。

**变更内容**
- 决策确认：产品名「AI 面试官」；题目数量默认 10（5–30）；每题提示 1 次；实习 / 全职追问同轮次（1–2 轮），难度差异靠题目本身（修改原默认「实习 ≤ 1」）；LLM Key `sk-` 前缀校验；Key 变更后新会话生效、进行中会话沿用旧 Key；报告导出 Markdown；P0 断点续聊用 MemorySaver（后端重启会话丢失并提示，P2 换 SqliteSaver）
- `prd/prd.html`：产品名全局替换（标题 / 框架顶栏 / 原型 logo 与路由 `ai-interviewer.app` / 文档视图标题 / 示例数据引用）；待确认项更新为「已确认（2026-09-16）+ 仅剩降级阈值待 P1 确认」；F2 字段规则与 R1 规则去除提示次数、追问轮次的 [待确认] 并同步"两场景同轮次"表述；F5 导出格式定为 Markdown；F6 去除 Key 校验与生效策略的 [待确认]

**验证结果**
- PRD HTML 标签配对完整（section 7/7、div 280/280、table 23/23）
- 产品名替换残留检查通过（无「模拟面试 Agent」/ `mockinterview` 残留；剩余 3 处「模拟面试」为功能描述）
- 待确认标记仅剩 1 处（P2 web_verify 触发方式，属后续阶段）；JS 语法检查通过

**项目结构更新**
- `prd/prd.html`：更新
- `CHANGELOG.md`：更新

## 2026-09-15 · 明确项目边界与非功能需求

**描述**：在 P0 开发启动前，完成需求澄清阶段的项目边界确认与非功能需求扩充，并落档至 PRD V1.0。

**变更内容**
- 需求澄清（决策树式逐项确认，8 项）：部署形态（单机本地）、数据生命周期（删除即物理删）、并发边界（同会话串行 + 全局单流式）、Key 存储（明文 .env + gitignore）、性能指标（补充 TTFT ≤ 3s）、可观测性（完整：JSON 日志 + 耗时明细 + 慢请求告警）、兼容基线（Chrome/Edge 近 2 主版本 + Safari 17.4+）、依赖服务（docker-compose 一键起 + 缺失降级）；另确认一组低风险默认值（端口 8000 可配置、Key 全程掩码、会话不设上限、上传 ≤ 10MB、ISO8601、SSE 心跳 15s）
- `prd/prd.html`：概览新增「项目边界」小节（5 项边界约定表）；验收标准 N 组由 3 条扩充为 9 条（N-1 延迟含 TTFT、N-2 安全含 Key 掩码、N-3 异常降级、N-4 依赖可用性、N-5 可观测性、N-6 兼容性、N-7 并发、N-8 数据安全、N-9 配置默认）

**验证结果**
- PRD HTML 标签配对完整（section 7/7、div 280/280、table 23/23、tr 130/130）
- 新增章节内容存在性校验通过（「项目边界」小节、N-9 条目）

**项目结构更新**
- `prd/prd.html`：更新
- `CHANGELOG.md`：新建
