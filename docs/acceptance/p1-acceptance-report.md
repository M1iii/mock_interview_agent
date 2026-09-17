# P1 知识库检索验收报告（草稿）

- 验收日期：2026-09-17
- 验收范围：P1-1 入库 / P1-2 召回 / P1-3 引用 / P1-4 降级 / P1-5 级联删除 / P1-6 P95 / P1-7 切换重建
- 验收脚本：`_acceptance_p1.py`（`uv run python _acceptance_p1.py` 全量串行，不带 `--keep`）
- 退出口径：passed=11 failed=3（P1-3/P1-4 decline/P1-7 观察项 FAIL，搁置待 P2 后修复复测）
- 状态：P1 验收完成，3 项 FAIL 搁置（P1-3 引用准确率 28%、P1-4 decline 子项、P1-7 观察项），进入 P2 澄清

## 1. 环境信息（运行探测结果）

| 组件 | 地址/标识 | 探测结果 |
| --- | --- | --- |
| Qdrant | http://127.0.0.1:6333 | 可用（qdrant - vector search engine，collection=kb_blocks） |
| Elasticsearch | http://127.0.0.1:9200 | 可用（index=kb_blocks） |
| TEI Embedding | http://127.0.0.1:8081/v1 | 可用；bge-large-zh-v1.5，输出 1024 维 |
| DeepSeek LLM | https://api.deepseek.com（deepseek-chat） | 可用；Key 由 `.env` LLM_API_KEY 注入，P1-3 完成 50 题引用判定 |
| 检索参数 | semantic_weight=0.6 / threshold=0.6 / weak_threshold=0.45 / top_k=5 | 配置文件默认值 |

运行说明：首轮（15:07 起）TEI 中段出现瞬时断连（`Server disconnected without sending a response`），
导致 P1-1 入库 1/5、P1-4 双路/语义路项出现异常 FAIL；环境恢复后复跑（15:15 起）全部项目正常执行，
以下数据以复跑为准（首轮异常已在归因中说明，不纳入最终结论）。

## 2. 七项验收结果表（标准 / 实测 / 结论）

| # | 验收项 | 标准 | 实测 | 结论 |
| --- | --- | --- | --- | --- |
| P1-1 | 入库成功率 | ≥95%（5 篇全部成功） | 5/5 = 100%；幂等重跑块数一致 | **PASS** |
| P1-2 | Top-K=5 召回命中率 | gold 定位 50/50；命中率 ≥80% | gold 定位 50/50；召回 50/50 = 100%，miss 无 | **PASS** |
| P1-3 | 引用准确率（normal 级） | ≥90% 且 judged≥40 | judged=50/50；cites 40/144 = **28%** | **FAIL** |
| P1-4 | 四级降级 | 双路→normal/weak；语义单路→fallback；关键词单路→fallback；无关→decline | 双路=normal(5 cites)；语义路=fallback；关键词路=fallback；**无关=fallback（decline 分支不可达）** | **FAIL**（仅 decline 子项） |
| P1-5 | 删除级联 | 文件级/库级 Qdrant+ES 均 0 残留，元数据清除 | 文件级 qdrant=0 es=0；库级 qdrant=0 es=0 meta_left=False | **PASS** |
| P1-6 | 单次检索 P95 | ≤2000ms | P95=134ms P50=111ms max=143ms | **PASS** |
| P1-7 | Embedding 切换重建 + 绑定一致 | rebuild failed=0；kb2 绑定（model_id/dims）一致；全库 READY；抽样 5 题命中 ≥4 | rebuild ok=5 failed=0；binding_ok=True；files_ok=True；**sample_hit=5/5** | **PASS** |

汇总：**passed=11 / failed=3**。

## 3. 未通过 / 未命中清单与归因

### P1-3 引用准确率（FAIL，28%）

- 实测：judged=50/50，144 条引用中仅 40 条被裁判判定支撑题目。
- 修复历程：引用文本装配从「命中子块文本」改为「按 parent_id 回查 ES 父块全文」（`_backfill_parent_text`），
  并取消截断（`_SNIPPET_LEN=0`）。准确率从 12% 提升到 28%，judged 恢复到 50/50。
- 残留根因（搁置待 P2 后排查）：
  1. 引用准确率仍远低于 90% 标准——需采样分析 false 样本，排查是文档/题库质量问题还是裁判标准问题；
  2. 首轮 TEI 断连期（仅关键词路召回）该指标为 35%，当前 28% 未恢复到首轮水平——可能与 LLM 裁判随机性有关。
- 处理：按用户裁决搁置，P2 完成后回来排查文档/题库质量 + 调整裁判口径后复测。

### P1-4 无关查询 → decline（FAIL，level=fallback）

- 实测：`今天天气怎么样明天会下雨吗` 返回 level=fallback 且带引用，未达 decline。
- 修复尝试：A+B 方案（Qdrant score_threshold + ES minimum_should_match）。
  首轮 score_threshold=0.3/min_should_match=75% → decline 可达但正常查询也被过滤（双路/关键词路 FAIL）；
  调低到 0.15/50% → 更差（judged=13/50）；最终去掉 score_threshold=0.0 + 25% → judged=50 恢复但 decline 再次不可达。
  核心矛盾：bge-large-zh-v1.5 的 cosine 分布与分级阈值体系不匹配——相关查询的 cosine 普遍在 0.1~0.3，
  任何 score_threshold 都会误杀正常查询；而不过滤则无关查询仍返回 top-k 低分命中。
- 处理：按用户裁决搁置，P2 完成后回来重新设计降级策略（可能需从 cosine 分数分布出发重新标定阈值，
  或改用分级层分数地板方案 C）。

### P1-7 观察项（记录型 FAIL，非应用缺陷）

- 内容：查询模型 ≠ 库绑定模型时的拒绝校验未实现（architecture v0.4 §4.3 约束在检索链路无实现）。
- 处理：已如实记录为 FAIL，交用户裁决是否补实现；不影响 P1-7 主项结论（切换重建、绑定一致、
  抽样检索均通过）。

## 4. 观察项

- P1-7 观察项：查询模型≠绑定模型拒绝校验未实现（见 3.3），记录待用户裁决。

## 5. 语料与题库说明

- 语料：`tests/acceptance/corpus/` 下 5 篇多栈 Markdown（java-concurrency / mysql / network / os / redis），
  每篇 10 个考点，共 50 考点；入库采用父子切块（父块 ≤800 字，子块 ≤200 字滑窗），
  Qdrant 存子块向量、ES 存父块全文（ik 索引）。
- 题库：`tests/acceptance/questions.json` 共 50 题，每题预标 `gold_snippet`（标准出处句子），
  验收时经 ES match 全文逐字定位唯一父块作为 gold 出处（50/50 定位成功）。
- 切换验证（P1-7）：独立库 kb2（bge-large-zh-v1.5 / 1024 维）入库 5 篇 → 构造切换后 embedding
  实例（model_id 标记为 `bge-large-zh-v1.5-switched`，TEI 忽略 model 字段向量仍可用）→
  全库重建 ok=5 failed=0 → kb2 绑定更新为 switched/1024、全库文件 READY → 抽样 5 题
  （gold 于 kb2 内定位）检索命中 5/5。
- 清理：主验收库与 kb2 均已删除（Qdrant/ES/元数据三处 0 残留），语料文件保留（git 受控，未 unlink）。
