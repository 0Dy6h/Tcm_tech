# Current State

本文件是 Tcm_tech / Qiyan Nexus 当前开发事实源索引。若历史规划、早期 prototype 或 archive 内容与本文件冲突，以本文件列出的入口为准。

## 当前事实源优先级

1. `backend/`、`frontend/` 代码与测试
2. `README.md`
3. `AGENTS.md`
4. `CLAUDE.md`
5. `CONTEXT.md`
6. `docs/adr/`
7. 最新 `docs/handoffs/`
8. `docs/archive/` 仅作历史参考

## 当前能力边界

- **2026-09-16 对抗修复**：本地 dev / preview / E2E 后端默认统一 8010，8000 保留给其他项目。PDF 实际上传使用内容绑定、长度受限的不可变 ID，旧引用字节不因同名上传改变；客户端解析携带 ID，服务和仓储 compare-and-set 拒绝过期解析，JSON 文献/chunk 更新共享文件锁并原子发布。文献、上传、eval、实体与装配计划请求完整保留 HTTP 状态；只有 404 才映射文献缺页，实体请求失败允许重试，PDF 上传成功和解析失败分开显示，过期检索被取消。长 ID/路径可在窄屏换行。RAG 签名兼容浏览器 JSON 数字往返（`1.0`→`1`），仍对完整原始字段验签，拒绝字段/值/非数值类型篡改；异常签名字符不再触发 500。证据等级、owner 边界与 opt-in 默认不变。
- **2026-09-16 依赖安全修复**：Next 固定 16.3.3，sharp/PostCSS 等传递依赖锁定已修复版本；后端提高 pypdf 6.16.1、Starlette 1.3.1、python-multipart 0.0.31 等安全下界，保留 FastAPI 0.136.3，开发依赖 transformers 使用非撤回的 5.10.4。Windows 原生后端 988 passed / 1 skipped，前端 Windows/Linux 各 309 passed，类型与生产构建通过，隔离浏览器 12 项通过。npm 复查零公告；可选 TorchScript 与 macOS sdist 两类低适用性剩余公告及验证边界见 [本轮报告](reports/2026-09-16-adversarial-evidence-review.md)。正式环境需要同步安装已验证依赖，不能仅替换源码。

