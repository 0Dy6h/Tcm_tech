# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## CodeGraph enforcement (MANDATORY)

**This project has CodeGraph MCP server configured. Use it FIRST for all structural queries.**

### Strict rules

1. **Never `Grep` for symbol names, function definitions, class declarations, or imports.** Use `codegraph_search` instead — it's faster and returns AST-verified results with signatures.
2. **Never `Read` multiple files to trace call chains.** Use `codegraph_context` (focused context) or `codegraph_explore` (multi-symbol source view) — one call returns what grep + 5× Read would.
3. **Trust codegraph results.** They come from tree-sitter AST parse. Do NOT re-verify with `Grep` or `Read` — that wastes tokens and is less accurate.
4. **For "how does X work" questions**: call `codegraph_context` first, then `codegraph_explore` for the returned symbols. Do NOT spawn a sub-agent or grep loop.

### When codegraph is NOT appropriate

- Literal text search (log messages, Chinese copy, comments)
- After you already have a file open and need a few adjacent lines
- String constants or regex pattern matching

### Decision tree

```
"Where is function X?" → codegraph_search
"What calls X?" → codegraph_callers
"What does X call?" → codegraph_callees
"What breaks if I change X?" → codegraph_impact
"Show me X's implementation" → codegraph_node or codegraph_explore
"How does RAG pipeline work?" → codegraph_context + codegraph_explore
"Find '非诊断结论' string" → Grep (literal text)
"Read app/main.py lines 50-60" → Read (specific range)
```

### Project-specific entry points

Query the actual symbols under these files instead of relying on a static symbol list, which drifts as slices are refactored:

- Backend RAG/export: `backend/app/services/rag.py`, `rag_export_integrity.py`, `rag_docx.py`
- Backend PDF: `backend/app/api/upload.py`, `backend/app/services/upload.py`, `backend/app/services/pdf_storage.py`, literature/chunk repositories
- Backend network: `backend/app/api/network.py`, `backend/app/services/network.py`, `*network_tasks.py`
- Frontend clients: `frontend/lib/api/client.ts`, `literature.ts`, `rag.ts`, `network.ts`
- Frontend pages: `frontend/app/literature/`, `frontend/app/rag/`, `frontend/app/network/`

### Index status check

If any codegraph call returns "not initialized", immediately run:
```bash
codegraph init -i
```

Then retry. Do NOT fall back to `Grep` + `Read`.

---

## Project identity

Qiyan Nexus — 面向特应性皮炎（AD）医生与科研人员的中医药窄领域网络药理学自动化科研辅助平台（ADR-0017 当前契约基线；ADR-0018 为组学策略方向演进）。仅医生/研究人员端，**不面向 C 端患者**，**不替代诊断**。所有 AI 输出必须附带免责声明 `非诊断结论、需结合临床。`

仓库当前处于可运行的内部预览阶段：MVP-A 证据工作台已完成收尾；网络药理学具备 mock/live 任务壳、三集合 lineage，以及离线 Open Targets 疾病侧与 `chembl_known_activity_v1` 成分侧的双侧 raw-artifact engineering provenance；owner-scoped 逐行人工 adjudication 与 source-bound 候选装配计划已落地；尚无真人判定记录，`formal_network_ready` 仍为 false。后端默认用本地 JSON seed + runtime state + deterministic retrieval 跑 RAG，PDF 解析支持 `pypdf` 文本预览，无法抽取时回退到文件级占位说明。真实 LLM、真实 embedding、Neo4j、Celery、Redis、MinIO、对象存储和支付均不进入默认路径；只允许按 `docs/current-state.md` / ADR 中的显式 opt-in 边界推进。（PostgreSQL/pgvector spike 已于 2026-09-23 按拍板移除，结论存档于 `docs/evaluations/2026-06-05-postgresql-pgvector-spike.md`。）

## Commands

### Backend (Python 3.11+, FastAPI)

本机 canonical 命令是 Windows PowerShell，venv 为 `backend/.uv-test-venv`：

```powershell
# First-time install
cd backend
py -3.11 -m venv .uv-test-venv
& .\.uv-test-venv\Scripts\python.exe -m pip install -U pip
& .\.uv-test-venv\Scripts\python.exe -m pip install -e ".[dev]"

# Dev server (http://127.0.0.1:8010)
& .\.uv-test-venv\Scripts\fastapi.exe dev app/main.py --port 8010

# Tests
& .\.uv-test-venv\Scripts\python.exe -m pytest -q

# Single test file / single test
& .\.uv-test-venv\Scripts\python.exe -m pytest tests\test_rag_service.py -q
& .\.uv-test-venv\Scripts\python.exe -m pytest "tests\test_rag_service.py::test_name" -q

# Lint / format / type-check (must all be green before commit)
& .\.uv-test-venv\Scripts\python.exe -m ruff format --check app tests
& .\.uv-test-venv\Scripts\python.exe -m ruff check app tests
& .\.uv-test-venv\Scripts\python.exe -m mypy app
```

