# Handoff — privileged reviewer-identity audit HMAC（消费契约 §6.2 独立切片，2026-09-28）

## 背景与切片来源

同日第五次会话，执行「继续开发」（自主交接口径：选已拍板下一步、零新增拍板、门禁+走查+收工全口径）。D9=B validator 收口后（提交链 `d9b706d`→`32cf2ae`→`291eb1c`→`37cda09`），handoff 遗留清单中唯一可自主开工的已拍板工程切片即消费契约 §6.2 明示的「privileged reviewer-identity audit HMAC 独立切片」——与 D9=B 同款拍板先例（契约 approved 时明示「属于独立切片」即开工依据）；真实数据闭环需 operator 拍板数据源与 manifest、检索迭代/UX 循环由研究者发起，均不可自主开工。设计决策全部工程内拍板并记录在切片计划 §2，供研究者复核。

## 落地（TDD：收集期 ImportError 红 → 实现转绿）

1. **`app/core/audit_hmac.py`**（纯函数，core 层零 schemas 导入）：`QIYAN_ADJUDICATION_AUDIT_KEY` env 读取（缺省/空 = 审计关闭）、`adjudication_audit_hmac_v1` 链规则——`HMAC-SHA256(key, canonical({policy_id, task_id, sequence, prev_audit_hmac, event}))`；`sequence` 是全流下标（含未审计前缀），`prev` 恒取**紧邻前一事件**的 tag（流首/前事件未审计为 null），event 为 `model_dump(exclude={"audit_hmac"})` 全载荷（含 reviewer_id 与 omics 封存字段）。不沿用 `rag_export_integrity.py` 进程内密钥先例——审计流是持久态，重启必须仍可验证。
2. **schema**：`NetworkTargetAdjudication.audit_hmac: str | None`（64 hex；docstring 明示 server-private 永不投影）。
3. **两仓储 tagging**：共享 helper `protocols._tag_with_audit_hmac`（仓储层唯一无环共享点，防两 backend 链规则漂移），在 JSON 实例锁内 / SQLite CAS 重试环内调用——`prev` 必须指向实际落点状态，service 层计算会在「service 读 → repo 写」窗口链接到过期 prev。
4. **独立验证脚本 `scripts/validate_adjudication_audit.py`**（零共享：canonical 序列化与链派生脚本内重实现，循 validate_omics_import 先例）：`--state-json`/`--sqlite-db`（可并用）、`--task-id` 过滤、key 缺失 exit 2 fail closed；违规=tag mismatch / duplicate adjudication_id，无 tag 事件=unaudited 计数非违规；exit 0/1/2。
5. **公开面零暴露**：D9 证据包组包改为 `exclude={"reviewer_id", "audit_hmac"}`（服务端私钥数据不进公共包）；`NetworkTargetAdjudicationRecord` 逐字段构造天然不带；`adjudication_selection_sha256` 与 plan_id 派生不受影响（tagged/untagged 同流快照逐字节一致有测试钉死）。D9 validator 本体零改动（快照复算逐字段选取）。

## 测试（31 个新测试，基线 1002→1033+1skipped）

- `test_adjudication_audit_hmac.py`（14）：env 语义/派生确定性+输入敏感性（含 reviewer_id 覆盖）/无 key 逐字节不变/链式 tag+全流下标/跨实例持久化/跨 backend tag 逐字节一致/未审计前缀起段/快照与 summary 投影零暴露。
- `test_validate_adjudication_audit_script.py`（16）：接受（3 链、未审计前缀计数、零判定任务）+ 篡改矩阵（改 decision/改 reviewer_id/改 decided_at/改 adjudication_id/伪造 tag/删已审计事件/重排/剥 tag/重复 id/换 key）+ CLI 真实 JSON/SQLite 状态端到端与 fail-closed（exit 2）。
- `test_validate_network_assembly_plan.py`（+1）：审计开启下真实 API 全流（seal→consume→validator 接受）且证据包无 audit_hmac——红阶段实证：exclude 未加时该测试当场红（tag 进包），修正后绿。

## 关键事实与边界

- **审计证据≠访问控制**：读取/报告/plan/consume 路径零校验零感知（契约 §6.2：「公共 validator 与 writer 消费路径都不校验 reviewer identity」）；无 tag 事件是合法未审计前缀（key 中途启停均合法），脚本报 `unaudited` 计数。
- 密钥生成：`python -c "import secrets; print(secrets.token_hex(32))"`（任意非空 UTF-8 均可），不进仓库。
- PG 不涉及（2026-09-23 已移除）；JSON/SQLite 双 backend 均覆盖。
- `scripts/` 三个文件的既有 ruff format 漂移仍未动（非本切片，沿用 handoff 2026-09-28-writer-output-independent-validator 的记录）；本切片新增脚本已 format 干净。
- `_run_flow` 证据组包属测试基建即审计者打包规程定义，exclude 集合是其契约的一部分。

