# Qiyan Nexus

面向特应性皮炎（AD）医生与科研人员的窄领域网络药理学自动化科研辅助平台；文献检索、PDF 归档、证据问答与引用导出是证据服务层。

## 这是什么

Qiyan Nexus 把「定研究协议 → 构建方药-成分-靶点-通路网络 → 核验逐边证据 → 运行富集与一致性检查 → 导出研究报告」整合成一条可追溯工作流。文献检索、PDF 与 RAG 用于支撑靶点、通路、网络边和科研 claim 的证据核验。**仅供医生/科研人员使用，不面向 C 端患者，不替代诊断**；所有 AI 输出均附带免责声明 `非诊断结论、需结合临床。`

### 核心工作流

1. **定研究协议**（`/network`）：明确方药对象、AD 表型、人类物种、证据策略与查询日期。
2. **构建与审计网络**（`/network`）：组织「方药-成分-靶点-通路-疾病」链，显示来源、证据等级、富集结果与科研就绪阻塞项。
3. **核证据**（`/literature`、`/rag`）：检索/归档原始文献并生成可核对引用，作为网络边和研究结论的证据服务层。
4. **出研究报告**（`/network`）：导出研究协议、链路、来源边界、阻塞项、免责声明和独立的 artifact/scientific readiness 状态。

### 当前能力边界（请如实告知试用者）

- RAG 默认走**本地确定性检索**（deterministic + keyword），不接真实 LLM；答案是检索到的原文证据片段，**不是模型综合生成的结论**。
- 文献库为**小型构造演示样本集（约数十篇）**，不可当作外部可检索的真实文献引用；真实 PubMed 同步为显式 opt-in 入口。需要更大的真实语料时，运行 `backend/scripts/seed_pubmed_corpus.py` 一键拉取真实 PubMed 记录写入 runtime（gitignored，不污染 seed）。
- 默认 keyword 检索在真实语料上的质量尚未获得真人 baseline。2026-07-11 已生成 344 条 real-only PubMed、30 题 × top-5 的 rank/score-blind reviewer packet；150 个标签仍为空，因此 `precision@5` / `MRR@5` 仍是 `null`。复现与标注规则见 `docs/guides/retrieval-validation-track-a.md`。
- 网络药理学默认为 **mock 演示链路**，富集分析为本地字典模拟，**不代表科研级 TCMSP/STRING/KEGG 或真实 FDR 校正**。
- `/api/network/analyze` 现要求显式研究协议，并保留可选、未验证的客户端疾病靶点 snapshot；`POST /api/network/disease-import/verify` 与 `POST /api/network/compound-import/verify` 分别由离线 Open Targets / ChEMBL raw artifact 创建不可变的 `server_verified_raw_artifact` task。compound 核验从 owner-scoped 的疾病核验 task 派生新 task，不修改父 task。结果把 `disease_targets`、`compound_targets`、`intersection_targets` 与逐行 lineage 分开输出；即使两侧 artifact 已核验，人工 adjudication 与科学验证未完成时 `formal_network_ready=false`。
- compound child 持久化 `source_task_id`，当前是 snapshot-only 输出：只返回冻结 lineage 与派生交集，刻意不调用 provider，不生成机制链、PPI、通路或富集（`chains=[]`、`enrichment=null`）。这不是完整网络分析，也不能因 parent 的 `data_mode="live"` 被描述为真实网络链路。
- network task 已按 reviewer 隔离，但 PDF upload record、解析结果、uploaded chunk 与 RAG retrieval 仍是实例共享；云端多人试用只能上传所有参与者均有权查看的材料。
- 分子对接 / 分子动力学（MVP-C）**仅有 schema 预留，无实际功能**。
- 默认路径不外发数据、不接真实 embedding / 生产数据库；外部 provider 仅作本地显式 smoke。

> 详细 API 示例、env 配置、本地门禁与状态事实源见下文与 `docs/current-state.md`。

当前状态：2026-07-15 已按 ADR-0017 完成方向纠偏 Gate 1，并完成 Gate 2 的双侧 raw-artifact 工程 provenance：首页与导航以网络药理学为主轴；网络任务强制持久化研究协议；结果、前端与报告分开展示疾病靶点、成分靶点、派生候选交集及逐行 lineage；离线 Open Targets 和 `chembl_known_activity_v1` ChEMBL artifact 都由服务端计算字节 SHA-256、静态解析并封存为不可变 `server_verified_raw_artifact` task，独立脚本可复算 artifact hash、集合计数、阈值与双侧 refs。后者是离线 artifact profile，不是 live ChEMBL API 集成。该状态不证明 release 选对、artifact 来自官方渠道或靶点具有生物学意义；两侧逐边人工 adjudication 和科学验证尚未完成，`formal_network_ready=false`。MVP-A 既有文献/PDF/RAG 能力保留为证据服务层；网络真实富集和 scientific readiness 仍未完成。默认仍不接真实 LLM、真实 embedding 模型、pgvector、Neo4j、Celery、Redis、MinIO、NextAuth 或外部生产服务。2026-08-15 已起草 ADR-0018（Proposed）：在 ADR-0017 当前契约之上，将底层逻辑升级为组学策略，网络药理学为系统层核心，真实组学数据只作显式 opt-in 验证层；该方向不改变当前实现、默认路径与 `formal_network_ready=false`。

当前事实源索引见 `docs/current-state.md`。正式命名建议见 `docs/evaluations/2026-05-06-project-evaluation-and-optimization.md`。当前本地工作区为 `D:\螃蟹's Projects\Tcm_tech`。

## 目录

- `frontend/` — Next.js 前端应用
- `backend/` — FastAPI 后端应用
- `infra/` — 本地基础设施说明与后续 Docker Compose 入口
- `docs/` — 当前状态、ADR、计划、交接与历史归档
- `docs/archive/pre-dev-planning/` — 早期 AI 工具链规划、Word 文档与 HTML 原型，仅作历史参考

## 后端

统一本地门禁（Windows PowerShell，推荐先跑这个）：

```powershell
.\scripts\verify-local.ps1
```

默认顺序执行后端 `ruff format --check`、`ruff check`、`mypy app`、`pytest -q`，以及前端 `pnpm test`、`pnpm typecheck`、`pnpm build`。`pnpm typecheck` 与 `pnpm build` 会写 `.next` route type 产物，必须顺序跑，不要并行跑。

