# AGENTS.md — Qiyan Nexus

> 本文件是项目地图层。当前事实源优先读 `docs/current-state.md`、`README.md`、`CONTEXT.md`、`docs/adr/` 与最新 handoff；历史规划已归档到 `docs/archive/pre-dev-planning/`。

## 仓库性质

项目已从纯规划阶段切换到可运行开发阶段。2026-07-11 起，唯一产品主轴是窄领域网络药理学自动化科研辅助；MVP-A 文献/PDF/RAG 能力作为证据服务层保留。网络药理学已具备 mock/live 任务壳、最小研究协议门禁、双侧离线 raw-artifact engineering provenance、owner-scoped 逐行人工 adjudication（2026-07-26 上线）与 source-bound 候选装配计划门禁（2026-08-02 上线），真实科研数据闭环仍未完成；真实 LLM / embedding / 生产数据库仍保持显式 opt-in 或后续 spike，不进入默认路径。2026-08 ADR-0018（Accepted，Gate 1-3 已确认）：在 ADR-0017 当前契约之上，把底层逻辑升级为组学策略，网络药理学为系统层核心，真实组学数据只作显式 opt-in 验证层；Gate 3 已选定转录组 GSE32924 并定义 `omics_validated` 证据等级；G3-1/G3-2/G3-3 三个切片已于 2026-09-03 落地（D-G3-A=a/D-G3-B=a 拍板）：omics manifest 冻结导入门禁 + 独立 validator、series matrix 确定性 DEG 候选投影（真实 GSE32924 验收：1,178 DEG 通过，IL6/STAT3/TNF 未过阈值，见 `docs/reports/2026-09-03-gate3-g32-real-data-verification.md`）、`omics_validated` 等级 + omics_confirmed HITL 判定（唯一升级路径，服务端判定时刻重验机器条件）；组学端点全部显式 opt-in，不进默认路径。检索质量基线：Track A 首版 150 标签（precision@5=0.113、MRR@5=0.163）；2026-08-17 种子扩展 batch1-5 完成（总表 83 条查询，runtime 语料 344→693 pubmed_live），工程侧 v2 盲评迭代至 p@5=0.400、MRR@5=0.744（补记见 `docs/reports/2026-08-17-pubmed-seed-expansion-batch2-5-changelog.md`）；标签仍是工程侧，真人 domain reviewer 数字出现前不声称检索有效。至今没有任何真人 domain reviewer 判定记录，「能记录判定/装配」不等于「已有人判定」，`formal_network_ready` 恒 false。

当前代码目录：
- `frontend/` — Next.js 前端应用
- `backend/` — FastAPI 后端应用
- `infra/` — 本地基础设施说明与后续 Docker Compose 入口
- `spikes/` — 一次性技术 spike 归档（如 PDF 抽取器对比），不是产品代码

历史规划产物：
- `docs/archive/pre-dev-planning/` — 早期 Cursor / Trae / Word / HTML 原型归档，仅作历史参考，不作为当前实现事实源。

## 快速导航

| 层级 | 文件 | 读它来做什么 |
|------|------|-------------|
| 当前事实源 | `docs/current-state.md` | 当前能力边界、事实源优先级、标准验证命令 |
| 入口 | `README.md` | 每个已实现 endpoint 的 curl 示例 |
| 命令与架构细节 | `CLAUDE.md` | 后端分层、RAG 管线、PDF 流、前端测试机制、codegraph 决策树；若命令冲突，以本文件的 Windows PowerShell 写法为准 |
| 领域语言 | `CONTEXT.md` | TCM 术语表、共享语言 |
| 长期模块路线图 | `docs/adr/0010-research-workbench-module-roadmap.md`、`0017-network-pharmacology-first-product-contract.md`、`0018-omics-strategy-platform-contract.md` | 证据工作台、网络药理学、分子对接/MD 的分阶段边界与概念预留；0017 是当前产品主轴契约基线，0018 是组学策略方向演进 |
| 最近交接 | `docs/handoffs/` | 越新的 handoff 越接近当前事实，用于跨会话续接 |
| 开发计划 | `docs/plans/` | 已落地或待执行的纵向切片计划 |
| 质量 | `docs/quality-score.md` | 各领域质量评分 |
| 验证报告 | `docs/reports/` | Gate/切片真实数据验收与检索盲评补记（如 2026-09-03 Gate 3、2026-08-17 种子扩展）；正文引用的验收数字以此为准 |
| 历史归档 | `docs/archive/pre-dev-planning/` | 早期需求、任务、设计、Word 文档与 HTML 原型，仅作追溯参考 |
| Agent 约定 | `docs/agents/` | 领域文档消费规则、本地 Markdown issue tracker（`.scratch/<feature-slug>/`）、triage 中文标签映射 |