- **产品方向纠偏与 Gate 2 进展（2026-07-15，ADR-0017）**：唯一主轴是“特应性皮炎中医药窄领域网络药理学自动化科研辅助平台”；文献/PDF/RAG/引用/导出是证据服务层。Gate 1 已完成研究协议持久化与 `formal_network_ready` 失败关闭。Gate 2 的双侧 raw-artifact 工程 provenance 已完成：疾病侧静态解析 Open Targets GraphQL `disease.associatedTargets`，成分侧静态解析离线 `chembl_known_activity_v1` known-activities JSON（不是 live ChEMBL API）；二者均由服务端计算 raw-byte SHA-256，并分别与 operator-controlled、只读 manifest 中登记的版本、结构化 query、query/retrieved time、threshold、mapping 和 usage note 完整比对。compound 核验只能按 `task_id + owner_id` 读取已有 `server_verified_raw_artifact` disease task，species/query_date 必须匹配其冻结研究协议，成功后创建不可变 child task，绝不修改 parent。客户端不能声明 records/hash/provenance/readiness/判定字段；disease/compound snapshots 都在 JSON/SQLite/PostgreSQL task 创建时封存且不可覆盖。disease/compound source rows 具有稳定 SHA-256 `lineage_row_id`；每个 `intersection_targets` row 是 `canonical_symbol_exact_match_v1` 派生记录，并完整引用两侧所有匹配 row IDs。自动导入与派生交集保持 `pending/unreviewed`。独立 validator 复算计数、row IDs、canonical payload hash、阈值、protocol、双侧 refs，并可复算两份 raw artifact 字节 hash；它不独立重演 Open Targets 或 ChEMBL raw-to-records parser。双侧 engineering provenance 不证明 release 选择、来源官方性或生物学意义，`formal_network_ready` 仍为 false。整改工作区见 `docs/audits/2026-07-11-network-pharmacology-realignment/`。
- **方向演进（2026-08-15，ADR-0018）**：ADR-0017 仍为当前产品契约基线；新增 ADR-0018（Accepted，Gate 1 已确认 2026-08-15）把底层逻辑升级为“组学策略”，网络药理学为系统层核心应用，真实组学数据作为显式 opt-in 验证层，北极星案例为夏枯草甲状腺整合研究四步路径。本方向不改变当前病种/物种边界、默认 mock、离线纪律与 `formal_network_ready=false`；EMNLP 投稿路径已让位。
- **Compound child 输出边界（2026-07-15）**：每个 compound child 持久化并导出不可变 `source_task_id`，只展示冻结的 disease/compound lineage 与服务端派生交集。它明确跳过 provider、机制链、PPI、通路和 enrichment，结果固定为 `chains=[]`、`enrichment=null`；即便 parent 的 `data_mode` 为 `live`，也不得把该 snapshot-only 输出描述为真实网络链路。缺少 parent link 的 legacy child 在结果与报告读取时失败关闭且不改写 runtime。独立 validator 可检查 link 的格式、非自指、snapshot-only 输出字段及其 warning/readiness blocker，但不能在未提供 parent artifact 时证明 parent 存在或 owner 归属。
- 当前阶段：**MVP-A 证据工作台 100% 收尾完成（2026-06-04，见 `docs/plans/2026-06-04-mvp-a-closeout.md`）**；MVP-B 网络药理学 mock 起步链路已落地；C 阶段 provider / retrieval / grounding 底座部分提前完成。**2026-06-01 L2 推进工程闭环（Slices 1-5）+ §4c 真人走查完成，决策：L2 不翻转，保持 L1。** 4 份本地 reviewer PDF 样本已通过隔离状态的真实上传 + auto-parse API 探测；人工反馈中的 `/network` 链接缺口与 PDF 数字/表格乱码提示已处理。**A3（RAG 答案 Markdown 导出）2026-06-04 由前端 client-side 切到后端 `POST /api/rag/answer/export` + `app/services/rag.py:build_answer_markdown`，对齐 Slice 9 网络报告设计模式**（详见 commit `c7fe91f`）。**A5（中文 PDF 人工验收）2026-06-04 完成 4 份真实样本端到端走查并写专项 handoff**（详见 `docs/handoffs/2026-06-04-a5-chinese-pdf-verification.md`，3/4 干净中文抽取 + 1/4 quality_warning fallback 路径走通）。**内部预览基线 2026-06-04 已收口**：light workbench shell / clinical palette 已落地，`/literature` 四来源切换 + 合规 banner + `has_pdf_upload` 过滤已由 Playwright 覆盖，Windows e2e 后端 teardown 使用进程树清理避免 uvicorn worker 残留。正式医生/科研 reviewer sign-off 仍需单独真人走查记录，不能由自动化结果替代。
- 数据：本地 JSON seed + `backend/data/runtime/` 运行态副本；runtime state 是本地开发/演示状态，不是生产数据库，也不应回写 seed fixture。**2026-06-02 已落地 SQLite runtime backend**：repositories 走 protocol 抽象（`backend/app/repositories/protocols.py`），运行态可通过 `QIYAN_STATE_BACKEND="sqlite"` 切换到 `qiyan_state.sqlite3`（同样 gitignored 在 `backend/data/runtime/` 下），默认仍为 `json`。两个 backend 均通过 `pytest -q` 全量测试。**2026-06-04 eval corpus isolation 已落地**：RAG eval 与 cross-lingual eval 默认固定读取 immutable seed corpus；本地上传 PDF/runtime chunk 只在显式 `corpus=runtime` / `--corpus runtime` 时进入评估，报告 summary 和前端 `/evals/rag-ad` 均显示 corpus 标签。
- 文献：本地样本文献、PubMed 实时同步入口、上传 PDF 解析片段、chunk 与 50 题 AD RAG eval 数据集。`LiteratureItem.record_origin` 区分 `seed_sample` 演示样本与 `pubmed_live` 实时同步记录，演示 seed 不可当作外部数据库真实文献引用。
- RAG：默认 `deterministic` provider + `keyword` retrieval，返回 answer、citation cards、retrieval metadata、provider name、token usage、grounding metadata 字段与免责声明。**2026-06-19 已完成 reviewer 反馈收口**：RAG 可处理只有复方/药材实体名的领域内查询（如「消风散」「黄芪」）并只从 `related_entity_ids` 关联文献中选 citation；单字「肠」不再作为 gut-axis alias，`肠梗阻怎么治疗` / `高血压一线降压药` 等离题查询返回 0 citations；RAG 导出同时支持 Markdown 与后端生成的 Word `.docx`，DOCX 会保留多行换行并剥离 XML 非法控制字符。
- 真实检索 Track A（2026-07-11）：非循环 blind-labeling harness 已从 provider 原始排序改为产品实际 `answer_question()` citation selection；reviewer worksheet 的候选确定性打乱且不含 rank/score，真实排名只写 private manifest。real-only build 会拒绝 synthetic seed 或 live 数不足，scorer 严格要求 JSON boolean 并只报告 top-k 人工标签可支持的 `precision@k` / `MRR@k`，不报告 recall。当前首版 packet 使用 344/344 `pubmed_live`、0 seed 的独立快照，30 题均返回 top-5，共 150 个标签仍为 null，因此 `precision@5` / `MRR@5` 仍为 null；问题集由工程侧起草，状态为待真人 domain reviewer 接受，不能冒充专家原创。详见 `docs/guides/retrieval-validation-track-a.md` 与 `docs/handoffs/2026-07-11-track-a-real-retrieval-validation.md`。**2026-08-17 种子扩展已完成并提交（总表 83 条查询、runtime 语料 344→693 `pubmed_live`），工程侧 v2 盲评迭代至 p@5=0.400 / MRR@5=0.744，标签 provenance 仍为 engineering draft、仍待真人 reviewer 接受，详见补记 `docs/reports/2026-08-17-pubmed-seed-expansion-batch2-5-changelog.md`。**
- LLM provider：`deterministic` 默认；`mock_claude` 用于离线 wiring 测试；`opencode_go` 是当前优先 live-provider smoke 路径，仅在显式配置 `QIYAN_OPENCODE_GO_API_KEY` 后调用外部服务。**2026-06-08 opt-in live 默认配置已从 `opencode.ai/zen/go/v1` + `deepseek-v4-flash` 切到 `https://ai.router.team/v1` + `gpt-5.5` + `QIYAN_OPENCODE_GO_MAX_TOKENS=4096`**；provider class、env 前缀、grounding policy 与默认离线 deterministic 路径均不变。旧的 `deepseek-v4-flash` 结果仍作为历史 smoke / SLI 证据保留，不能直接外推到 gpt-5.5 治理决策；gpt-5.5 的价格、延迟、NLI pass rate 与 L2 通过率需重新建 baseline。**2026-06-09 baseline attempt 已尝试但未形成有效 live baseline**（`docs/evaluations/2026-06-09-gpt-5.5-baseline-attempt.md`）：10/10 题进入 `opencode_go` 后均因 router.team HTTP 401 回退 deterministic，`provider_name` 计数为 `deterministic: 10`、grounding 全部 `skipped`、成本仍为 `null`；下一次重跑前必须换成已授权 `gpt-5.5` 的 `QIYAN_OPENCODE_GO_API_KEY`，并先用单题 smoke 确认返回 `provider_name="opencode_go"`。**2026-05-31 已完成真实 live smoke**（`docs/evaluations/2026-05-31-opencode-go-bge-smoke.md`）：实测 `deepseek-v4-flash`（thinking mode）拒绝强制 `tool_choice`（HTTP 400），真实路径走 structured claims v3 而非 provider-native tool use；默认 `max_tokens=1200` 会被 reasoning 吃光导致空 content 回退 deterministic，需 ≥4000 才能让真实路径生效。优先尝试 OpenAI-compatible `record_grounded_claims` function tool grounding；若网关或模型拒绝 tools，则重试 structured claims JSON 并继续经过 structured claim grounding v3 校验。**2026-06-01 已落地 claim 质控 prompt v2**：发给真实 provider 的 prompt 明确要求每条 claim 只能引用 1 个证据 ID，且只能由对应 `证据文本` 直接蕴含；禁止跨引用综合，禁止添加引用片段未明示的治疗疗效、靶点、生活质量、因果或指南地位；OpenCode Go function schema 同步收紧为最多 3 条 claim、每条 claim 最多 1 个 evidence ref。`anthropic` 路径保留为后置可选 smoke，仅在未来有 `ANTHROPIC_API_KEY` 时使用。上述结构/工具/证据 ID grounding 之后，外部 provider 还会经过语义级 grounding gate：每条 claim 与其引用 chunk 文本计算 cosine，低于阈值（`QIYAN_GROUNDING_SEMANTIC_THRESHOLD`，hashing backend 默认 `0.40`，bge backend 推荐 `0.78`）则 `blocked_reason="semantic_low_support"`。**默认 `hashing` backend 下该分数是词汇重叠代理（lexical proxy），不是真正语义判定；`QIYAN_EMBEDDING_BACKEND="bge"` 原地升级为真实语义（已验证，推荐阈值 0.78）。** 标注语料 `backend/data/evals/grounding_semantic_pairs.json` + `run_grounding_semantic_separation` 度量分离度。BGE 评估结果（2026-05-31）：阈值 0.78 下实现完美分离（0 false rejects, 0 false accepts, 100% paired separation, clean score gap +0.029）。详见 `docs/evaluations/2026-05-31-bge-semantic-evaluation.md`。该 gate 仅作用于 `anthropic` / `opencode_go`，不改变真实 provider 默认关闭的事实。**真实 provider 已具备可治理启用路径（L1 受控 smoke/演示可启用，L2 默认预览仍不翻转）：启用决策与不变量见 ADR-0012，外发数据流向与 PIPL 见 ADR-0011，开/关步骤见 `docs/guides/real-llm-enablement-runbook.md`；默认路径仍为离线 deterministic。**
- LLM claim-quality v2 live validation：**2026-06-02 已用真实 key 重新采样 10 个问题**（`docs/evaluations/2026-06-02-claim-quality-v2-live-validation.md`）。配置为 `opencode_go + keyword + bge + semantic_threshold=0.3 + transformers NLI=0.5`；14/14 条 claim 均为单 evidence ref，0 条无 ref，0 条多 ref，0 条 unsupported ref/schema parse failure；4/10 个回答 passed，6/10 个回答 blocked，拦截原因均为 `nli_low_entailment`。快速 claim-level review 显示 4 个 passed 回答的 claim 与其 cited chunk 直接对齐。**2026-06-02 已生成并填写 delta-only reviewer packet 的 Codex technical verdict，且用户已确认正式 verdict**（`docs/evaluations/2026-06-02-l2-passed-claims-reviewer-packet.md`）：6/6 passed claims 为 supported，0 unsupported，0 unclear；该 packet 只覆盖这 4 个 passed answers 的 claim-vs-chunk 核对，不重复 2026-06-01 已完成的 §4c gate/fallback/rollback/UI 走查。结论：v2 明显改善结构化 claim 质量，L1 受控 smoke/demo 路径更可用；**L2/default preview 仍不翻转**，默认仍为 deterministic。
- RAG SLI：`/api/rag/answer` 顶层返回 `sli`（`provider_latency_ms`、`estimated_cost_usd`），deterministic / fallback 路径 latency 为 int、cost 为 `null`；成本由 token 用量 × `QIYAN_OPENCODE_GO_PRICE_INPUT_PER_MTOK` / `QIYAN_OPENCODE_GO_PRICE_OUTPUT_PER_MTOK` 计算，单价默认 `0.0` 即不估算（不臆造价格）。后端额外打印不含 secret 的 `rag_sli` 结构化日志；`/rag` 页面与 Markdown 导出展示延迟与成本。
- Price SLI baseline：**2026-06-02 已用当时 `deepseek-v4-flash` 公开 token 价格补齐历史成本基线**（`docs/evaluations/2026-06-02-opencode-go-price-sli-baseline.md`）：按 `$0.14` / 1M input、`$0.28` / 1M output 计算，10 题 live capture（6,040 input / 14,984 output）估算总成本 `$0.005042`；provider latency min 5.252s / avg 13.148s / max 28.540s。原 capture 中 `estimated_cost_usd=null` 仍是正确原始事实，因为当时未配置价格 env。**2026-06-08 切到 router.team + gpt-5.5 后，价格与延迟基线尚未重建；2026-06-09 401 attempt 中历史 deepseek 单价 env 已刻意临时移除，避免生成错误的 gpt-5.5 成本；`QIYAN_OPENCODE_GO_PRICE_*` 继续默认 0.0，除非真实 router.team 合同价格已确认。**
- Retrieval provider：`keyword` 默认；`vector` / `hybrid` 可通过 `QIYAN_RETRIEVAL_PROVIDER` 显式 opt-in；默认不启用真实 embedding 模型。
- 跨语言检索：确定性 CN↔EN 术语桥（`backend/data/retrieval/cross_lingual_terms.json`）和 keyword ranker 是当前默认有效路径；`run_cross_lingual_retrieval_eval()` 支持 keyword/vector/hybrid 的 recall、MRR 与 language_diversity 对比。2026-06-04 已完成 eval corpus isolation 与 `rag-eval-011` 数据审计：默认 seed benchmark 不再受 runtime/uploaded PDF chunk 污染，`pmid-40100009`（skin microbiome / S. aureus）作为合法英文视角保留，`chunk-pmid-40100009-staph` 纳入 expected chunks，microbiome bridge 补入「微生态」「皮肤微生态」与 `skin microbiome`；seed keyword bilingual cohort 当前 N=16、mono=1.0000、cross=1.0000。BGE-M3 多语 embedding spike 已完成且结论为不翻默认：`MultilingualBgeM3EmbeddingBackend` 仅作为 `QIYAN_EMBEDDING_BACKEND=multilingual_bge_m3` 显式 opt-in 可选项保留，不发 ADR-0015，不改 retrieval/embedding/RAG default。详见 `docs/evaluations/2026-06-04-eval-corpus-isolation-and-rag-eval-011-audit.md` 与 `docs/evaluations/2026-06-04-multilingual-bge-m3-eval.md`。
- PDF：本地上传存储；文本型 PDF 通过 `pypdf` 提供预览；扫描件/OCR 暂不支持，失败时回退到文件级占位说明。**2026-06-05 PDF 抽取质量 spike 已补齐**：pypdf 启发式增强保留（页眉页脚过滤、NUL warning 阈值调整），`pdfplumber` 对照在 A5 四份中文 PDF 上未能降低 problem sample 的 warning（嵌入字体 NUL 仍存在），因此不引入默认依赖、不替换 pypdf；同日 AFK hardening 已补 preview-window 选择：`pypdf-text-preview` 会优先选择摘要/正文信号窗口，避开明显页眉页脚、参考文献开头和低文本密度行，OCR 或商业/license-reviewed 抽取器仍需独立 spike。
- 网络药理学：`/api/network/analyze`、`/api/network/result/{task_id}`、`/api/network/result/{task_id}/report`、`/api/network/entities` 与 `/network` 页面已可跑通 mock 分析任务、seed entity、citation/entity 双向跳转，并支持 Markdown 报告导出（**2026-06-02 Slice 9** 前端导出按钮从本地 `buildNetworkReportMarkdown()` 切到后端 `/api/network/result/{task_id}/report`，后端 `build_network_report_markdown` 为 single source of truth；前端重复生成器删除，保留 `buildNetworkReportFileName` 纯文件名工具；详见 `docs/handoffs/2026-06-02-network-report-frontend-backend-wire.md`）。**新增 GO/KEGG 富集分析**：从 chains 提取 target symbols，使用本地 JSON 字典（`backend/data/network/sample_go_terms.json`、`sample_kegg_pathways.json`）模拟 GO/KEGG 数据库，通过 scipy 超几何分布计算 p-value（Bonferroni 校正），返回 top 20 显著富集的通路/功能（p < 0.05，至少 2 个重叠基因）。前端在结果页面展示富集分析表格（Term ID、通路/功能、类别、重叠基因、P-value、基因列表），限制显示前 10 条。当前为 mock 实现，不代表科研级 KEGG REST API 或真实 FDR 校正。**2026-06-08 已新增真实网络药理学 opt-in 工程链路**（commit `8bd38a6`）：`QIYAN_NETWORK_DATA_PROVIDER="live"` 时任务与结果返回 `data_mode="live"`、外部 provenance、pipeline steps、warnings/error、target evidence type、evidence refs 与可选 PPI edges；live 链路按 `TCMSP/cache → PubChem CID → ChEMBL known activity → UniProt → STRING PPI → KEGG pathway/enrichment → report provenance` 执行，外部响应只写入 runtime network cache，不回写 seed，不改变默认 mock。**新增结果图可视化（2026-06-01）**：`/network` 结果区在链卡片之上叠加确定性 node-link 图，按 `中药/复方 → 化合物 → 靶点 → 通路 → 疾病` 五层固定布局渲染内联 SVG（纯前端，零 d3/canvas/图表库依赖）。布局由纯函数 `frontend/lib/network-graph.ts` 的 `buildNetworkGraphModel` 计算（同层去重、相邻层连边、坐标确定性可复现，10 条真值单测兜底）；展示组件 `frontend/components/NetworkGraph.tsx` 将边 `score` 映射为线宽/透明度，带 `role="img"`、`aria-label`、每节点 `<title>` tooltip、图例与空态（「暂无网络数据」）。详见 `docs/handoffs/2026-06-01-network-graph-viz.md`。
- 网络图渲染最新状态：**2026-06-08 已完成 publication-style / Cytoscape-style 图谱美化**（commits `9b4dcdb`, `0e9e410`），在不引入 d3/canvas/图表库的前提下补 barycenter crossing reduction、分层布局稳定化、compound/target/pathway 分层视觉编码、导出友好的 SVG 样式与对应前端测试；默认 mock 与 live opt-in 边界不变。
- 网络药理学证据分级（ADR-0015，2026-07-04）：每条 `NetworkChain` 带确定性 `evidence_level`（`mock_inferred` / `predicted` / `literature_supported` / `experimental`），由 `data_mode` + `target_evidence_type` + `evidence_refs` 纯函数推导（`backend/app/services/network.py` 的 `derive_chain_evidence_level` / `grade_chains_evidence`，在 `_advance_record` 装配处统一打分）。**强制护栏**：`data_mode="mock"` 的链恒为 `mock_inferred`，任何字段都不能升级，mock 不得冒充有证据支撑的结论。后端报告新增「## 证据分级」段（含指南三原则映射与 mock 边界提示），`/network` 前端每条链卡片渲染「证据分级 · <label>」pill；前端 `NetworkChain` 类型与 `getNetworkEvidenceLevelLabel` 同步。这是把外部路演宣称的「内嵌《网络药理学评价方法指南》」落成确定性、可测的透明标注层，不引入真实 LLM/数据库，不产生概率或疗效估计；不是指南全量条目核验。默认路径下等级恒为 `mock_inferred`。
- 前端：Next.js App Router + React + Ant Design，页面包括 `/`、`/literature`、`/literature/[id]`、`/rag`、`/evals/rag-ad`、`/compliance`、`/network`。2026-06-04 已统一 light workbench shell 与 clinical palette；**2026-06-08 已完成 persistent workbench shell、深色毛玻璃与流星背景 UI 收尾，用户确认“目前前端做成这样就很好了”，当前有效交接为 `docs/handoffs/2026-06-08-post-frontend-ui-handoff.md`，早前 `2026-06-08-frosted-glass-meteor-handoff.md` 仅作 superseded 历史参考。** `/literature` 支持“全部来源 / PubMed 记录 / CNKI sample / 上传 PDF”四来源视图，合规 banner 随选择切换，上传 PDF 视图走后端 `has_pdf_upload=true` 查询参数；每条文献会显示 `记录来源`，区分演示 seed 与 PubMed 实时同步记录，演示 seed 不可当作外部数据库真实文献引用。**2026-07-10 云端访问边界加固**：所有前端 backend fetch 仍统一经过 `frontend/lib/api/client.ts`，但客户端不再读取或注入任何后端 access token；multipart PDF 上传不手写 `Content-Type`。云端 reviewer 由 nginx 全站 Basic Auth 按人鉴别，nginx 从 root-only 配置向 `/api/` 注入共享后端 `X-Access-Token` 并在 access log 记录 `$remote_user`；任何访问凭证均不得进入浏览器公开环境变量。**2026-06-02 Slice 10** NetworkGraph 节点支持键盘交互：Tab 进入 / 离开节点（onFocus/onBlur 镜像 hover 高亮）、Enter 或 Space 切换 focus、Escape 清除 focus；每节点 `role="button"` + `aria-pressed` + `aria-label`，屏幕阅读器可朗读层级与名称。详见 `docs/handoffs/2026-06-02-network-graph-keyboard-a11y.md`。**2026-06-02 Slice 11** 在 Slice 10 之上补箭头键导航：ArrowUp/Down 在同层前后节点间移动，ArrowLeft/Right 跨层跳到 Y 距离最小的节点（不是简单第一个），通过 `useRef<Map<string, SVGGElement>>` 收集 DOM ref 后程序性 `.focus()`；onFocus handler 复用既有 hover 高亮态，让键盘用户也看得到连边强调。详见 `docs/handoffs/2026-06-02-network-graph-arrow-key-nav.md`。**2026-06-03 Slice 12** 补 e2e 回归：`frontend/e2e/network-graph-keyboard.spec.ts` 用真实 chromium 驱动键盘事件覆盖 focus → Enter/Space toggle → Escape clear → ArrowRight 跨层 → ArrowDown 同层 → ArrowLeft 反向跨层全链路，关闭 Slice 11 handoff 留下的 "e2e 键盘交互测仍未加" TODO。同时修一处 Windows + Node 20+ 的 e2e runner spawn EINVAL（`frontend/e2e/start-frontend.mjs` 兜底 `pnpm.cmd` 分支补 `shell:true`，Node ≥20 拒绝 shell:false spawn .cmd / .bat，CVE-2024-27980）；2026-06-04 进一步补 `frontend/e2e/literature-data-source.spec.ts` 锁定 B6 数据来源切换与后端查询参数，并修 `frontend/e2e/start-backend.mjs` Windows 进程树 teardown；`pnpm e2e` 实测 4 spec 全绿。详见 `docs/handoffs/2026-06-04-internal-preview-baseline.md`。
- 2026-07-11 对抗性加固收口：Next.js 升至 `16.2.6`，PostCSS override 固定为 `8.5.10`，当次 `pnpm audit --prod` 为 0 vulnerabilities；2026-07-15 复跑时 quick 与 fallback endpoint 均返回 HTTP 410，未形成新的漏洞结论。浏览器公开 token 路径已删除。RAG answer response 使用服务端 HMAC `integrity_token`，Markdown/DOCX 导出只接受字段完整且签名匹配的 canonical payload。unknown network query 返回空 chains，不再伪造机制链。SQLite network-task repository 对同一 canonical DB path 共享进程内 `RLock`；literature/chunk repository 仍是实例级锁。三者的失败数据库操作均执行 rollback；这些保证都不跨进程或多 worker。
- Reviewer ownership 已落地到 network task：nginx Basic Auth 的 `$remote_user` 由可信代理覆盖写入 `X-Qiyan-Reviewer`，FastAPI 仅在 access token 验证后建立 request-state identity；open mode 固定为 `local-preview` 并忽略来路身份头。JSON/SQLite/PostgreSQL 均按 `task_id + owner_id` 查询或原子推进，foreign/legacy-ownerless task fail closed 为 404。`GET /api/network/result/{task_id}/report` 已与 polling 推进分离：queued/running 返回 202 且不写盘，completed 返回只读 200，failed 返回带真实 error 的 409。
- 内部预览脚本不再拼接 `PowerShell -Command`，统一调用 `scripts/start-configured-process.ps1`；端口限定为 1–65535，smoke 的 token/reviewer 参数拒绝 curl config/header 注入。云端 runbook 要求 80/443 access log、两个 reviewer 账号的对象隔离 smoke、凭证轮换与 teardown；后端 8000 只监听 loopback，reviewer 不得获知共享内部 token。PDF 上传、解析结果、uploaded chunk 和 RAG retrieval 尚未完成对象级隔离，多人试用仍只能上传所有参与者均有权查看的材料。
- Reviewer walkthrough：**2026-06-05 内部代走彩排已完成**（见 `docs/handoffs/2026-06-05-internal-reviewer-rehearsal.md`）。默认离线 profile 下文献四来源、PDF 上传→自动解析、RAG uploaded PDF citation、RAG/Network Markdown 导出、网络图键盘烟测与富集分析表格均通过。**正式 reviewer 技术 preflight 已记录**（见 `docs/handoffs/2026-06-05-formal-reviewer-signoff.md` 与 `docs/evaluations/2026-06-05-reviewer-feedback.md`）：运行 profile 固定为 deterministic + keyword + open access + isolated runtime，不启用真实 LLM、不启用 PostgreSQL、不外发数据；同日已补 backend token profile automated smoke（`QIYAN_ACCESS_TOKENS` + `X-Access-Token` 下文献/RAG/export/network/report 可用）。`scripts/run-internal-preview.ps1` 的 token profile 现在只用于脚本直连后端 API；浏览器 E2E 固定 open mode，不再向前端公开后端 token。云端浏览器走查必须经过 `docs/guides/cloud-trial-deployment-runbook.md` 的 Basic Auth 反向代理。`scripts/collect-internal-preview-evidence.ps1` 仍可一键生成本地 `.tmp/internal-preview-evidence/<timestamp>/` 证据包（open/backend-token smoke JSON、Markdown、metadata、日志副本与 request id 汇总）。正式医生 + 科研 reviewer sign-off 仍需真人 reviewer 填写，不能由内部代走、证据包或自动化结果替代。
- 默认运行不接入真实 LLM、真实 embedding 模型、pgvector、Neo4j、Celery、Redis、MinIO、NextAuth 或外部生产服务；外部服务只作为本地显式 smoke，不进入默认用户路径。