如需在 reviewer 走查或分支收口前追加 Playwright E2E：

```powershell
.\scripts\verify-local.ps1 -IncludeE2E
```

单独跑一侧：

```powershell
.\scripts\verify-local.ps1 -BackendOnly
.\scripts\verify-local.ps1 -FrontendOnly
```

首次安装（Windows PowerShell）：

```powershell
cd backend
py -3.11 -m venv .uv-test-venv
& .\.uv-test-venv\Scripts\python.exe -m pip install -U pip
& .\.uv-test-venv\Scripts\python.exe -m pip install -e ".[dev]"
```

运行测试：

```powershell
cd backend
& .\.uv-test-venv\Scripts\python.exe -m pytest -q
```

启动开发服务：

```powershell
cd backend
& .\.uv-test-venv\Scripts\fastapi.exe dev app/main.py --port 8010
```

健康检查：

```bash
curl http://127.0.0.1:8010/health
```

访问控制（可选，A2）：

- 默认 `QIYAN_ACCESS_TOKENS` 未设置时全部接口开放（dev 模式）。
- 设置后所有非 `/health` 与非 OPTIONS preflight 请求必须带 `X-Access-Token` 请求头匹配白名单，否则返回 401。
- 示例：`$env:QIYAN_ACCESS_TOKENS="dev-token-1,internal-reviewer-2"; & .\.uv-test-venv\Scripts\fastapi.exe dev app/main.py --port 8010`，调用方需 `curl -H "X-Access-Token: dev-token-1" http://127.0.0.1:8010/api/literature/search?q=AD`。
- `X-Access-Token` 只证明请求来自可信内部通道，不代表 reviewer 身份。network task 等 owner-bound endpoint 在 protected mode 还要求 `X-Qiyan-Reviewer`；云端由 nginx 用 Basic Auth 的 `$remote_user` 覆盖注入，本地 token smoke 使用固定 `preview-smoke`。不要让浏览器 body、query 参数或公开环境变量决定 owner。
- 前端不会读取或注入后端 token。任何 `NEXT_PUBLIC_*` 都会进入浏览器 bundle，不能承载访问凭证；本地浏览器开发使用 open mode，云端试用按 `docs/guides/cloud-trial-deployment-runbook.md` 由 nginx Basic Auth 鉴别 reviewer，并由 nginx 在反代层注入后端内部 token。
- `frontend/lib/api/client.ts` 只合并调用方业务 header；multipart PDF 上传仍不手写 `Content-Type`，避免破坏浏览器生成的 boundary。

内部预览一键启动 / smoke（默认离线 deterministic + keyword + isolated runtime）：

```powershell
# open dev profile
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-open
.\scripts\smoke-internal-preview.ps1
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-open -Stop

# backend API token profile（供脚本直连验证；直接前端页面不会携带 token）
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-token -AccessToken "trial-token"
.\scripts\smoke-internal-preview.ps1 -AccessToken "trial-token" -ReviewerId "preview-smoke"
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-token -Stop

# 生成本地内部预览证据包（open + shared-token smoke，输出到 .tmp\internal-preview-evidence\<timestamp>\）
.\scripts\collect-internal-preview-evidence.ps1
```

`run-internal-preview.ps1` 使用 `backend\.uv-test-venv\Scripts\python.exe -m uvicorn app.main:app` 启动后端，避免 Windows FastAPI CLI Rich banner 编码问题；runtime JSON、chunk、network task、vector cache 与 uploads 都写到指定 `.tmp\...` 目录。传入 `-AccessToken` 只保护后端并供脚本直连验证，直接打开 `:3000` 的浏览器页面不会获得该 token；token 按设计保留在后端进程环境中，但不会进入生成的 PowerShell command line、curl argv、前端进程或浏览器，multipart smoke 通过 stdin curl config 传递 header。这里仍只应使用一次性本地测试 token，不要复用云端/生产内部 token，也不要把真实 token 留在 shell history。浏览器走查请用 open dev mode，或使用云端 runbook 中的认证反向代理。`smoke-internal-preview.ps1` 会检查 health、文献四来源、PDF upload + auto-parse、RAG answer/export、network analyze/result/report，并输出 `X-Request-ID`；protected profile 默认使用 canonical reviewer `preview-smoke`。传入 `-OutputJson` / `-OutputMarkdown` 时会同时生成机器可读和 Markdown smoke 证据。`collect-internal-preview-evidence.ps1` 会自动跑 open 与 backend-token 两种 API profile，生成 `evidence-summary.md`、`metadata.json`、`open-smoke.*`、`token-smoke.*` 和日志副本；该证据包只是技术预览 artifact，不能替代正式医生/科研 reviewer sign-off。

文献检索 API 数据来源：

- seed 文献 JSON：`backend/data/literature/sample_ad_literature.json`
- seed chunk JSON：`backend/data/literature/sample_ad_chunks.json`
- runtime 文献状态：`backend/data/runtime/literature_state.json`（gitignored，可从 seed bootstrap）
- repository 层：`backend/app/repositories/literature.py`
- service 层：`backend/app/services/literature.py`
- 当前每个 `LiteratureItem` 返回 `record_origin`：`seed_sample` 表示演示 seed 样本，不可当作外部数据库真实文献引用；`pubmed_live` 表示来自 PubMed E-utilities 实时同步的 runtime 记录。
- 当前 PDF metadata 字段：`pdf_upload_id`、`pdf_file_name`、`pdf_parse_status`、`pdf_parse_message`、`pdf_parse_started_at`、`pdf_parse_finished_at`、`last_parse_trigger`、`parse_attempt_count`、`pdf_parse_result`
- 当前支持本地 PDF 上传存储：`POST /api/uploads/pdf`（multipart `file`），默认写入 `backend/uploads/`，可通过 `UPLOAD_STORAGE_DIR` 覆盖
- 当前支持本地 PDF 下载/预览：`GET /api/uploads/pdf/{pdf_upload_id}`，按稳定 upload id 读取 `UPLOAD_STORAGE_DIR` 下的 PDF 文件
- 当前支持文本型 PDF 预览：parse result 可返回 `extraction_method="pypdf-text-preview"` 与 `preview_text`；预览会优先选择摘要/正文信号窗口，避开明显页眉页脚、参考文献开头和低文本密度行；无法抽取文本时返回 `file-metadata-placeholder`