### Frontend (Next.js 16 + React 19 + Ant Design 6, pnpm)

```bash
cd frontend && pnpm install
cd frontend && pnpm dev            # http://localhost:3000, expects backend at 127.0.0.1:8010
cd frontend && pnpm test           # node --import tsx --test tests/*.test.ts
cd frontend && pnpm typecheck      # next typegen && tsc --noEmit (includes tests/)
cd frontend && pnpm build          # next build --webpack

# Single test file
cd frontend && node --import tsx --test tests/literature-api.test.ts

# Override API base
$env:NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8010"; cd frontend; pnpm dev

# E2E (A4 — Playwright). One-time host setup: pnpm exec playwright install chromium
# plus sudo install-deps for libnspr4/libnss3/etc. See frontend/e2e/README.md.
cd frontend && pnpm e2e            # spins up backend + frontend webServer, runs e2e/*.spec.ts
```

## Architecture

### Backend layering (strict)

`app/api/*.py` (FastAPI routers under `/api/...`) → `app/services/*.py` (business logic, disclaimer composition, ranking) → `app/repositories/*.py` (JSON/runtime storage plus explicit SQLite backend behind protocols) → `app/schemas/*.py` (Pydantic models). Don't bypass layers — routers should not read storage directly, services should not import `FastAPI`.

Routers are wired in `app/main.py`. CORS is restricted to `localhost:3000` / `127.0.0.1:3000`, methods `GET, POST` only — adding a `DELETE` or `PUT` route requires editing the middleware.

### Sample-data substrate

Authoritative mock data lives in `backend/data/`, while runtime mutations are written under `backend/data/runtime/`:
- `literature/sample_ad_literature.json` — seed literature records (zh + en)
- `literature/sample_ad_chunks.json` — seed chunk-level evidence
- `evals/rag_ad_eval_questions.json` — 50-question AD eval set with expected literature/chunk hits, forbidden phrases, required disclaimer
- `runtime/literature_state.json` / `runtime/*` — runtime literature, chunk, PubMed sync, PDF metadata, and network task state; gitignored

Repositories bootstrap from seed JSON and write runtime state on update (e.g. `update_pdf_metadata`, `update_pdf_parse_status`). Runtime state can use JSON by default or SQLite via `QIYAN_STATE_BACKEND="sqlite"`. Do not commit runtime state or uploaded PDFs as fixtures unless a task explicitly asks for new source data.

### RAG pipeline (deterministic default)

`app/services/rag.py` does keyword tokenization with Chinese-char-per-token + alias / cross-lingual bridge terms. Scoring runs against `title + snippet + abstract + keywords + evidence_tags + related_entity_ids + chunk text + chunk evidence_tags + chunk related_entity_ids`. Formula/herb names from `backend/data/network/` are injected as entity tokens so queries like `消风散` / `黄芪` can match linked literature without requiring the literal AD disease token. A single `肠` character is intentionally not a gut-axis alias; keep `肠道` / `肠-脑` for valid gut-axis bridge terms. Language detection picks a `preferred_source_type` tie-breaker (zh → `cn_literature`, otherwise `pubmed`). Confidence is a constant per source type, **not** computed.

RAG export endpoints are `POST /api/rag/answer/export` for Markdown and `POST /api/rag/answer/export/docx` for Word `.docx`. `/api/rag/answer` signs its canonical response fields with a server-side HMAC `integrity_token`; both export endpoints reject missing, incomplete, or modified payloads. DOCX rendering lives in `app/services/rag_docx.py`, uses only the standard library, preserves answer newlines with `<w:br/>`, and strips XML-illegal control characters before writing text nodes. The signing key is process-local, so payloads issued before a restart are intentionally invalid afterward.

Default path is `deterministic` provider + `keyword` retrieval. Optional providers / retrieval backends (`mock_claude`, `opencode_go`, `anthropic`, `vector`, `hybrid`, BGE/BGE-M3 embedding) are explicit env opt-ins for local smoke or spike work only; do not flip defaults without an ADR / governance decision.