## 当前目录分层

- `backend/` — FastAPI 后端应用。
- `frontend/` — Next.js 前端应用。
- `infra/` — 本地基础设施说明与显式 opt-in spike 配置；当前包含 PostgreSQL + pgvector compose，不进入默认开发路径。
- `docs/adr/` — 架构决策与长期边界。
- `docs/plans/` — 可执行切片计划。
- `docs/handoffs/` — 跨会话续接记录，越新的越接近当前事实。
- `docs/archive/pre-dev-planning/` — 早期规划、Word 文档、HTML 原型和 Trae/Cursor 产物，仅作历史参考。

## 标准验证命令

统一本地门禁（推荐，Windows PowerShell）：

```powershell
.\scripts\verify-local.ps1
```

默认顺序执行 backend 4 项与 frontend `test/typecheck/build`。`pnpm typecheck` 与 `pnpm build` 都会写 `.next` route type 产物，必须顺序跑，不要并行跑。Reviewer 走查或分支收口前可追加：

```powershell
.\scripts\verify-local.ps1 -IncludeE2E
```

浏览器 E2E 固定使用 open mode，不接收后端 token；后端 token middleware 由后端测试与下方 direct API smoke 覆盖。云端身份边界按 Basic Auth runbook 独立验证。

内部预览 isolated runtime 启动与 API smoke：