文献检索 API：

```bash
curl "http://127.0.0.1:8010/api/literature/search?q=特应性皮炎"
```

支持参数：

- `q`：必填检索关键词，后端会 trim。
- `source`：`all` / `cn_literature` / `pubmed`，默认 `all`。
- `page`：页码，默认 `1`。
- `page_size`：每页数量，默认 `10`，最大 `50`。
- `sort`：`relevance` / `year_desc` / `year_asc`，默认 `relevance`。
- `has_pdf_upload`：可选布尔值；`true` 仅返回已挂载上传 PDF metadata 的条目，`false` 排除已挂载 PDF 的条目，省略则不按 PDF 状态过滤。

示例：

```bash
curl "http://127.0.0.1:8010/api/literature/search?q=瘙痒&source=cn_literature&page=1&page_size=5&sort=relevance"
curl "http://127.0.0.1:8010/api/literature/search?q=特应性皮炎&has_pdf_upload=true"
```

返回字段保留 `query`、`total`、`items`，并新增 `source`、`page`、`page_size`、`total_pages`、`sort`，用于前端分页、排序和数据来源视图展示。`items[*].record_origin` 用于区分 `seed_sample` 演示样本与 `pubmed_live` 实时同步记录。

文献详情 API：

```bash
curl "http://127.0.0.1:8010/api/literature/cn-ad-gbs-001"
```

PDF upload API（本地文件存储 + 自动关联 literature metadata；默认返回 pending）：

```bash
curl -X POST "http://127.0.0.1:8010/api/uploads/pdf" \
  -F "literature_id=cn-ad-gbs-001" \
  -F "file=@/absolute/path/to/ad-evidence.pdf;type=application/pdf"
```

PDF download/preview API（本地对象存储 mock）：

```bash
curl -L "http://127.0.0.1:8010/api/uploads/pdf/<pdf_upload_id>" \
  -o ad-evidence.pdf
```

说明：实际上传按文献 ID、原始文件名与 PDF 字节 SHA-256 生成有界的不可变 `pdf_upload_id`；下载时使用上传响应中的 ID，不从文件名推导。重复同名上传不会改写既有引用对应的 PDF。上传先校验 PDF 字节签名（不等于完整格式/内容审核），再原子落盘并写入 `pending`；独立 auto-parse endpoint 接受可选 `pdf_upload_id`，前端始终传入当前 ID；过期请求或解析期间替换上传返回 409，保持新文件为 pending。该端点负责推进 parse 状态，并补充 `pdf_parse_message`、`pdf_parse_started_at`、`pdf_parse_finished_at`、`last_parse_trigger`、`parse_attempt_count` 与 `pdf_parse_result`。解析成功后会向 runtime chunk 状态补充 `source_type=uploaded_pdf` 的 chunk，使上传 PDF 的解析片段可进入 RAG 检索与 citation cards。

Auto-parse API：

```bash
curl -X POST "http://127.0.0.1:8010/api/uploads/pdf/auto-parse" \
  -H "Content-Type: application/json" \
  -d '{"literature_id":"cn-ad-gbs-001","file_name":"ad-evidence.pdf"}'
```

PDF metadata attach API（backend-only）：

```bash
curl -X POST "http://127.0.0.1:8010/api/literature/pdf-metadata" \
  -H "Content-Type: application/json" \
  -d '{"literature_id":"cn-ad-gbs-001","file_name":"ad-evidence.pdf","source_type":"uploaded_pdf"}'
```

PDF parse status API（backend-only）：

```bash
curl -X POST "http://127.0.0.1:8010/api/literature/pdf-parse-status" \
  -H "Content-Type: application/json" \
  -d '{"literature_id":"cn-ad-gbs-001","pdf_parse_status":"parsed"}'
```

RAG API：

```bash
curl -X POST "http://127.0.0.1:8010/api/rag/answer" \
  -H "Content-Type: application/json" \
  -d '{"question":"特应性皮炎和肠-脑-皮肤轴有什么关系？","source":"all","top_k":2}'
```

当前 RAG endpoint 默认采用 `deterministic` provider + `keyword` retrieval：基于 literature + chunk 样本，对 title/snippet/abstract/keywords/evidence_tags/chunk text 做关键词命中计分，并返回 answer + citation cards + “非诊断结论、需结合临床”免责声明。后端契约测试保证每个 `citations[*].literature_id` 都能通过 `/api/literature/{item_id}` 解析到文献详情。RAG 请求支持 `source`（`all` / `cn_literature` / `pubmed`）和 `top_k`（>= 1）控制 citation card，并返回 `retrieval` 元数据（`applied_source`、`applied_top_k`、`available_citation_count`、`strategy`）供前端展示当前检索条件；response 顶层同时返回 `provider_name`、`input_tokens`、`output_tokens`、`grounding` metadata、`sli` 与服务端 HMAC `integrity_token`，其中 deterministic / fallback 路径 token usage 为 `null`、grounding 为 `skipped`。

RAG 导出 API：

```bash
curl -X POST "http://127.0.0.1:8010/api/rag/answer/export" \
  -H "Content-Type: application/json" \
  -d @rag-answer.json

curl -X POST "http://127.0.0.1:8010/api/rag/answer/export/docx" \
  -H "Content-Type: application/json" \
  -d @rag-answer.json \
  --output qiyan-rag-answer.docx
```

`rag-answer.json` 必须是 `/api/rag/answer` 刚返回的完整、未修改 payload，并保留 `integrity_token`；任何字段缺失或被客户端篡改，Markdown/DOCX 导出都会返回 `409`。Markdown 导出用于纯文本证据简报；`.docx` 导出使用后端标准库生成最小 OOXML 包，保留多行回答换行并剥离 XML 非法控制字符，适合在 Word / WPS 中继续编辑。当前签名密钥为单进程内存态，服务重启后旧 payload 需要重新请求答案。

SLI（成本/延迟可观测）：