## 代码结构查询

仓库已索引 `.codegraph/`（会话挂 codegraph MCP）：结构类问题（符号在哪、谁调用、改动影响面）先走 codegraph 工具而不是 grep 循环；CLAUDE.md 顶部有完整决策树与禁用场景（字面文本、日志、中文文案仍用 grep/Read）。

## 命令（本机是 Windows + pwsh，照抄）

后端 venv 是 `backend/.uv-test-venv`（不是 `.venv`），必须走 `Scripts\python.exe`。

`scripts/*.ps1` 是 UTF-8 无 BOM 且含中文注释，必须用 pwsh（7.x）执行；Windows PowerShell 5.1（`powershell.exe`）按 GBK 误读注释会在解析期直接报错（2026-09-28 实证 `run-internal-preview.ps1` line 26，见 `docs/handoffs/2026-09-28-facade-private-surface-shrink.md`）——解析失败与 diff 无关，先查执行宿主再查代码。

**端口事实（2026-09-16）**：本机 8000 保留给另一项目，全程不可触碰。本项目本地 `pnpm dev:backend`、前端 API fallback、preview 与 E2E 默认后端均为 8010，前端默认 3000。`run-internal-preview.ps1` / `verify-local.ps1` / `smoke-internal-preview.ps1` 继续显式拒绝本机 8000。前端所有 fetcher 共用 `frontend/lib/api/client.ts` 的 base URL 解析；server rendering 优先非公开 `QIYAN_INTERNAL_API_BASE_URL`，浏览器使用 `NEXT_PUBLIC_API_BASE_URL` 或 8010 fallback。CORS 仍仅允许本机回环 3000 / 3100；云端 runbook 与容器的内部 8000 属于独立部署语境。

```powershell
# 推荐：统一本地门禁（默认跑 backend 4 项 + frontend test/typecheck/build）
.\scripts\verify-local.ps1

# reviewer 走查或分支收口前追加 Playwright E2E；8000/3000 被占时用隔离端口
.\scripts\verify-local.ps1 -IncludeE2E -E2eBackendPort 8010 -E2eFrontendPort 3000

# 单侧门禁
.\scripts\verify-local.ps1 -BackendOnly
.\scripts\verify-local.ps1 -FrontendOnly
```

```powershell
# 后端验证门禁（提交前 4 项全绿）— 顺序：format -> lint -> type -> test
cd backend
& .\.uv-test-venv\Scripts\python.exe -m ruff format --check app tests
& .\.uv-test-venv\Scripts\python.exe -m ruff check app tests
& .\.uv-test-venv\Scripts\python.exe -m mypy app
& .\.uv-test-venv\Scripts\python.exe -m pytest -q

# 单测 / 单用例
& .\.uv-test-venv\Scripts\python.exe -m pytest tests\test_rag_service.py -q
& .\.uv-test-venv\Scripts\python.exe -m pytest "tests\test_rag_service.py::test_name" -q

# dev server (http://127.0.0.1:8010)
& .\.uv-test-venv\Scripts\fastapi.exe dev app/main.py --port 8010
```

```powershell
# 前端（pnpm，期望后端在 127.0.0.1:8010）
cd frontend
pnpm test        # node --import tsx --test tests/*.test.ts，无 build 步
pnpm typecheck   # next typegen && tsc --noEmit（含 tests/）
pnpm build       # next build --webpack
node --import tsx --test tests\literature-api.test.ts   # 单测文件
```