```powershell
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-open
.\scripts\smoke-internal-preview.ps1
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-open -Stop

.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-token -AccessToken "trial-token"
.\scripts\smoke-internal-preview.ps1 -AccessToken "trial-token"
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-token -Stop
```

Backend:

```powershell
cd backend
& .\.uv-test-venv\Scripts\python.exe -m ruff format --check app tests
& .\.uv-test-venv\Scripts\python.exe -m ruff check app tests
& .\.uv-test-venv\Scripts\python.exe -m mypy app
& .\.uv-test-venv\Scripts\python.exe -m pytest -q
```

Frontend:

```bash
cd frontend
pnpm test
pnpm typecheck
pnpm build
pnpm e2e
```

## 当前下一步候选

**当前唯一工程主线（2026-08-02）**：Gate 2 双侧 raw-artifact provenance、owner-scoped 逐行人工 adjudication 与 source-bound 网络装配门禁（候选装配计划）均已完成。判定通过 `POST /api/network/result/{task_id}/adjudications` append-only 记录，`GET /api/network/tasks` 提供 owner-scoped 任务列表；projection 挂在结果响应信封而非冻结快照上，同一 row latest wins，`reviewer_id` 持久化但从不回投，未知/外人/legacy ownerless task 一律 `404`。**装配门禁（2026-08-02，契约见 `docs/plans/2026-08-02-source-bound-network-assembly-gate.md`，交接见 `docs/handoffs/2026-08-02-source-bound-network-assembly-gate.md`）**：`POST /api/network/result/{task_id}/assembly-plans` 在 child 任务三类 lineage 全部 latest-wins 终态判定、双侧来源 `server_verified_raw_artifact`、父子协议字节等价、snapshot-only 边界与至少一条带双侧 included backing 的交集后，原子封存不可变候选计划（`201`，同输入幂等 `200`）；任何判定事件追加都会产生新计划，旧计划 append-only 可审计但默认不可执行。`GET .../assembly-plans/{plan_id}` 提供 owner-scoped 历史计划。独立 validator `backend/scripts/validate_network_assembly_plan.py` 用与 producer 零共享代码的路径重算全部绑定并拒绝每一种篡改；result 信封、报告与 `/network` 前端只展示 `assembly_input_ready` 与结构化 blockers，`formal_network_ready` 仍恒为 false，冻结 lineage row 的 `adjudication_status`/`decision` 仍恒为 `pending`/`unreviewed`。**判定能力与装配门禁均已上线，但尚无任何真实领域 reviewer 判定过任何一行；能力不等于事实，事实也不等于科学有效。** `-IncludeE2E` 红线已恢复绿色：根因是项目目录迁移后遗留的 `.next` 绝对路径缓存，而非行为回归；清理缓存后冷/热两轮均为 Playwright `4 passed`，并已移除 4 个 spec 对脆弱 `networkidle` 状态的依赖，统一门禁再次通过（backend `863 passed, 1 skipped`，frontend `281 passed` + typecheck/build，E2E `4 passed`）。**未完成边界**：writer 的装配计算逻辑已于 2026-09-11 落地（切片计划 `docs/plans/2026-09-11-writer-assembly-computation.md` 七条拍板规则，交接见 `docs/handoffs/2026-09-11-writer-assembly-computation.md`）：consume 时服务端从 plan `selected_intersections` 确定性派生 `NetworkChain`（成分×靶点组合一条链、同 symbol 多来源行不合并；pChEMBL/10 归一口径；本地 KEGG 字典填 pathway、未命中留空并进 warnings；herb/formula 诚实留空——冻结协议/plan 无该信息；富集不跑；分级按行 provenance 判定——verified 行恒 `predicted` 不上浮 experimental、mock 行防御分支恒 `mock_inferred`），输出信封新增 `chains`/`warnings` 字段且刻意不进 `output_sha256` hash 域（D5 重放语义不变）；selected 行解析失败 fail closed（500 integrity `assembly_input_unresolvable`）。writer 的写前强制门禁已落地（2026-09-11 已拍板装配规则并出切片计划 `docs/plans/2026-09-11-writer-assembly-computation.md`）：**writer 消费原语（2026-09-06，契约 D1-D9 已于 2026-08-16 拍板）** `POST /api/network/result/{task_id}/assembly-plans/{plan_id}/consume` 在同一临界区内原子完成 R1-R9 重验 + 不可变输出信封 + exactly-once 消费记录（`UNIQUE(task_id, owner_id, plan_id)`；同 writer 同输出幂等重放返回 `existing`），失败码按 D3 固定优先级（404/422/`plan_already_consumed`/`plan_superseded`/`adjudication_changed`/`broken_parent_link`/500 integrity/429 容量）；JSON 后端如实标注 `backend_fidelity="preview"`（仅同进程同实例，文件进程 token 检出异进程写入即 fail closed），SQLite/PG 为 `production`；消费记录容量 env `QIYAN_CONSUMPTION_RECORD_LIMIT` 默认 1000。只读投影 `is_latest_plan`/`is_consumed`/`is_superseded_by` 出现在 plan 审计视图、result 信封 `latest_plan.is_consumed` 与报告消费状态行；消费是审计不是推进，`formal_network_ready` 恒 false。实现切片记录见 `docs/plans/2026-09-06-writer-consumption-primitive.md` 与 `docs/handoffs/2026-09-06-writer-consumption-primitive.md`。其余未完成边界：PostgreSQL repository 已实现消费原语但未做活库 parity 验证；writer 输出的独立零共享 validator 按 D9=B 留待后续切片；privileged reviewer-identity audit HMAC 不在本切片；在完成前不得把 artifact consistency、人工判定、候选计划或消费记录写成 scientific readiness。Gate 3 组学验证层实现计划已立项（`docs/plans/2026-09-03-gate3-omics-implementation-plan.md`，D-G3-A/D-G3-B 按推荐项 a/a 拍板）；**G3-1/G3-2/G3-3 三个切片已于 2026-09-03 落地**：omics manifest 冻结导入（`POST /api/network/omics-import/verify` + 独立 validator `backend/scripts/validate_omics_import.py`）、确定性 DEG 候选投影（`GET /api/network/result/{task_id}?omics_verification=true&omics_accession=...`；真实 GSE32924 验收 1,178 DEG，IL6/STAT3/TNF 未过阈值，见 `docs/reports/2026-09-03-gate3-g32-real-data-verification.md`）、`omics_validated` 证据等级 + `omics_confirmed` HITL 判定（判定时刻重验机器条件；mock 恒 `mock_inferred`；不翻转 `formal_network_ready`）。组学端点全部显式 opt-in。