Two non-obvious invariants enforced by tests:
1. Every `citations[*].literature_id` returned by `/api/rag/answer` must resolve via `/api/literature/{id}` (`test_rag_literature_contract.py`).
2. Responses always carry the disclaimer string; the eval scans for forbidden phrases. Don't soften or rewrite `DISCLAIMER` in `services/rag.py`.

### PDF upload → RAG citation flow

`POST /api/uploads/pdf` (multipart) writes the file under `UPLOAD_STORAGE_DIR` (default `backend/uploads/`, gitignored) and sets literature metadata to `pdf_parse_status=pending`. **The upload endpoint does not do heavy parsing** — call `POST /api/uploads/pdf/auto-parse` separately to transition `pending → parsed`/`failed`. Auto-parse builds `pdf_parse_result`: text-layer PDFs use `pypdf-text-preview`; scanned/empty/unreadable PDFs fall back to `file-metadata-placeholder`. On success the parser writes an `uploaded_pdf` chunk into runtime state so RAG retrieval can cite it; on failure it only flips status and bumps `parse_attempt_count`.

Stable upload IDs are derived from `literature_id + file_name` so `GET /api/uploads/pdf/{pdf_upload_id}` is idempotent.

### Frontend test setup

`pnpm test` runs `node --import tsx --test tests/*.test.ts` — the `tsx` loader compiles TypeScript on the fly so tests import directly from `lib/*.ts` without a build step. Tests use only `node:test` + `node:assert/strict` (no Vitest, no jsdom). Four tests (`pdf-upload-status`, `literature-detail-meta`, `client-section-consistency`, `page-shell-consistency`) read `.tsx` files via `readFileSync` and assert against the source text — when you change page shells, navigation, or visible metadata copy in `app/` or `components/`, these regex assertions are the things most likely to fail.

`pnpm typecheck` (`tsc --noEmit`) covers `tests/**` as well; the fetch-mock pattern in `evals-api.test.ts` / `literature-detail-api.test.ts` uses explicit `as typeof globalThis.fetch` casts because `node:test` has no built-in fetch mocking.

Pages: `/` `/literature` `/literature/[id]` `/rag` `/evals/rag-ad` `/compliance` `/network`. Shared shell helpers live in `lib/ui/` (`surfaces`, `states`, `card-meta`, `status-card`) and `lib/compliance-page.ts`; source-regex tests such as `page-shell-consistency.test.ts` and `client-section-consistency.test.ts` lock these contracts. Playwright e2e specs cover the main literature/RAG path, internal preview path, network graph keyboard flow, and literature data-source switching.

### Module roadmap (ADR-0010)

MVP-A (evidence workbench) is complete for internal preview. MVP-B network pharmacology has a mock/sample-data path plus offline Open Targets disease verification (`POST /api/network/disease-import/verify`, `NETWORK_OPEN_TARGETS_MANIFEST_PATH`) and offline ChEMBL compound verification (`POST /api/network/compound-import/verify`, `NETWORK_CHEMBL_MANIFEST_PATH`). The compound path creates an immutable owner-scoped child, persists `source_task_id`, and returns a snapshot-only result without provider, PPI, pathway, or enrichment outputs; raw bytes persist under `NETWORK_RAW_ARTIFACT_DIR`. MVP-C molecular docking / MD remains schema-only (`protein`, `ligand`, `simulation_task` etc.) with no router/service/repository and no real computation.

## Conventions