- response 顶层 `sli` 返回 `provider_latency_ms`（仅包住 provider 生成调用）与 `estimated_cost_usd`。
- deterministic / fallback 路径 `provider_latency_ms` 为整数、`estimated_cost_usd` 为 `null`。
- 成本由 token 用量 × `QIYAN_OPENCODE_GO_PRICE_INPUT_PER_MTOK` / `QIYAN_OPENCODE_GO_PRICE_OUTPUT_PER_MTOK`（USD/百万 token）计算；单价默认 `0.0` 即不估算（不臆造价格）。
- 后端额外打印不含 secret 的 `rag_sli` 结构化日志（provider、grounding、latency、token、cost、strategy）；`/rag` 页面与 Markdown 导出展示延迟与成本。

Grounding：

- `opencode_go` 是当前优先 live-provider grounding 路径：后端优先发送 OpenAI-compatible `record_grounded_claims` function tool，工具参数只允许 `claims[].text` 与 `claims[].evidence_refs`；后端只展示由工具输入重新组装且通过本次 citation 证据 ID 白名单的 answer。
- 若 OpenCode Go 网关或模型拒绝 tool/function calling，provider 会重试不带 tools 的 structured claims JSON 路径，后续仍由 structured claim grounding v3 校验：`{"claims":[{"text":"...","evidence_refs":["chunk-..."]}]}`。
- `anthropic` 成功路径保留 provider-native strict tool use，但当前后置为可选 smoke，不作为优先路径。
- 若 provider 未调用预期工具、工具参数不合法、claims 为空，或任一外部 provider 引用了本次 citations 未提供的证据 ID，`answer` 会被替换为拦截提示，`grounding.status="blocked"`，但 citations、provider name、token usage、`claim_count`、`cited_claim_count`、`structured_claims`、native grounding 与 tool metadata 会保留，便于排查。
- 语义级 grounding（hallucination reject）：结构与证据 ID 校验通过后，外部 provider 的每条 claim 还会与其引用 chunk 文本（`quote`，缺失时回退 `snippet`）计算 cosine 相似度；任一 claim 低于阈值则 `grounding.status="blocked"`、`blocked_reason="semantic_low_support"`，`grounding.structured_claims[].semantic_score`、`min_semantic_score`、`semantic_threshold` 一并返回。阈值由 `QIYAN_GROUNDING_SEMANTIC_THRESHOLD` 控制（默认 `0.40`，`<=0` 关闭）。**默认 `hashing` embedding backend 下该分数是逐字符的词汇重叠代理（lexical proxy），不是真正的语义判定；`QIYAN_EMBEDDING_BACKEND="bge"` 可原地升级为真实语义。** 标注语料 `backend/data/evals/grounding_semantic_pairs.json` 上，默认阈值对忠实 claim 零误拦、配对分离 10/10；可通过 `run_grounding_semantic_separation` 复核混淆矩阵。
- `deterministic` 与外部 provider fallback 到 deterministic 的路径不做后验拦截，`grounding.status="skipped"`（语义 gate 同样只作用于 `anthropic` / `opencode_go`）。
- 当前 grounding 约束引用声明、工具调用、越界证据 ID 与上述语义支持度阈值；语义层为 lexical proxy（除非启用 `bge`），仍不等同于完整事实核验，也不代表真实 LLM 默认开放（隐私措辞、延迟/成本 SLI 为独立后续 slice）。

可选 LLM providers（本地 smoke 用，默认不启用）：

- `QIYAN_LLM_PROVIDER=deterministic` 或未设置：默认离线 deterministic provider。
- `QIYAN_LLM_PROVIDER=mock_claude`：离线 mock provider，用于前后端 wiring 与 UI 展示。
- `QIYAN_LLM_PROVIDER=opencode_go`：当前优先 live-provider；调用 OpenCode Go OpenAI-compatible Chat Completions API；优先尝试 function tool grounding，必要时回退 structured claims v3。
- `QIYAN_LLM_PROVIDER=anthropic`：后置可选；调用 Anthropic SDK；key 从 `ANTHROPIC_API_KEY` 读取；模型与 token 上限可用 `QIYAN_ANTHROPIC_MODEL`、`QIYAN_ANTHROPIC_MAX_TOKENS` 覆盖；成功路径必须经过 `record_grounded_claims` strict tool-use grounding。
- provider 出错或缺 key 时应回退 deterministic，不应让 `/api/rag/answer` 对用户硬失败。

- `QIYAN_LLM_PROVIDER=opencode_go` 时，RAG answer 文本会调用 OpenCode Go OpenAI-compatible Chat Completions API；检索、citation cards 与 disclaimer 仍由本地后端控制。
- API key 只从 `QIYAN_OPENCODE_GO_API_KEY` 读取，不能写入仓库、README、handoff 或测试。
- 当前 opt-in smoke 默认 endpoint 与模型（2026-06-08）：`QIYAN_OPENCODE_GO_BASE_URL="https://ai.router.team/v1"`，`QIYAN_OPENCODE_GO_MODEL="gpt-5.5"`，`QIYAN_OPENCODE_GO_MAX_TOKENS="4096"`。
- 历史基线说明：2026-05-31/06-02 的 live smoke 与 price SLI 基于 `deepseek-v4-flash`，该模型为 thinking mode，曾拒绝强制 `tool_choice`（HTTP 400），且需要 >=4000 token 才能避免空 content fallback。切到 router.team + gpt-5.5 后，价格、延迟、NLI pass rate 与治理通过率都需要重新采样，不能沿用 deepseek 历史数字作为当前预算或 L2 决策依据。详见 `docs/evaluations/2026-05-31-opencode-go-bge-smoke.md`、`docs/evaluations/2026-06-02-opencode-go-price-sli-baseline.md` 与 `docs/guides/real-llm-enablement-runbook.md`。
- 未设置 key、HTTP 错误、网关失败或响应结构异常时，provider 会记录不含 secret 的 warning，并回退到 deterministic answer。

可选 retrieval providers（默认不启用 vector/hybrid）：

- `QIYAN_RETRIEVAL_PROVIDER=keyword` 或未设置：默认 keyword + alias ranker。
- `QIYAN_RETRIEVAL_PROVIDER=vector`：使用本地 chunk vector index；默认 hashing embedding backend 可离线运行。
- `QIYAN_RETRIEVAL_PROVIDER=hybrid`：用 Reciprocal Rank Fusion 融合 keyword + vector。
- 当前默认不启用真实 embedding 模型；`vector` / `hybrid` 仅用于 opt-in ablation 与 smoke。