**并行 HITL（不占工程主线）**：由一名未参与 ranker 调参的真实临床或科研 reviewer 接受 held-out Track A 问题集并完成 150 个 blinded 二元相关性标签，产出诚实的 `precision@5` / `MRR@5`；在真人数字出现前不声称检索有效。

**竞品笔记**：`docs/competitive-analysis-qingtuanyun.md`（仅公开官网信息，非决策记录，不改 ADR-0017/0018 边界）。

**omics 遗留决策（2026-09-04，对抗性审查后拍板，见 `docs/reports/2026-09-04-omics-followup-decisions.md`）**：不为 IL6/STAT3/TNF 冻结 AL vs ANL 第二对比 snapshot（outcome-shopping 风险 + 配对样本与非配对 Welch 统计设计不匹配 + 契约变更成本；探针显示当前管线下该对比 adj_p<0.05=0）；`/network` 暂不做 omics UI 入口（保持 API-only，保护 opt-in 纪律；触发条件见决策记录）。

以下 2026-05/06 材料是 live-LLM 治理与评估的历史证据，不代表当前工程优先级：`docs/evaluations/2026-06-02-claim-quality-v2-live-validation.md`、`docs/evaluations/2026-06-02-l2-passed-claims-reviewer-packet.md`、`docs/evaluations/2026-06-02-opencode-go-price-sli-baseline.md`、`docs/evaluations/2026-06-01-nli-real-distribution.md`、`docs/evaluations/2026-05-31-opencode-go-bge-smoke.md`、ADR-0012 与 real-LLM runbook。