- **Language**: docs and user-facing copy in Simplified Chinese; code identifiers, API paths, file names in English; comments may mix.
- **Disclaimer string**: `非诊断结论、需结合临床。` is load-bearing — referenced by tests, eval, and frontend assertions. Keep it byte-identical.
- **Visual tokens**: 青黛绿 `#0d9488` ~ `#14b8a6` as primary; light-mode product surfaces; Noto Sans SC. Existing pages use inline styles with `clamp(20px, 4vw, 48px)` page padding — match that rather than introducing a new styling layer mid-slice.
- **Lint/type gate**: every backend change must leave `ruff format --check app tests`, `ruff check app tests`, `mypy app`, and `pytest -q` all green. `[tool.mypy].strict = true` is enforced on `app/`; tests are excluded. `B008` is globally ignored because FastAPI uses `Body()` / `Form()` / `File()` / `Query()` as defaults.
- **E2E gate (A4)**: `pnpm e2e` is the third frontend gauntlet stage but is NOT part of the per-commit gauntlet — it requires `playwright install chromium` + system libs (sudo). Run it before closed-beta walkthroughs and CI; treat failures as branch-level blockers, not commit-level.
- **Secrets**: only `.env.example` is committed. `.env*` and `backend/uploads/` are gitignored.
- **Access control (A2)**: `QIYAN_ACCESS_TOKENS` env (comma-separated allowlist) gates every API path except `/health` and CORS preflight. Empty value = open (dev default); set value requires `X-Access-Token`. Browser code must never receive or forward this token. In protected deployments nginx authenticates each reviewer, overwrites `X-Qiyan-Reviewer`, and injects the shared backend token; middleware trusts reviewer identity only after token validation and stores it in request state. Keep backend port 8000 loopback-only.
- **Object ownership**: network tasks carry `owner_id`; repositories and services must query/advance by `task_id + owner_id`. Foreign and legacy ownerless tasks return 404 without state changes. The report endpoint observes state only: queued/running → 202, completed → 200, failed → 409. PDF/uploaded-chunk/RAG ownership is not implemented yet; do not describe the current preview as safe for mutually private uploads.
- **Raw-artifact trust boundary**: uploaded bytes and client metadata are one attacker-controlled trust domain. Grant `server_verified_raw_artifact` only after server-side raw-byte hashing, lookup in an operator-controlled SHA-keyed manifest, strict multipart/GraphQL allowlists, bounded non-chunked request framing, server parsing, and atomic content-addressed persistence. Hash consistency is not release correctness, biological meaning, or human adjudication; keep `formal_network_ready=false`.
- **SQLite concurrency**: network-task repositories sharing one canonical DB path share a process-level `RLock`; literature/chunk repositories currently use instance-level locks. Failed database operations rollback. None of these locks protect multiple Python workers; require a database claim/lease design before claiming cross-process exactly-once transitions.
- **TDD slice cadence**: per `AGENTS.md`, write failing test → implement → refactor; commit small vertical slices rather than batched refactors.

## Frontend skill routing

This project has three relevant user-level skills installed in `~/.claude/skills/`. Route between them as follows — do NOT default to whichever skill the prompt verb sounds like.

- **`web-design-guidelines`** (vercel-labs/agent-skills) — **always use** when reviewing or auditing any file under `frontend/app/**` or `frontend/components/**`, or when the user says "review my UI / check a11y / audit design / check accessibility". It fetches the latest rules and emits `file:line` findings. Required gate before any frontend PR.
- **`frontend-design`** (anthropics/skills) — use when creating a NEW page under `frontend/app/` or a NEW component under `frontend/components/`. **Tokens are non-negotiable**: primary `#0d9488 ~ #14b8a6`, font `Noto Sans SC`, light-mode surfaces, page padding `clamp(20px, 4vw, 48px)`, disclaimer `非诊断结论、需结合临床。` byte-identical. The skill's "pick a BOLD aesthetic direction" step is overridden by these locked brand tokens — do NOT switch to brutalist / maximalist / dark-mode / alternative typography on this project. Treat it as "creative within the locked palette" rather than "creative".
- **`design-taste-frontend`** (Leonxlnx/taste-skill v2) — **suppressed for this project**. Its own description says it's for "landing pages, portfolios, and redesigns. Not dashboards, not data tables, not multi-step product UI." Qiyan Nexus is exactly the latter (文献库 / RAG / PDF / eval / compliance pages). Do NOT invoke it for anything inside `frontend/`. The only legitimate use would be a standalone marketing/landing page under a clearly separate path (e.g. `frontend/app/(marketing)/`); confirm with the user before activating.

Existing pages use inline styles in the established pattern — match that surface (`lib/ui/surfaces`, `lib/ui/states`, `card-meta`, `status-card`) rather than introducing a new styling layer. The four shell-consistency tests (`page-shell-consistency`, `client-section-consistency`, `pdf-upload-status`, `literature-detail-meta`) lock visible copy and structure via regex on the .tsx source — run them after any frontend skill-assisted change.

## Where to look for context

- `AGENTS.md` — project map, frozen tech decisions, current dev principles
- `CONTEXT.md` — domain glossary (AD, GBS-Axis, Evidence-Chain, etc.); use these terms verbatim
- `README.md` — full API examples (curl) for every endpoint currently implemented
- `docs/adr/` — ADRs covering literature indexing strategy, model routing, embedding split, storage/async future direction, frontend baseline, module roadmap, external LLM data flow, and real-LLM enablement
- `docs/handoffs/` — recent session handoffs; the newest is the most reliable "what's actually done" source
- `docs/plans/` — slice plans (literature data slice, PDF→RAG slice, RAG eval slice)