PowerShell 本地 smoke 示例：

```powershell
cd backend
$env:QIYAN_LLM_PROVIDER="opencode_go"
$env:QIYAN_OPENCODE_GO_API_KEY="<local-secret>"
$env:QIYAN_OPENCODE_GO_MODEL="gpt-5.5"
$env:QIYAN_OPENCODE_GO_MAX_TOKENS="4096"
& .\.uv-test-venv\Scripts\fastapi.exe dev app/main.py --port 8010
```

另开终端调用：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8010/api/rag/answer" `
  -ContentType "application/json" `
  -Body '{"question":"特应性皮炎和肠-脑-皮肤轴有什么关系？","source":"all","top_k":1}'
```

RAG eval API：

```bash
curl "http://127.0.0.1:8010/api/evals/rag-ad/report"
curl "http://127.0.0.1:8010/api/evals/rag-ad/report?corpus=runtime"
```

当前评估报告基于 `backend/data/evals/rag_ad_eval_questions.json` 的 50 个特应性皮炎问题，调用 deterministic RAG 后返回 summary + item results。默认 `corpus=seed`，固定读取 tracked seed 文献/chunk，避免本地 uploaded PDF/runtime state 污染 benchmark；显式 `corpus=runtime` 才评估 `backend/data/runtime/` 本地状态。当前基线目标：50 题通过率保持内部基线，citation/chunk 命中、disclaimer coverage 与 must_not violations 以本地测试输出与最新 handoff 为准。

Network pharmacology API（默认 mock，live 需显式 opt-in）：

```bash
curl -X POST "http://127.0.0.1:8010/api/network/analyze" \
  -H "Content-Type: application/json" \
  -d '{"query":"消风散","analysis_type":"formula","research_protocol":{"disease":"atopic_dermatitis","phenotype":"特应性皮炎伴2型炎症与皮肤屏障异常","species":"Homo sapiens","evidence_policy":"direct_human_first","query_date":"2026-07-11"}}'
```

随后轮询：

```bash
curl "http://127.0.0.1:8010/api/network/result/<task_id>"
curl "http://127.0.0.1:8010/api/network/entities"
```

离线 Open Targets raw-artifact 核验需要 operator 预先配置 trusted manifest。PowerShell multipart 示例（`metadata.json` 内容必须与 manifest 中该 raw hash 的条目完全一致）：

```powershell
$metadata = Get-Content -Raw C:\path\to\metadata.json
curl.exe -X POST "http://127.0.0.1:8010/api/network/disease-import/verify" `
  -F "query=消风散" `
  -F "analysis_type=formula" `
  -F "evidence_policy=direct_human_first" `
  --form-string "metadata=$metadata" `
  -F "file=@C:\path\to\open-targets-response.json;type=application/json"
```

同一 owner 完成疾病 raw-artifact 核验后，才可用 `POST /api/network/compound-import/verify` 上传离线 ChEMBL known-activity artifact。operator 必须先配置 `NETWORK_CHEMBL_MANIFEST_PATH`；multipart 只能包含 `source_task_id`、`metadata`、`file`，其中 metadata 必须与该 raw-byte hash 的 manifest 条目完全一致：

```powershell
$compoundMetadata = Get-Content -Raw C:\path\to\chembl-metadata.json
$sourceTaskId = "network-REPLACE_WITH_VERIFIED_DISEASE_TASK_ID"
curl.exe -X POST "http://127.0.0.1:8010/api/network/compound-import/verify" `
  -F "source_task_id=$sourceTaskId" `
  --form-string "metadata=$compoundMetadata" `
  -F "file=@C:\path\to\chembl-known-activities.json;type=application/json"
```

服务端按 `task_id + owner_id` 查找 source task；它必须已有 `server_verified_raw_artifact` disease snapshot，且 compound metadata 的 `species`、`query_date` 必须等于父 task 的研究协议。成功时创建持有冻结协议、疾病 snapshot 与 compound snapshot 的新 task，父 task 永不修改；客户端不得提交 owner/reviewer、records、hash、provenance、readiness 或 adjudication 字段。完整 artifact/manifest 格式见 `docs/guides/network-compound-target-import.md`。

ADR-0018 Gate 3 组学验证层（显式 opt-in，默认离线路径不含组学）：`POST /api/network/omics-import/verify` 把 GEO series matrix（可选 GPL 平台注释文件）冻结为不可变 omics snapshot——服务端计算 SHA-256、按 accession 封存、同输入重导幂等（`201`/`200`）、不同内容同 accession 冲突 `409`；manifest 的 `raw_artifact.sha256/frozen_at/frozen_by` 与整段 `provenance` 由服务端封存，客户端提交即 `422`。独立 validator：`python backend/scripts/validate_omics_import.py --omics-dir <dir> --accession GSE32924`。

```powershell
$omicsManifest = Get-Content -Raw C:\path\to\omics-manifest.json
curl.exe -X POST "http://127.0.0.1:8010/api/network/omics-import/verify" `
  --form-string "manifest=$omicsManifest" `
  -F "file=@C:\path\to\GSE32924_series_matrix.txt.gz;type=application/gzip" `
  -F "annotation_file=@C:\path\to\GPL570.annot.gz;type=application/gzip"