**AI Technical Pre-review 完成（2026-06-06）**：AI 技术视角的产品安全审查（临床与科研双视角）未发现 P0/P1 问题，结论为可进入小范围试用准备；详见 `docs/handoffs/2026-06-06-comprehensive-product-review.md`。该结论不替代真实临床医生/科研专家的领域判断；`docs/evaluations/2026-06-05-reviewer-feedback.md` 已恢复为正式真人 reviewer packet，clinician / research reviewer sign-off 仍待填写。AI 预审发现的 P2「网络药理学 mock 边界标注可增强」已在 2026-06-06 补强：`/network` 页面新增演示数据边界 note，network Markdown 报告头部新增数据说明。小范围试用反馈模板见 `docs/evaluations/2026-06-06-small-scale-trial-feedback.md`。

**2026-06-09 状态刷新**：`opencode_go` opt-in live provider 默认 smoke 配置已切到 router.team + gpt-5.5；首次 10 题 baseline attempt 因 HTTP 401 全量回退 deterministic，尚未形成价格/延迟/NLI 通过率基线（见 `docs/evaluations/2026-06-09-gpt-5.5-baseline-attempt.md` 与 `docs/handoffs/2026-06-09-post-mvp-a-engineering-closeout.md`）。网络药理学 live data pipeline 已作为显式 opt-in 落地但默认仍 mock；TCMBench 作者联系邮件已发出并等待回复（见 `docs/handoffs/2026-06-08-tcmbench-contact.md`），回复前不集成非公开数据、不训练、不再分发；正式 clinician/research reviewer sign-off 仍未完成，是进入小范围试用前的人工决策点。