```powershell
# 仓库根便捷脚本（package.json 代理到 frontend/ 或 scripts/）
pnpm dev           # frontend dev
pnpm dev:backend   # 直接用 uvicorn 起后端 127.0.0.1:8010（不是 fastapi dev）
pnpm preview       # = scripts\run-internal-preview.ps1（isolated runtime 起前后端）
pnpm preview:stop

# 内部预览 isolated runtime + API smoke（用法详见 docs/current-state.md）
# 8000/3000 被其他应用占用时加 -BackendPort/-FrontendPort 换端口；
# -OpenTargetsManifestPath 注入 trusted manifest 以走查 verified disease-import 与 omics HITL 流程
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-open -BackendPort 8010 -FrontendPort 3000
.\scripts\smoke-internal-preview.ps1 -BackendUrl "http://127.0.0.1:8010"
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-open -Stop
.\scripts\run-internal-preview.ps1 -RuntimeRoot .tmp\trial-token -AccessToken "trial-token"
.\scripts\smoke-internal-preview.ps1 -AccessToken "trial-token"

# 全局终端命令 tcmtech（= scripts\tcmtech.ps1，shim 在 %LOCALAPPDATA%\Microsoft\WindowsApps\tcmtech.cmd
# 与 C:\Users\12035\bin\tcmtech[.cmd]）：起 8010/3000 + 开浏览器 + 前台阻塞，Ctrl+C 触发 finally 调 -Stop；
# 停止也可用 tcmtech -Stop（等价 pnpm preview:stop）。脚本带 CmdletBinding：未知/拼错的参数显式报错，
# 不得移除（移除会恢复「静默吞参照常启动」故障，-Stop 曾中招）。
# runtime 用默认 .tmp\internal-preview，所以 pnpm preview:stop 也能停它。重跑 tcmtech 会先自动停掉上一次服务。
# cmd shim 是 GBK (cp936) 编码（编辑器里中文显示为乱码属正常），勿按 UTF-8 重写；详见 docs/handoffs/2026-09-04-tcmtech-command.md
# ⚠ 状态（2026-09-28 实测）：上述三份 shim 本机均已缺失（~/bin 为空、WindowsApps 无 tcmtech.cmd、where tcmtech 无结果），命令当前不可用；
#   起服务改用 pnpm preview / pnpm preview:stop（等价 run-internal-preview.ps1）或 pnpm dev:backend + pnpm dev；shim 重建配方即上述 handoff 文档
```

- `pnpm e2e`（Playwright）不在每次提交门禁内，需先 `pnpm exec playwright install chromium` 及系统库，按 `frontend/e2e/README.md`。
- 浏览器自动化走查本项目 dev 页面时，role 定位点击可能假超时（工具行为非产品缺陷）：`elementFromPoint` 验证无遮挡后改用 evaluate 触发 DOM click 即可。
- GitHub Actions CI 位于 `.github/workflows/ci.yml`，规则说明见 `.github/workflows/README.md`；没有 `.cursor` 规则。提交前仍必须本地手跑上述 PowerShell / pnpm 门禁，不能把远端 CI 当作首次验证。

## 改代码前必看的硬约束（测试会卡）

