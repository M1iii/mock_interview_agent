# AI 面试官 · 踩坑记录（Troubleshooting）

> 记录项目开发中踩过的坑：现象、根因、修复、验证、涉及文件。
> 增量文档——只在踩坑时追加，不参与三文档 + CHANGELOG 的"大改动同步"约定。
> 最近更新：2026-09-17

---

## 1. pre-commit 在 TRAE 沙箱中无法运行（只读缓存目录）

**现象**
- `pre-commit run --all-files` 报 `FileNotFoundError: No usable temporary directory found`
- 换 Conda base 环境后报 `sqlite3.OperationalError: attempt to write a readonly database`
- 以及 `PermissionError: [Errno 13] Permission denied: 'C:\Users\Mizuki\.cache\pre-commit\pre-commit.log'`

**根因**
- TRAE 沙箱把 `~/.cache` 与 `%LOCALAPPDATA%\Temp` 呈现为只读视图，且 `HOME` 为空
- pre-commit 无法写入缓存 DB 与日志文件

**修复**
- 将 `PRE_COMMIT_HOME` / `TMP` / `TEMP` 重定向到项目内 `.tmp/`（沙箱可写）
- 用 Conda base Python 运行：`& 'D:\miniconda\python.exe' -m pre_commit run --all-files`

**验证**
- 五钩子全部 Passed（ruff / ruff format / end-of-file / trailing-whitespace / large-files）
- `git commit` 钩子同样受限，后续提交需复用同一套环境变量

**涉及文件**
- `.pre-commit-config.yaml`、`.gitignore`（`.tmp/` 加入忽略）

---

## 2. loguru 结构化日志输出 JSON 时抛 KeyError

**现象**
- `setup_logging()` 配置 callable format 输出 JSON，运行时抛 `KeyError`（花括号相关）

**根因**
- loguru 会把 callable format 的**返回值**当作模板再次执行 `format_map`
- JSON 中的花括号 `{}` 被误认为模板占位符，触发 KeyError

**修复**
- 分层处理：`_record_to_json` 干净生成 JSON 字符串 → `_json_formatter` 将花括号转义还原
- 规避 format_map 二次解析

**验证**
- `tests/test_logging.py` 通过，JSON 日志（ts/level/msg/耗时明细）输出正确

**涉及文件**
- `app/logging.py`、`tests/test_logging.py`

---

## 3. LangGraph 图：evaluate 节点永不执行，测试"假通过"

**现象**
- 步骤 7 测试失败：finish 返回 400「无评分记录」
- 此前 `test_chat_second_call` 却通过——事后查明是**假通过**

**根因**
- LangGraph `invoke` 每次从 `START` 重新执行整图
- 图 START 只连 `opening`/`ask_question`，`evaluate` 节点**没有任何入边**，评估从未执行
- 假通过原因：mock 的 evaluate 响应被 `ask_question` 当作题干输出，测试断言只检查"包含关键词"，未覆盖实际语义

**修复**
- `route_after_start` 新增判断：`current_question` 非空 → 返回 `"evaluate"`（回答后重新 invoke 进入评估，而非重新出题）
- 条件边映射补 `"evaluate": "evaluate"`

**验证**
- `pytest tests` 89 passed（含 count=5 完整 5 轮自然结束链路）
- 链路验证：出题 → 回答 → 评估（评分落库）→ 追问/下一题/报告

**涉及文件**
- `app/interview/graph.py`、`tests/test_report.py`

---

## 4. 测试 mock 未替换 app.state.llm_client，导致真实 LLM 被调用

**现象**
- finish 端点在测试中行为异常（依赖真实 API，慢或失败）

**根因**
- `finish_session` 用 `Depends(get_llm_client)` 取 `app.state.llm_client`（lifespan 初始化的**真实** DeepSeekClient）
- 测试只替换了 `app.state.compiled_graph`，`report_node` 仍走真实 LLM

**修复**
- 测试统一 `_install_mock(llm)`：同时替换 `app.state.llm_client` 与 `app.state.compiled_graph`