**重要说明**：AI 审查侧重产品安全、术语规范、科学准确性和数据透明度，不替代真实临床医生/科研专家的领域判断。以下领域仍需在小范围试用中由真实用户验证：(1) 临床语境准确性，(2) 科研工作流适配性，(3) 用户认知边界，(4) 术语细节。

**历史候选记录（非当前优先级）**：下列条目保留 2026-05/06 的完成事实与治理债；新增工程必须由 ADR-0017 的网络药理学研究门禁主线牵引，不能因现有 RAG/LLM 基础较成熟而继续倒置优先级。

1. **✅ 语义 grounding BGE 评估（已完成）**：BGE (BAAI/bge-small-zh-v1.5) 评估已完成。详见 `docs/evaluations/2026-05-31-bge-semantic-evaluation.md`。
2. **✅ 真实 LLM live smoke + 启用底座（已完成）**：OpenCode Go live smoke 已跑通。真实 provider 现可在 **L1 受控 smoke/演示** 启用；默认仍 deterministic。
3. **L2 默认预览推进（工程部分✅，走查完成，决策不翻转）**：
   - ✅ **threshold recalibration**（§4a）：BGE-cosine 不可达 → 落地 NLI entailment gate（opt-in，默认关）。
   - ✅ **NLI gate 实现**：`mDeBERTa-v3-base-mnli-xnli`，二级 gate（cosine 预筛后）。
   - ✅ **Slice 1-5 工程闭环**：采集 → 标注（20 对）→ 真实分布评估（0 FP, 0 FN, gap +0.95）→ 批处理（batch entailment, ~1.1x）→ §4c 走查准备。
   - ✅ **§4c 真人走查**（2026-06-01）：7 步核验全部通过，NLI gate 在生产管线正确运行，R4/R5 回退验证通过。
   - ❌ **L2 不翻轉**：走查全程无回答穿透 BGE=0.78 + NLI=0.5（4 条全 blocked）。根因是 keyword retriever 中英跨语匹配弱 + openCode Go 自由改写触发多 claim NLI 拦截。保持 L1 受控启用；存 key 者设 3 个 env var 即可启用真实 provider。详见 ADR-0012 2026-06-01 更新（三）。
   - ✅ **claim-quality v2 live validation**（2026-06-02）：BGE 预筛降至 0.3 后，NLI gate 放行 4/10 个回答；所有 14 条 claim 均单证据引用，未见 raw draft 泄漏。delta-only reviewer packet 已由 Codex technical review 填写 6/6 supported，并已由用户确认；决策仍不翻转 L2。