```

对已完成、有冻结疾病 lineage 的 task，`GET /api/network/result/{task_id}?omics_verification=true&omics_accession=GSE32924` 显式 opt-in 后在结果信封返回确定性 DEG 候选投影（Welch t-test + 基因层面 BH，只出 `pending_human_confirmation` 候选，不定级）。唯一把某条边的证据等级升到 `omics_validated` 的路径是人工判定：在既有 append-only adjudication 流上提交 `decision="omics_confirmed"` 并携带 `omics` 上下文，服务端在判定时刻重验全部机器条件（候选存在、阈值满足、数据集 Homo sapiens + 特应性皮炎、task lineage 绑定），任一不满足即 fail closed。mock 数据恒为 `mock_inferred`；`omics_validated` 不翻转 `formal_network_ready`。真实 GSE32924 验收记录见 `docs/reports/2026-09-03-gate3-g32-real-data-verification.md`。

writer 消费契约（2026-09-06 落地，契约见 `docs/plans/2026-08-14-writer-consumption-contract-draft.md`）：所有 lineage 行终态判定后 `POST /api/network/result/{task_id}/assembly-plans` 封存候选计划；未来的网络装配 writer 写任何产物前必须走一次性消费原语 `POST /api/network/result/{task_id}/assembly-plans/{plan_id}/consume`——服务端在同一临界区内原子重验 R1-R9（plan 仍是 latest、判定流与冻结 lineage 绑定未变、父子协议成立）并追加不可变输出信封与 exactly-once 消费记录。同 writer 同输出重试返回 `200 existing`（幂等重放）；判定追加未重封存报 `409 adjudication_changed`；已重封存报 `409 plan_superseded`；持久化哈希自相矛盾报 `500 assembly_integrity_failed`；容量上限（env `QIYAN_CONSUMPTION_RECORD_LIMIT`，默认 1000）报 `429`。响应信封如实标注 `backend_fidelity`（JSON=`preview` 仅同进程同实例安全，SQLite/PG=`production`）。消费成功不等于科研就绪：`formal_network_ready` 恒 false，输出只是审计产物。

```bash
curl -X POST "http://127.0.0.1:8010/api/network/result/<task_id>/assembly-plans/<plan_id>/consume" \
  -H "Content-Type: application/json" \
  -d '{"writer_id":"assembly-writer-01","output_payload":{"edges":[]}}'
curl "http://127.0.0.1:8010/api/network/result/<task_id>/assembly-plans/<plan_id>"  # 只读审计视图：is_latest_plan / is_consumed / is_superseded_by
```

protected mode 直连脚本必须在创建、轮询和报告请求中保持同一个 reviewer id：

```bash
curl -X POST "http://127.0.0.1:8010/api/network/analyze" \
  -H "X-Access-Token: dev-token-1" \
  -H "X-Qiyan-Reviewer: reviewer-a" \
  -H "Content-Type: application/json" \
  -d '{"query":"消风散","analysis_type":"formula","research_protocol":{"disease":"atopic_dermatitis","phenotype":"特应性皮炎伴2型炎症与皮肤屏障异常","species":"Homo sapiens","evidence_policy":"direct_human_first","query_date":"2026-07-11"}}'
curl "http://127.0.0.1:8010/api/network/result/<task_id>" \
  -H "X-Access-Token: dev-token-1" \
  -H "X-Qiyan-Reviewer: reviewer-a"
```

任务创建时会持久化内部 `owner_id`，但 API response 不暴露该字段。其他 reviewer 查询同一 task id 时统一得到 `404`，且不会推进任务状态；旧 runtime 中没有 owner 的 task 同样 fail closed，需要清理或显式迁移。

默认模式下，网络药理学包含 seed graph + runtime task 壳 + GO/KEGG 富集分析（mock），用于验证「复方/草药 - 成分 - 靶点 - 通路 - 疾病」产品路径、citation/entity 双向跳转、富集分析表格展示与前端 Markdown 报告导出。富集分析使用本地 JSON 字典（`backend/data/network/sample_go_terms.json`、`sample_kegg_pathways.json`）模拟 GO/KEGG 数据库，通过 scipy 超几何分布计算 p-value，返回 top 20 显著富集的通路/功能（p < 0.05，至少 2 个重叠基因）。mock 模式不代表科研级 TCMSP / STRING / KEGG REST API 或真实 FDR 校正。

`POST /api/network/analyze` 可选接收旧的任务级 `disease_target_import`，该路径固定为 `unverified_client_import`。推荐先使用 `POST /api/network/disease-import/verify` multipart 入口上传离线保存的 Open Targets GraphQL `.json` response 与声明元数据：服务端先用 `NETWORK_OPEN_TARGETS_MANIFEST_PATH` 指向的 operator-controlled manifest 按 raw-byte hash 核对 release、结构化 query parameters、UTC retrieved time、`association_score` 阈值、Ensembl mapping version 和 usage/license note，再自行解析 records，计算 raw-byte `source_artifact_sha256` 与 canonical `import_payload_sha256`，并把原始字节保存到 `NETWORK_RAW_ARTIFACT_DIR`（默认 gitignored runtime）。客户端不能提交 records、hash、provenance、readiness 或 adjudication 字段。前端 `/network` 已使用 `FormData` 走该入口；完整格式与验证边界见 `docs/guides/network-disease-target-import.md`。

`POST /api/network/compound-import/verify` 是第二阶段的离线 ChEMBL artifact 核验入口，而非 live ChEMBL API。它只接受 `source_task_id`、`metadata`、`file` 三个 multipart 字段，按访问控制得到的 owner 对 source task fail-closed 查询；该 task 必须有服务端核验的 disease snapshot。服务端用独立的 `NETWORK_CHEMBL_MANIFEST_PATH`（operator-controlled、按 raw-byte SHA-256 索引）核对 `chembl_known_activity_v1` metadata，静态解析 known activities，生成 raw-byte `source_artifact_sha256` 与按 canonical 排序的 `import_payload_sha256`，再以新 immutable child task 保存。它不会改写 parent task，也不接收任何客户端 records、hash、provenance、readiness、lineage 或人工判定字段。详见 `docs/guides/network-compound-target-import.md`。

compound child 的结果仅用于审计冻结的双侧 lineage 和派生交集；服务不会从同一任务构造 provider 链、PPI、通路或 enrichment，`chains=[]`、`enrichment=null` 是有意的失败关闭边界而不是零网络结论。child 会导出 `source_task_id` 指向其疾病 parent；缺少该 link 的 legacy child 在结果和报告读取时失败关闭。独立 validator 还会检查 snapshot-only 的 chains、PPI、data sources、pipeline steps、enrichment 及 warning/readiness blocker；对 parent link 本身，它只核对格式与非自指，不证明 parent task 存在或 owner 归属。

结果中的 `target_lineage` 分开声明观察单元：`disease_targets` 与 `compound_targets` 以 source record 为行，`intersection_targets` 以 canonical-symbol derivation 为行。同一标准靶点来自两个来源记录时保留两行，但 unique target count 只计一次；每个派生候选交集只生成一行，并完整引用同 symbol 的所有 disease/compound `lineage_row_id`。没有导入时 disease/intersection 失败关闭为空；旧客户端导入路径的 `records=[]` 只表示客户端声明零命中，来源与查询执行仍未验证。所有自动行和派生交集默认 `pending/unreviewed`。可用独立于业务 service 的标准库脚本复核导出的 result JSON：

```powershell
cd backend
& .\.uv-test-venv\Scripts\python.exe scripts\validate_network_target_lineage.py C:\path\to\network-result.json
```

对于双侧 raw-artifact task，同时提供两份原始文件：

```powershell
& .\.uv-test-venv\Scripts\python.exe scripts\validate_network_target_lineage.py `
  C:\path\to\network-result.json `
  --disease-source-artifact C:\path\to\open-targets-response.json `
  --compound-source-artifact C:\path\to\chembl-known-activities.json
```