## 门禁与验证（收工口径，全绿）

- 后端：ruff format --check（166 文件）/ ruff check / mypy strict（**80 文件**，+1 core 模块）/ **pytest 1033 通过 + 1 skipped**（基线 1002 + 31 新测试；既有测试零破坏——schema 新字段对既有 dump 兼容）。
- 前端零改动认证：test 309/0 + typecheck + build 全绿；`next-env.d.ts` build 漂移已 `git checkout --` 恢复。
- smoke：isolated preview（`.tmp/trial-audit`，8010/3000）`Internal preview smoke passed.`，收尾 `-Stop` 后双端口确认释放。
- 变异式红证据：红阶段两文件收集期 `ModuleNotFoundError: app.core.audit_hmac`（与 D9 常量先例同形）；file C 兼容测试在 exclude 修正前行为红。

## /review 整改（同日，紧随 dc2d01d）

/review 对 dc2d01d 给出 0🔴/1🟠/2🟡/4⚪，本轮全部闭环（脚本+测试+文档，零 app 运行时 diff）：

- **🟠1 尾部截断 overclaim**：自洽链检不出删/剥**最后一个**已审计事件（尾部无后继 prev 可失配），而 plan §1/§2.3 与脚本 docstring 原声称「任何删/改/重排可检出」。三处文档勘误（plan §1/§2.3/§4/§5、脚本 docstring 新增 Detection boundary 段、AGENTS.md 子弹补边界句）+ 两个边界锁定测试（删尾 → ok 且 issues 空、剥尾 → ok 且 unaudited+1——把盲区钉成被测试证明的事实，防止后来者误改语义）+ 外锚立项（遗留 #4）。勘误注记：dc2d01d 提交信息「删已审计事件」矩阵口径实为「已审计区段**内部**事件」，提交信息不可改写，本节显式更正。
- **🟡1 tag 三态分诊**：tag 存在但非 64 字符串（如 123 / 63 位）原走 `not isinstance(tag, str)` 分支被静默计入 `unaudited`（尾部位置 ok=True 放行）。改为三态：缺省/null → unaudited（合法 legacy）；存在但非 64 字符串 → violation（producer 不可能形态即篡改）；64 字符串 → compare_digest。两个突变测试 TDD 红→绿。
- **🟡2 CJK 同规实证**：真实状态接受测试的覆盖事件 `reason` None→「人工复核」，`ensure_ascii=False` 两侧同规跨非 ASCII 字节从「构造上相同」变为「被测试证明」（防零共享副本静默漂移）。
- **⚪**：输入内重复 `task_id` 判违规（json/sqlite 后端互斥，同 id 双现即状态异常）；CLI `--state-json` 指向缺失文件（key 已设）exit 2 路径补测；`protocols.py` 模块 docstring 补「亦承载跨 backend 共享助手」句；如实记录：smoke 的 `network_adjudication` 因 mock 任务无可判定行条件性跳过——live 走查未触达带 tag 的 append 路径，该路径由 TestClient 套件覆盖，勿把「smoke passed」读成审计路径在线上走过。

### 整改后基线

- 后端门禁四项全绿：ruff format/check、mypy strict（80 文件）、**pytest 1039 通过 + 1 skipped**（1033 + 6 新测试：3 行为突变红→绿 + 2 边界锁定 + 1 CLI 覆盖）。
- 前端零改动认证：test 309/0 + typecheck + build 全绿。
- smoke 免跑：本轮零 `app/` 运行时 diff（独立脚本 + 测试 + 文档 + protocols docstring）。

## 遗留与下一个切片候选

1. **真实科研数据闭环**（产品主轴缺口，最高优先）：仍需 operator 拍板数据源与 trusted manifest，随后端到端走 verified 导入 → 判定 → seal → consume → 独立 validator 全链（本切片后可加验 audit 链）。
2. 检索质量下一轮迭代 / 前端 UX 新一轮循环（按既往节奏，由研究者发起）。
3. 小额技术债（非阻塞）：`scripts/` 三个既有文件 format 漂移；audit HMAC 密钥轮换/多 key 并验未设计（单 env 单 key，operator 事项）。
4. **审计链外锚（尾部截断检测，🟠1 整改后立项）**：自洽链的检测盲区已被边界测试锁定；候选方案为 plan seal 时绑定全流事件元组（涉 D4 policy v2 语义，会改 plan_id 派生）或独立 append 计数器文件（新存储面），需研究者拍板后方可开工。