- 后端严格分层：`api/` → `services/` → `repositories/` → `schemas/`，不许跨层（router 不直接读 JSON，service 不 import FastAPI）。router 在 `app/main.py` 接线。
- network service 是子模块直连 + 私有 façade patch-hub 结构：`services/network.py` 不是导入面，只是私有 late-binding hub（`__all__` 恰为三个可 patch 名 `_get_repository`/`uuid4`/`select_network_provider`，另保留 13 个被 sibling `_facade.X` 引用的管道名 re-export）。公共导入面就是兄弟模块本体：`app/api/network.py` 与测试一律直连 `network_common`（轻量公共原语，只依赖 schemas + canonical JSON，防 import cycle）、`network_imports` / `network_lineage` / `network_tasks` / `network_assembly` / `network_adjudication` / `network_queries` 与更早的 `network_providers` / `network_connectors` / `network_omics` / `network_chembl` / `network_open_targets` / `network_external_client`。测试 patch 用字符串形式 `monkeypatch.setattr("app.services.network.<name>", ...)`；子模块必须在函数体内 `from app.services import network as _facade` 走调用时解析——写成模块级 import 会静默绕过 monkeypatch；跨兄弟引用一律走 `_facade.`，唯一模块级例外是 `network_common`（零依赖、不在 monkeypatch 面上）。以上不变量由 `tests/test_network_facade_late_binding.py` 九断言守护（sibling 模块级 façade 导入含相对导入形态 / 可 patch 名裸调用 = 测试失败；三个行为断言证明 façade patch 从兄弟模块入口真实到达；api 层禁止导入 façade；除 guard 外测试含 conftest 与嵌套目录按 rglob 禁止导入 façade；façade `__all__` 恰为 patch 面；scanner 形态矩阵单元测试锁定绝对/相对/函数体全形态且以 network_common 合法导入为负控制；五组物理变异验证过，红原因见 handoff）；新增网络服务代码先选对子模块归属。
- CORS 仅放行本机回环 `localhost`/`127.0.0.1` 的 3000 与 3100（3100 对应 `run-internal-preview.ps1 -FrontendPort 3100` 换端口场景），仅 `GET, POST`；加来源或 `PUT`/`DELETE` 路由要改 `app/main.py` 中间件，并同步 `test_cors.py` 的放行+拒绝契约测试。
- 开放预览也有请求来源边界（2026-09-14）：仅接受回环 Host；Origin 必须是上述前端来源或后端自身来源。CORS 不能代替写入防护，multipart simple request 同样在处理前拒绝外站与 `null` Origin。请求上限按实际流式字节计数，不仅依赖 Content-Length。TestClient 使用回环 base_url；虚构域名仅用于拒绝测试。受 token 保护的部署继续按既有代理/鉴权契约运行。
- 免责声明字符串 `非诊断结论、需结合临床。` 是 load-bearing，被后端测试、eval、前端断言引用，必须逐字节一致，不要改写 `services/rag.py` 的 `DISCLAIMER`。同族还有 RAG 实体零命中话术：`entity_matched is False` 时输出「未检索到与所问实体直接对应的证据片段」开头（`services/llm/provider.py`，`test_llm_provider.py` 断言），改话术要同步改测试，且不得顺手调检索排序/eval 预期。
- RAG 契约：`/api/rag/answer` 返回的每个 `citations[*].literature_id` 必须能被 `/api/literature/{id}` 解析（`test_rag_literature_contract.py`）。
- runtime 状态写在 `backend/data/runtime/`（gitignored），是本地开发态，不要回写 seed fixture，也不要把 runtime state / 上传的 PDF 当 fixture 提交。
- reviewer identity 只能来自 access token 验证后的 request state；受保护部署由可信 nginx 覆盖写入 `X-Qiyan-Reviewer`。禁止信任浏览器或任意客户端直传的 reviewer header，后端 8000 必须保持 loopback。
- network task 必须按 `task_id + owner_id` 查询和推进；foreign 或 legacy ownerless task 都要 fail closed。report GET 是只读观察接口，不得借读取推进状态或写 runtime。
- 派生 network task 的 parent link 也是授权边界：必须通过同 owner 的查询解析，`source_task_id` 要跨 JSON/SQLite、result、report 持久化且不可变，禁止 self-link 与 child-of-child。缺少 link 的 legacy child 在 result/report/export 读取时只返回非持久化失败投影，不得由读取修复或推进。
- 靶点集合必须失败关闭：`disease_targets`、`compound_targets`、`intersection_targets` 分开建模；没有独立疾病靶点来源时 disease/intersection 必须为空，禁止从 compound set 自造交集。同一 canonical symbol 的不同 source record 保留多行，unique target count 与 lineage row count 分开；自动抽取不得冒充人工 adjudication。`disease_target_import` 在 task 创建时封存且不可后改：旧 `/api/network/analyze` 客户端导入固定为 `unverified_client_import`；`server_verified_raw_artifact` 只能由受支持的离线 raw artifact（当前为 Open Targets GraphQL 疾病数据或 `chembl_known_activity_v1` ChEMBL 成分数据）经服务端 SHA-256、operator-controlled trusted manifest 与服务端 parser 派生。客户端不得提交 records/hash/provenance/readiness/判定字段，multipart 外层也必须 strict allowlist；该中间态不得命名为 `verified`，且不得翻转 `formal_network_ready`。intersection 必须是一条/unique symbol 的服务端派生 row，并完整引用两侧匹配 lineage row IDs。
- 双侧 raw artifact 只建立冻结 snapshot，不自动授权下游网络结论。compound child 必须跳过 provider、机制链、PPI、通路与 enrichment，保持 `chains=[]`、`enrichment=null` 和明确的 network-assembly blocker；独立 validator、report 与 UI 必须共同执行该 snapshot-only 边界。
- 人工判定是与冻结快照平行的 append-only 审计流，不属于快照：projection 挂在结果响应信封而非 `NetworkAnalysisResult`，同一 lineage row 多次判定按 latest-wins 投影，`reviewer_id` 持久化但从不回投，且结构上不得翻转 `formal_network_ready`。冻结 lineage row 的 `adjudication_status` / `decision` 不由该审计流回写。「能记录判定」不等于「已有人判定」，更不等于科学有效。
- source-bound 装配门禁只证明「装配输入已封存」，不生成网络结论、不授权任何 writer、不翻转 `formal_network_ready`：`POST /api/network/result/{task_id}/assembly-plans` 产出不可变候选装配计划（确定性 plan_id + 协议/父子任务/双侧 artifact/冻结 lineage/判定快照全量绑定 hash），计划封存与判定流在 repository 锁内原子绑定（评估期间追加判定返回 `conflict`）；旧计划 append-only 默认不可执行，写前强制由下一条的消费原语执行。独立 validator `backend/scripts/validate_network_assembly_plan.py` 与 producer 零共享代码，改 plan 结构时必须让它对每一种篡改继续拒绝。
- writer 消费契约已落地（2026-09-06，契约 `docs/plans/2026-08-14-writer-consumption-contract-draft.md` status: approved，决策包 D1-D9 已拍板）：任何网络装配 writer 写产物前必须走 `POST /api/network/result/{task_id}/assembly-plans/{plan_id}/consume` 一次性消费原语——服务层按 D3 固定优先级预检（404 → 422 → R3 已消费/重放 → R4 superseded → R6 adjudication_changed → R7 broken_parent_link → 500 integrity），仓储层在同一临界区内重验可变通道（判定流元组、lineage 重算 hash、latest sequence、exactly-once）后才写输出+消费记录；去掉任一锁内守卫，`test_network_assembly_consumption_repo.py` 必须变红（变异验证过）。exactly-once 键为 `UNIQUE(task_id, owner_id, plan_id)`；同 writer+同 `output_sha256` 是 D5 幂等重放（返回原记录），否则 `plan_already_consumed`。JSON 后端响应标注 `backend_fidelity="preview"` 且输出/消费文件记录进程 token——检出异进程写入即 `multi_process_blocked` fail closed，JSON 永不承诺跨进程 exactly-once；消费记录容量 env `QIYAN_CONSUMPTION_RECORD_LIMIT`（默认 1000）触发 429。消费是审计不是推进：不回写冻结字段、`formal_network_ready` 恒 false，读取侧投影（`is_latest_plan`/`is_consumed`/`is_superseded_by`）与前端 `NetworkAssemblyPlanSummary.is_consumed` 两侧各有断言。canonical hash 由 `app/core/canonical_json.py` 供 service 与三仓储共用——改 canonicalization 必须三侧同步，独立 validator 的零共享副本另行同步。装配计算已落地（2026-09-11 拍板切片，`docs/plans/2026-09-11-writer-assembly-computation.md`）：consume 信封的 `chains`/`warnings` 是服务端从 plan `selected_intersections` 派生的，刻意不进 `output_sha256` hash 域（D5 重放语义不变）；装配链证据分级按行 provenance 判定——verified 行恒 `predicted`（known_activity 不上浮 experimental）、mock 行恒 `mock_inferred`，禁止改回按任务 `data_mode` 判（verified 导入任务的 data_mode 只是 provider 开关）；herb/formula 冻结载荷里没有就诚实留空，禁止从 mock 样例实体字典反查归属。
- omics 端点全部显式 opt-in，默认路径不可见：omics manifest 冻结导入 `POST /api/network/omics-import/verify`（`app/api/network.py`）客户端 manifest `extra="forbid"`，sha256/frozen_at/frozen_by/provenance 等封存字段只能服务端写；multipart strict allowlist（manifest/file/annotation_file）；同 accession 不同内容 409、同输入幂等。omics 投影（DEG 候选、证据 overlay）只挂结果响应信封（`?omics_verification=true&omics_accession=...` 显式 opt-in），不写入 `NetworkAnalysisResult`、不回写 lineage row，重算必须逐字节一致。独立 validator `backend/scripts/validate_omics_import.py` 与 producer 零共享代码（含 platform_annotation 第二 raw artifact 封存校验），改 omics 结构时必须让它对篡改继续拒绝。
- `omics_validated` 是唯一需要 HITL 的证据等级：`derive_chain_evidence_level` 永不产出该等级——跳过人工判定没有任何路径让边显示它；唯一升级路径是 `decision="omics_confirmed"` 的 append-only 判定，服务端在判定时刻重验机器条件（row/symbol 绑定、冻结快照存在、候选存在、阈值满足、数据集 Homo sapiens + AD），任一失败 fail closed。证据等级表与前端 `NetworkEvidenceLevel` / `getNetworkEvidenceLevelLabel`（`frontend/lib/api/network.ts`）两侧必须同步、两侧各有断言。客户端只能展示服务端投影传来的等级：`components/NetworkAnalysisClient.tsx` 源码里禁止出现 `"omics_validated"` 字面量（类型与 label 定义只在 `lib/api/network.ts`，`network-evidence-grading-ui.test.ts` 双向断言）。
- SQLite network-task repository 的锁按 canonical DB path 在单进程内共享；literature/chunk 仍是实例级锁。两者都不提供多 worker exactly-once；若引入多进程，必须先设计数据库 claim/lease 或等价原子协议。共享行上任何新增 read-modify-write 必须复用邻近方法已有的 CAS + 重试（`advance()`、`append_adjudication()` 即例），同文件已有的守卫就是需求；并发测试必须能观测到它声称覆盖的竞态——同进程两个 repository 实例共享 path lock，去掉守卫后仍会通过，必须显式制造交错并做变异验证。
- 写操作与其后用于刷新界面的读取必须分开捕获错误。共用一个 `catch` 会把已落库的写报成失败，在 append-only 审计域里会诱导重试并污染历史。
- 前端 fetcher 对非 2xx 一律抛 `ApiStatusError`（GET/POST 同规，`lib/api/*.ts` 全覆盖），UI catch 必须按错误类型分层：HTTP 状态码与服务端校验失败如实进文案，「请确认后端服务已启动」只允许出现在真网络故障（非 ApiStatusError）分支。该「错误折叠成 backend-down」家族在 2026-09-04/09-05 已回归三处（轮询 GET、network POST、rag POST），新增接口直接照 `network-input-boundaries.test.ts` / `rag-empty-state.test.ts` 的断言写。
- 跨端字段的位置必须两侧各有断言。后端放在响应信封、前端从嵌套快照读取时不会有任何报错，只会静默显示 0。
- 门禁全红时先排除工具链再改代码：pnpm 写绝对 symlink，仓库目录一旦移动，前端依赖全部悬空、前端门禁全红且与 diff 无关，需 `rm -rf frontend/node_modules && pnpm install --frozen-lockfile`；`.next` 缓存同样含迁移前绝对路径，目录移动后 dev/E2E 会出现与 diff 无关的间歇性失败（如 Playwright `networkidle` 超时），需一并 `rm -rf frontend/.next`；`pnpm build` 还会在 dev/build 间来回改写 `frontend/next-env.d.ts` 的 routes 类型路径，build 后树变脏时 `git checkout -- frontend/next-env.d.ts` 即可，不是代码问题。判断某条失败是否既有，用 `git stash` 清空改动后复跑确认，且复跑必须处于干净工具链（已重装依赖、已清缓存），不要凭印象归因。
- 启动外部进程时传结构化 argv，禁止拼接 `PowerShell -Command` 或 curl config/header 字符串；端口和凭证参数必须先校验。
- PDF 上传的真实文件 ID 绑定文献、完整文件名和字节 SHA-256，长度受限且旧文件不可覆写；旧 filename-only ID 保持可读兼容。JSON 文献与 chunk 更新按 canonical path 共享进程内锁，并原子替换文件；不承诺跨进程事务。解析/人工状态请求需传当前 `pdf_upload_id`，服务层与三种仓储重验 ID，过期返回 409，禁止把旧解析预览附在新文件上。
- PDF 流分两步：`POST /api/uploads/pdf` 只落盘并置 `pending`，要单独调 `POST /api/uploads/pdf/auto-parse` 才推进到 `parsed`/`failed`；upload endpoint 不做重解析。
- 前端测试套件（`frontend/tests/`，47 个测试文件）里有 23 个源码断言测试（`grep -l '\.tsx' frontend/tests/*.test.ts` 可列全，如 `pdf-upload-status`、`literature-detail-meta`、`client-section-consistency`、`page-shell-consistency`、`network-evidence-grading-ui` 等）用 `readFileSync` 对 `.tsx` 源码做正则断言；改页面壳、导航、可见 meta 文案或组件内嵌逻辑时最容易挂这批。
- 后端 mypy `strict=true` 仅作用于 `app/`（tests 排除）；`B008` 全局忽略，因为 FastAPI 用 `Body()`/`Form()`/`File()`/`Query()` 当默认值。
- eval 数据集是 50 题（`backend/data/evals/rag_ad_eval_questions.json`），不要按历史文档里的 20 题口径规划。
- 检索排序预期是调参产物，不是随手可修的失败：改 `services/retrieval/provider.py` 评分（字段加权 title=3/keywords=2/abstract=1、IDF 加权、多字术语词典）、`backend/data/retrieval/cjk_medical_terms.json` 或 `cross_lingual_terms.json` 会改变 citation 排序；`test_rag_service.py`、`test_rag_api.py`、`test_cross_lingual_eval.py` 的预期顺序对应 Track A/A+ 实测基线（MRR@5 0.268）——该基线对应 seed fixture 上的确定性检索，扩展语料只存在于 gitignored runtime state，不进测试语料，测试预期不受 v6 数字影响——调整时必须说明对基线的影响，不得为过测试而抹平排序。