**验证**
- `pytest tests` 89 passed

**涉及文件**
- `tests/test_report.py`

---

## 5. report_node 直接调用不写回 checkpointer，导出报告 404

**现象**
- 提前结束（finish）成功返回报告，但随后 `GET /report` 返回 404「报告内容不存在」

**根因**
- 方案 A：`finish_session` 直接调 `report_node(state, llm)` 不走图
- 返回值未持久化到 checkpointer，`_report` 字段仍为空

**修复**
- 调用后补 `compiled.update_state(config, result)`，把报告输出写回 checkpointer

**验证**
- `test_get_report_success`：200 + Markdown 文件下载（Content-Disposition attachment）

**涉及文件**
- `app/api/sessions.py`

---

## 6. 测试误用 question_count=1，被 API 校验 422 拦截

**现象**
- 测试创建会话报 `KeyError: 'id'`——`resp.json()` 无 id

**根因**
- Pydantic `Field(ge=5)` 校验：题目数量最小 5（PRD 5–30）
- 测试用 `count=1` 模拟"最后一题"，被自动 422 拒绝

**修复**
- 测试改用 `count=5`：提前结束场景用 `_make_llm_multi`（4 响应），自然结束场景用 `_make_llm_natural(5, ...)`（11 响应）

**验证**
- `pytest tests` 89 passed

**涉及文件**
- `tests/test_report.py`

---

## 7. DeepSeek 真实调用 400：stream_options 只能与 stream=true 一起使用

**现象**
- 真实 LLM 冒烟联调，首次对话返回"服务异常，请重试"
- 服务端日志：`OpenAIInvalidRequestError('Error code: 400 - stream_options should be set along with stream = true')`

**根因**
- `DeepSeekClient._instance` 把 `stream_options={"include_usage": True}` 挂在实例级 `model_kwargs` 上
- 非流式调用 `ainvoke`/`invoke` 也会携带该参数，DeepSeek API 拒绝（stream_options 仅限流式请求）

**修复**
- 从 `model_kwargs` 移除 `stream_options`
- 改为仅在 `stream()` 方法调用时显式传参：`llm.astream(messages, stream_options={"include_usage": True})`

**验证**
- `pytest tests` 96 passed（`FakeChat.astream` 补 `**kwargs` 兼容新签名）
- 真实冒烟：首次对话流式返回开场白 + 题干

**涉及文件**
- `app/llm/client.py`、`tests/test_client.py`

---

## 8. complete_sync 用 asyncio.run 跨事件循环调 ainvoke，报 Event loop is closed

**现象**
- 真实 LLM 冒烟联调：首次对话成功，**第二次**提交回答立即失败"服务异常"
- 服务端日志：`llm complete failed: RuntimeError('Event loop is closed')`

**根因**
- `complete_sync` 在 `asyncio.to_thread` 线程内用 `asyncio.run(self.complete(...))` 每次新建事件循环
- langchain ChatOpenAI 底层的 openai AsyncClient 会缓存事件循环引用；首次 `asyncio.run` 结束后循环已关闭，复用同一 LLM 实例再调 `ainvoke` 即报错
- 测试未暴露：图节点测试全部 mock 了 LLM

**修复**
- `complete_sync` 改用**同步** `llm.invoke()`（httpx 同步客户端，不涉及事件循环），与 async 路径彻底分离
- 补 `test_complete_sync_returns_content_and_usage` / `test_complete_sync_failure_raises_llm_error` 覆盖

**验证**
- `pytest tests` 96 passed
- 真实冒烟：连续多轮（回答 → 评估追问 → hint → skip → 提前结束 → 导出）全部 200

**涉及文件**
- `app/llm/client.py`、`tests/test_client.py`

---

## 9. 节点透传 callbacks 后测试 mock 签名漂移（TypeError）

**现象**
- 流式改造后跑旧测试报 `TypeError: mock_complete() got an unexpected keyword argument 'callbacks'`
- 波及所有 mock `complete_sync` 的节点/API 测试