脚本复算三个集合的 unique symbol count、source/derivation row count、稳定 row ID、疾病/成分 canonical-symbol 交集、intersection 双侧 refs、导入 payload hash、阈值规则、默认人工状态与 protocol 一致性；为各 `server_verified_raw_artifact` 另行提供 source artifact 时还会复算 raw-byte hash。一致时退出码为 `0`，不一致或输入无效时为 `2`。脚本不 import 生产 service/parser，也不独立重演 Open Targets GraphQL 或 ChEMBL raw-to-records 派生；它只证明已检查的 artifact consistency 与持久化 payload 完整性，不证明 release 选择正确、来源真实、靶点生物学意义或 scientific readiness。

真实网络药理学链路是显式 opt-in，不进入默认路径：

> 注意：live 链路是 `TCMSP/cache → PubChem → ChEMBL → UniProt → STRING → KEGG` 的多步外部调用，且 `QIYAN_NETWORK_ALLOW_TCMSP_SCRAPE` 默认 `false`、预测靶点需本地 artifact，未预先准备缓存/靶点文件时大概率跑不通。**内部预览与 reviewer 走查请直接用默认 mock 模式**，不要为走查临时开 live。

- 设置 `QIYAN_NETWORK_DATA_PROVIDER="live"` 后，`POST /api/network/analyze` 与轮询 response 会返回 `data_mode="live"`，并输出 `data_sources`、`pipeline_steps`、`warnings`、`error`、`target_evidence_type`、`evidence_refs` 与可选 `ppi_edges`。
- live 链路按 `TCMSP/cache → PubChem CID → ChEMBL known activity → UniProt 标准化 → STRING PPI → KEGG pathway/enrichment → report provenance` 执行；外部响应只写入 `backend/data/runtime/network_cache/`，不会回写 seed fixture。
- `QIYAN_NETWORK_ALLOW_TCMSP_SCRAPE` 默认 `false`。关闭时 TCMSP 入口只读已有 cache；开启前需 operator 明确接受抓取稳定性、授权和限速风险。
- SwissTargetPrediction 不自动 crawler；预测靶点只通过 `QIYAN_NETWORK_TARGET_PREDICTION_FILE` 指向本地 JSON/CSV artifact 导入，字段为 `compound,target_symbol,score,source,source_record_id,retrieved_at`。
- `QIYAN_NETWORK_HTTP_TIMEOUT_SECONDS` 与 `QIYAN_NETWORK_RATE_LIMIT_PER_SECOND` 控制 live API timeout 和限速；外部失败会进入 `warnings` 或业务 `failed` task，不应变成正常业务流的 500。
- 回滚路径：清空或设置 `QIYAN_NETWORK_DATA_PROVIDER="mock"` 即回到默认离线 mock。需要强制重新请求外部源时，清理 `backend/data/runtime/network_cache/`。

PowerShell live smoke 示例（不会自动开启 TCMSP 抓取；需提前准备 cache 或 prediction artifact）：

```powershell
cd backend
$env:QIYAN_NETWORK_DATA_PROVIDER="live"
$env:QIYAN_NETWORK_CACHE_DIR="data/runtime/network_cache"
$env:QIYAN_NETWORK_TARGET_PREDICTION_FILE="C:\path\to\network-target-predictions.csv"
& .\.uv-test-venv\Scripts\fastapi.exe dev app/main.py --port 8010
```

另开终端轮询：

```powershell
$task = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8010/api/network/analyze" `
  -ContentType "application/json" `
  -Body '{"query":"黄芪","analysis_type":"herb","research_protocol":{"disease":"atopic_dermatitis","phenotype":"特应性皮炎伴2型炎症与皮肤屏障异常","species":"Homo sapiens","evidence_policy":"direct_human_first","query_date":"2026-07-11"}}'

do {
  $result = Invoke-RestMethod "http://127.0.0.1:8010/api/network/result/$($task.task_id)"
  if ($result.status -in @("queued", "running")) { Start-Sleep -Milliseconds 250 }
} while ($result.status -in @("queued", "running"))

if ($result.status -eq "completed") {
  Invoke-RestMethod "http://127.0.0.1:8010/api/network/result/$($task.task_id)/report"
} else {
  throw "Network task failed: $($result.error)"
}
```

Report 是只读观察接口：任务仍 queued/running 时返回 202，completed 时返回 200 Markdown，failed 时返回 409；读取 report 不会推进状态。

Network analysis response 示例（包含 enrichment 字段）：

```json
{
  "task_id": "network-abc123",
  "query": "黄芩",
  "analysis_type": "herb",
  "chains": [...],
  "enrichment": {
    "analysis_type": "combined",
    "input_gene_count": 5,
    "background_gene_count": 20000,
    "terms": [
      {
        "term_id": "GO:0006954",
        "term_name": "inflammatory response",
        "term_name_zh": "炎症反应",
        "category": "biological_process",
        "gene_count": 450,
        "overlap_count": 3,
        "p_value": 0.0001,
        "adjusted_p_value": 0.0024,
        "genes": ["IL6", "TNF", "IL1B"]
      }
    ],
    "timestamp": "2026-06-01T10:00:00Z"
  },
  "disclaimer": "非诊断结论、需结合临床。"
}
```

标准后端验证：