4. 已完成 4 份本地中文 PDF 样本的最小验收探测、2026-06-05 抽取质量 spike 与 preview-window 选择；后续抽取工作只剩 OCR、表格重建等独立 spike，不能扩进默认内部预览路径。
5. **✅ 跨语言检索改进（已完成并对账）**：keyword + cross-lingual bridge 是默认有效路径；2026-06-04 seed corpus 隔离与 q011 数据审计后，bilingual cohort N=16 当前 mono=1.0000、cross=1.0000。BGE-M3 保留为 env opt-in，不进入默认路径。
6. 其它可选主线：network report export 后续增强（PDF/Word）；**runtime JSON → SQLite 已落地（2026-06-02，commit 4144357）**；**PostgreSQL/pgvector spike 已完成工程接入、Docker Compose 配置与 JSON/SQLite/PostgreSQL 实测 benchmark（2026-06-05）；实测不支持切换默认，默认仍为 JSON，SQLite 仍是当前可选本地持久化推荐，PostgreSQL 保持 explicit opt-in spike/backend**（见 `docs/evaluations/2026-06-05-postgresql-pgvector-spike.md`）；**网络图可视化、hover/focus 高亮、键盘与箭头导航、e2e 回归均已落地**；Anthropic 仅在有订阅/key 后再排期。
7. 历史治理候选（均不覆盖当前 owner-scoped 人工 adjudication 主线）：
   - ① **L2 governance**：BGE=0.3 + NLI=0.5 profile 的治理判断，以及生产预算前复核真实合同价格；这是决策议题，不是默认工程翻转。
   - ② **PostgreSQL/pgvector 后续**：spike 已闭环且结论为不翻默认；仅在出现多人并发、真实 pgvector ANN 检索或生产数据库治理需求时，再重开生产化 ADR。
   - ③ **PDF 后续专项**：抽取质量 spike 已完成且不翻默认；若继续，应聚焦 OCR、表格重建或 preview-window 选择的独立 spike，不扩进默认内部预览路径。
   - ④ **正式 reviewer sign-off**：内部代走彩排已完成，下一步是让医生 + 科研 reviewer 按 `docs/evaluations/2026-06-05-reviewer-feedback.md` 填写正式反馈并对 P0/P1 做闭环。