**根因**
- `ask_question_node` 新增 `callbacks` 参数透传给 `complete_sync`（支持 skip 出题流式）
- 测试 mock 函数签名仍是 `(api_key, prompt)`，未同步 `callbacks=None` 默认参数

**修复**
- 批量更新测试 mock 签名：`def mock_complete(api_key, prompt, callbacks=None)`
- 与第 4 条同源：mock 签名必须随生产签名同步漂移

**验证**
- `pytest tests` 113 passed

**涉及文件**
- `tests/test_nodes.py`、`tests/test_stream_integration.py` 等 mock 处

---

## 10. 题干流式输出混入「【主题】」标记行

**现象**
- 流式对话中题干末尾出现「【主题】xxx」标记行（出题 prompt 要求 LLM 输出「题干 + 主题标记」两段结构，标记仅供评估/追问使用，不应展示给候选人）

**根因**
- 非流式路径在 `_parse_question` 用 `partition("【主题】")` 截断；流式路径按 token 转发时没有截断逻辑
- 两个难点：① 标记可能跨 token 拆分（如「【主」与「题】」分两次到达），单 token find 会漏截；② 标记行行首的换行属于标记行，残留会多一个空行
- 另：LangGraph 回调只暴露 run_id 与父链，无法直接知道 token 属于哪个节点，需先记录 run 树再逆向溯源节点名

**修复**
- 新增 `TokenStreamHandler`：`on_chain_start` 记录 run_id → 名称/父链，`_resolve_node` 逆向查找节点名（ask_question/follow_up 转发，evaluate/report 不转发）
- `_strip_marker` 缓冲累积 token，命中「【主题】」后停止转发，命中前的残留头去掉行尾换行（覆盖跨 token 与同一 token 内命中两种情况）

**验证**
- `tests/test_stream.py` 单测 8 例（含跨 token 拆分、同一 token 命中、行尾换行清理）
- `pytest tests` 113 passed

**涉及文件**
- `app/api/chat.py`、`tests/test_stream.py`

---

## 11. Python 3.14 `except A, B` 无括号 except 元组（ruff 0.16 规范化，非 bug）

**现象**
- ruff format 将 `except (json.JSONDecodeError, TypeError):` 自动改写为 `except json.JSONDecodeError, TypeError:`
- 初看像 Python 2 时代语法，易被误判为 bug 回改

**根因**
- Python 3.14 起 PEP 758 恢复无括号 except 元组语法；ruff 0.16 对目标版本 3.14 采用新语法输出
- 语义与 `except (A, B):` 完全等价

**修复**
- 无需修复：接受 ruff 规范化（项目目标 Python 3.14）。若未来需兼容 3.13 及以下，需显式加回括号

**验证**
- `pytest tests` 113 passed（含 `_take_or_cancel` 的 `except asyncio.CancelledError, asyncio.InvalidStateError`）
- 真实 LLM 冒烟通过

**涉及文件**
- `app/api/chat.py`、`app/interview/nodes/__init__.py`

---

## 12. compose 首次 up 端口占用失败后残留 Created 容器：端口映射丢失 / ES 启动失败

**现象**
- `docker compose up -d` 首次失败（8081 被旧容器占用）后，清理冲突容器再 `up`：
  - qdrant/embedding 容器 `Up` 但 `docker port` 为空、宿主端口不可达（`6333-6334/tcp` 无映射）
  - ES 容器 `Exited (1)`：`InetAddress.getLocalHost` 抛 UnknownHostException → `IllegalStateException: status logger logged an error`

**根因**
- 首次失败时创建的容器（Created 状态）网络 sandbox 未正确建立；复用这些残留容器重启，端口绑定与 DNS 解析均异常

**修复**
- `docker compose down` 删除全部残留容器（卷保留），`docker compose up -d` 全新创建
- 重建后三容器端口映射正常，ES 直接 healthy