```powershell
cd backend
& .\.uv-test-venv\Scripts\python.exe -m ruff format --check app tests
& .\.uv-test-venv\Scripts\python.exe -m ruff check app tests
& .\.uv-test-venv\Scripts\python.exe -m mypy app
& .\.uv-test-venv\Scripts\python.exe -m pytest -q
```

## 前端

首次安装：

```bash
cd frontend
pnpm install
```

构建验证：

```bash
cd frontend
pnpm build
```

启动开发服务：

```powershell
cd frontend
pnpm dev
```

也可以在仓库根目录直接跑（root `package.json` 只是转发到 `frontend/`，效果相同）：

```powershell
pnpm dev            # 等价于 cd frontend && pnpm dev，起 http://localhost:3000
pnpm dev:backend    # 等价于在 backend/ 起 uvicorn，http://127.0.0.1:8010
```

注意：在仓库根目录直接执行 `pnpm dev` 以外的 frontend 子命令（如 `pnpm build`）同样需要 `cd frontend`，或使用上面根目录的同名转发脚本；根目录本身不是 Next.js 应用。浏览器完整体验需要前后端同时在线：前端 `:3000` 渲染页面壳，文献/RAG/网络数据来自后端 `:8010`。一键同时起两侧的脚本是 `.\scripts\run-internal-preview.ps1`（停止用 `-Stop`）。

前端 API 地址默认是 `http://127.0.0.1:8010`。如需覆盖：

```powershell
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8010"
cd frontend
pnpm dev
```

前端不接收后端访问 token。后端启用 `QIYAN_ACCESS_TOKENS` 时，本地脚本或 curl 可直接带 `X-Access-Token`；浏览器页面必须放在能完成用户认证并在服务端注入 token 的反向代理后面。不要把 secret 写入任何 `NEXT_PUBLIC_*` 变量。

前端测试：

```bash
cd frontend
pnpm test
pnpm typecheck
pnpm build
```

页面：

- 首页：`/`
- 文献检索页：`/literature`
- RAG 问答页：`/rag`
- 文献详情页：`/literature/[id]`
- RAG 评估页：`/evals/rag-ad`
- 合规说明页：`/compliance`
- 网络药理学页：`/network`

当前前端能力：

- `/literature`：支持 query 输入、4 类数据来源视图（全部来源 / PubMed 记录 / CNKI sample / 上传 PDF）、加载/错误/空结果状态、结果卡片跳转详情页，并展示演示数据提示与随来源切换的合规 banner；每条结果会标明记录来源，演示 seed 不可当作外部数据库真实文献引用。
- `/rag`：支持 question、source、top_k 输入，展示 answer、provider、retrieval strategy、token usage、grounding status、native grounding、tool metadata、句级引用覆盖、结构化声明数、citation cards 与免责声明；当外部 provider 草稿未通过 grounding 时展示拦截提示；支持 Markdown 和 Word `.docx` 导出。
- `/literature/[id]`：服务端读取文献详情，展示统一 meta/body 样式，并提供 PDF 上传入口、PDF 预览链接、parse status、parse message、时间戳、触发来源、尝试次数、解析方式与解析结果预览。
- `/evals/rag-ad`：客户端触发 `/api/evals/rag-ad/report`，展示 50 题 RAG 评估的语料范围、通过率、引用命中、chunk 命中、免责声明覆盖、禁用语检查与 grounding 拦截计数。
- `/network`：提交 mock 网络药理学分析任务，展示 seed chain、entity chips、相关文献与 RAG/network 互链，并可把当前完成结果导出为 Markdown 报告。
- `/rag` 与 `/literature` 的状态文案、状态面板、meta 行和正文密度已做最小统一。
- 当 RAG 成功返回 0 citations 时，会展示明确空状态提示，而不是空白引用区。

## 合规底线

所有 AI 输出必须带：

非诊断结论、需结合临床。

本平台不替代医生诊断，不面向普通患者 C 端。

### 可信原则（对齐 `/compliance` 页，均有代码落地）

| 原则 | 落地方式 |
|------|----------|
| 数据来源可追溯 | 文献 `record_origin` 区分演示 seed / PubMed 实时同步；上传 PDF 只落本地 runtime；网络结果标注 `data_mode` 与证据分级 |
| 分析流程可审计 | 默认 deterministic 检索、request id、RAG SLI 结构化日志；网络证据分级为确定性纯函数 |
| 模型输出保留证据链 | 每条 citation 的 `literature_id` 必须能被 `/api/literature/{id}` 解析；真实模型经 grounding gate 校验 |
| 不替代实验/诊断结论 | 输出附免责声明；网络 mock 证据等级恒为 `mock_inferred`；引用只给检索匹配度，不给疗效/概率 |
| 大模型输出受控 | 默认离线 deterministic；真实 provider 显式 opt-in，未过 gate 的回答被拦截不外显 |

**平台可以做什么**：证据简报、带引用的问答、机制线索探索（演示数据）、可导出复核材料。
**平台不替代什么**：临床诊断/处方、药理与安全性评价、临床试验与药效学结论、专家审评与合规审查。mock 网络药理学结果不作为正式分析。

## MVP-C 概念对象（仅 schema 预留）

`backend/app/schemas/molecular.py` 定义了分子对接与分子动力学模拟的概念对象，为未来 MVP-C 阶段预留类型定义，**当前不提供实际功能**。

**已定义的 schema**：
- `Protein` - 蛋白结构对象（PDB ID、UniProt ID、序列）
- `Ligand` - 小分子配体对象（SMILES、InChI、分子量）
- `DockingResult` - 分子对接结果（结合亲和力、结合位点、RMSD）
- `MDSimulationConfig` - 分子动力学模拟配置（温度、压力、时长、力场）
- `MDSimulationResult` - MD 模拟结果（轨迹、能量、RMSD/RMSF）
- `SimulationTask` - 对接/MD 模拟任务（异步任务管理）

**当前状态**：
- ✅ Schema 定义完成（Pydantic models）
- ✅ 测试覆盖（11 个 schema 验证测试）
- ❌ 无 router、service 或 repository 实现
- ❌ 无前端页面或 API 集成
- ❌ 不应在当前代码中使用这些对象

**用途**：
- 为未来 MVP-C 阶段保留类型定义
- 确保与 network 模块的数据模型一致性（通过 `compound_id` 关联）
- 提前规划分子对接/MD 模拟的数据结构