## 已冻结的技术决策

项目当前采用小步可验证的内部预览边界：前端是 Next.js / React / Ant Design，后端是 FastAPI / Pydantic；默认使用本地 JSON seed、runtime state、可选 SQLite runtime backend 与 deterministic retrieval，不提前接入 Neo4j、Celery、Redis、MinIO、真实 LLM 或真实 embedding。上述重依赖保留为后续阶段的架构方向，而不是当前默认实现要求。（PostgreSQL/pgvector spike 已于 2026-09-23 按拍板移除。）

## 产品边界

- 病种仅特应性皮炎；用户仅医生/科研人员端；不替代诊断；不自训大模型
- 产品主轴是网络药理学科研项目；文献检索、PDF、RAG 与引用导出必须服务于研究项目、靶点、通路、网络边或科研 claim
- network task 必须携带明确表型、`Homo sapiens`、证据策略与查询日期；缺少来源版本、阈值或逐边人工判定时 `formal_network_ready=false`
- 所有 AI 输出必须带 "非诊断结论、需结合临床" 免责声明
- 视觉：青黛绿主色 `#0d9488`~`#14b8a6`，浅色产品端，Noto Sans SC

## 语言约定

文档/需求用简体中文。代码变量/函数/API 端点用英文，注释可中英混合。

## 当前开发原则

- 小步提交：先健康检查、配置、页面壳，再接真实业务能力
- TDD：行为代码先写测试，确认失败，再实现
- 不提前接入真实 AI API、Embedding 模型、Neo4j、支付等重依赖
- Secret 不进仓库，只写 `.env.example`
- 长期科研模块按阶段推进：先完成网络药理学协议、lineage、独立复算与小规模真实闭环；证据服务层按网络研究对象绑定；MVP-C 分子对接/分子动力学模拟目前只做 schema 概念预留