**验证**
- qdrant `0.0.0.0:6333-6334`、es `0.0.0.0:9200`（green + analysis-ik 插件）、embedding `0.0.0.0:8081` 全部可连

**涉及文件**
- `docker-compose.yml`

---

## 13. TEI 模型 warmup 期间 /v1/embeddings 返回 502 Bad Gateway

**现象**
- TEI 容器日志显示 `Ready`、端口可连（`/health` 可返回），但 POST `/v1/embeddings` 返回 502

**根因**
- TEI 的 HTTP server 先 Ready，模型 backend 仍在 CPU warmup（1.3GB safetensors 加载 + 预热，约 40~60s），期间请求统一 502

**修复**
- 等待 warmup 完成（日志出现完整 `Warming up model` 后约 40s），无需改配置

**验证**
- warmup 后 `embed_query`/`embed_documents` 均返回 1024 维向量

**涉及文件**
- 无（运行时行为）

---

## 14. TRAE 沙箱：回收站 API 不可用 + 项目目录级操作被拦截

**现象**
- `Microsoft.VisualBasic.FileIO.FileSystem::DeleteDirectory(..., 'SendToRecycleBin')` 抛 `This function is not supported on this system`
- `Rename-Item`/删除 `D:\pycharm_project\shopkeeper-agent`（项目根目录）被沙箱拦截：`Not allow operate files`

**根因**
- TRAE 沙箱为非交互会话，回收站（Recycle Bin）API 不可用；沙箱文件权限白名单仅覆盖本项目目录，跨项目目录级写操作被拦截

**修复**
- 回收站方案不可用时：同卷重命名归档（可恢复、瞬时）或由用户手动处理
- 沙箱拦截项：需用户手动执行，或配置 Settings → Permission & Approval → Custom Configuration 放行

**验证**
- 模型目录迁移（`docker/embedding/` 内）在沙箱内可正常执行；`shopkeeper-agent` 根目录操作需手动

**涉及文件**
- 无（环境行为）

---

## 15. Qdrant delete 过滤条件传 dict 被拒（Unsupported points selector type）

**现象**
- 幂等入库的"先清旧"步骤报 `ValueError: Unsupported points selector type: <class 'dict'>`

**根因**
- qdrant-client 新版 `delete()` 的 `points_selector` 只接受模型对象（Filter/PayloadSelector 等），不接受裸 dict

**修复**
- 改用 SDK 模型类构造过滤：`Filter(must=[FieldCondition(key="file_id", match=MatchValue(value=file_id))])`

**验证**
- `pytest tests` 154 passed（`test_ingest_idempotent_deletes_old_first` 覆盖）；真实冒烟幂等重建通过

**涉及文件**
- `app/retrieval/ingest.py`

---

## 16. 首次入库 Qdrant 集合不存在（404 Collection doesn't exist）

**现象**
- 首次上传文档入库报 `Unexpected Response: 404 (Not Found) Collection 'kb_blocks' doesn't exist!`

**根因**
- `_delete_old` 在 `ensure_collection`/`ensure_index` 之前执行，集合尚未创建就发起删除过滤

**修复**
- 将 `qdrant.ensure_collection(embedding.dims)` 与 `es.ensure_index()` 提前到删除旧数据之前

**验证**
- `test_ingest_creates_collection_and_index` 覆盖；真实冒烟首次入库成功

**涉及文件**
- `app/retrieval/ingest.py`

---

## 17. 测试 mock 向量数量与子块数不一致（zip() 长度不匹配）

**现象**
- 入库测试报 `ValueError: zip() argument 2 is longer than argument 1`

**根因**
- mock 的 `embed_documents` 固定返回 1 条向量，而真实子块数量由切块结果决定（可能多条），批量 zip 时长度不匹配

**修复**
- mock 改用 `side_effect=lambda texts: [[0.1] * dims for _ in texts]`，按输入文本数量动态生成等长向量

**验证**
- `pytest tests` 154 passed（ingest 相关用例全部通过）

**涉及文件**
- `tests/test_retrieval_ingest.py`
