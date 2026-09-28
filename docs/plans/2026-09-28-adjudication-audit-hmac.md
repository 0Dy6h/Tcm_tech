# 切片计划 — privileged reviewer-identity audit HMAC（判定流服务端私有审计 HMAC）

- date: 2026-09-28
- status: implemented（2026-09-28 同日 TDD 落地；同日 /review 整改闭环：尾部截断边界勘误 + tag 三态分诊 + CJK 同规实证，见 handoff 整改节；交接同）
- 契约依据：`docs/plans/2026-08-14-writer-consumption-contract-draft.md`（status: approved）§6.2——「判定快照的服务端私有审计 HMAC 属于独立切片；公共 validator 与 writer 消费路径都不校验 reviewer identity，writer 契约不依赖、不暴露 reviewer identity」
- 拍板口径：与 D9=B 同款——契约 approved 时明示「属于独立切片」，handoff `2026-09-28-writer-output-independent-validator.md` 遗留清单列为候选且未标注外部前置，属唯一可自主开工的已拍板工程切片（真实数据闭环需 operator 拍板数据源；检索迭代/UX 循环由研究者发起）。

## 1. 解决什么问题

判定事件（`NetworkTargetAdjudication`）是 append-only 审计流，`reviewer_id` 持久化但从不投影。现有完整性机制都不能直接守护这条流本身：

- 装配计划绑定的 `adjudication_selection_sha256` 只覆盖 latest-wins 快照的五个投影字段，且只在「存在已封存 plan + 走消费校验」时才被复算；无 plan 时对流篡改无感知，且回滚场景下被取代的历史事件（include→exclude 的前者）从快照中消失，删改无感知。
- 持久化状态（runtime JSON / SQLite）可被带外直接改写（改 decision、删事件、换 reviewer_id），读取永不校验、无篡改证据。

本切片为这条流加服务端私有 HMAC 链：append 时在持久化事件上盖链式 `audit_hmac`，配合独立离线验证脚本，让已审计区段**内部**的删/改/重排/剥 tag 可被 operator 检出；**尾部截断（删/剥最后一个已审计事件）是自洽链的检测盲区**——尾部无后继事件的 prev 链接可失配，闭合它需要外锚（如 plan 绑定全流事件元组或计数器文件），属后续拍板候选（§5）。这是**审计证据**，不是访问控制，不改变任何读取行为。

## 2. 设计决策（工程内拍板，逐条记录供研究者复核）

1. **密钥来源 = env 显式 opt-in**（`QIYAN_ADJUDICATION_AUDIT_KEY`，非空即启用）：不用 `rag_export_integrity.py` 的进程内 `token_bytes` 先例——那个密钥短命是设计意图（重启作废导出 token），而审计流是长期持久态，重启后必须仍可验证。env 缺省/空 = 审计关闭，append 路径行为与今日逐字节一致（默认路径零变化，循真实 LLM/DB/组学端点同款 opt-in 纪律）。密钥不进仓库。
2. **tag 计算在仓储层临界区内，不在 service**：JSON repo 在实例锁内、SQLite repo 在 CAS 重试环内（`SELECT` 与 `UPDATE` 同锁体）取 observed 流的末事件 tag 作 `prev`。service 侧计算会在「service 读取 → repo 写入」窗口内读到过期 prev（SQLite 跨进程 CAS 胜出时尤甚），链即断。
3. **链式而非逐事件**：`audit_hmac = HMAC-SHA256(key, canonical({policy_id, task_id, sequence, prev_audit_hmac, event}))`。`sequence` = 追加时事件在全流中的下标（含未审计前缀），`prev` = 流中**紧邻前一事件**的 `audit_hmac`（流首或前事件未审计时为 null）。`event` 为事件 `model_dump(mode="json", exclude={"audit_hmac"})`——含 `reviewer_id` 与 omics 封存字段（这正是「reviewer-identity audit」的覆盖对象）。链式使已审计区段**内部**的删/改/重排/剥 tag（含 sequence 错位）可检出——事件被删或被剥 tag 后，后继事件存储的 prev 与新邻居不再一致；尾部事件无后继可失配，即 §1 声明的盲区。tag 存在但非 64 字符串是 producer 不可能产生的篡改形态，验证脚本判违规、绝不降级为 `unaudited`。
4. **未审计前缀诚实留白**：key 中途启用时，既有事件无 tag（`audit_hmac=null`），链从首个 tagged 事件起算；验证脚本把无 tag 事件报为 `unaudited` 计数而非违规（key 中途停用同理——停用后追加的事件无 tag，属合法部署选择）。审计覆盖 = 审计启用期间追加的事件。
5. **字段存放 = 事件本体**（`NetworkTargetAdjudication.audit_hmac: str | None = None`）：随事件一次原子写盘，无 sidecar 漂移面。公开面零暴露——`NetworkTargetAdjudicationRecord`（POST 响应投影）逐字段构造天然不带；latest-wins 快照/`_adjudication_summary`/omics overlay 全是逐字段投影，`adjudication_selection_sha256` 与 `plan_id` 派生不受影响（测试钉死：同流开关审计 seal 出同 plan_id）。
6. **验证 = 独立离线脚本** `backend/scripts/validate_adjudication_audit.py`，与 producer 零共享代码（canonical 序列化在脚本内独立重实现，循 `validate_omics_import.py` 先例）；从持久化状态（`--state-json` / `--sqlite-db`）直接重导链，key 取同 env。不接入 app 读路径、不接入公共 validator、不接入消费路径（契约 §6.2 边界）。
7. **canonicalization 共享 vs 零共享的分界**：app 侧 helper（`app/core/audit_hmac.py`，纯函数、dict 进 str 出）走 `canonical_json_payload` 共享原语（core 跨层共用先例）；脚本内零共享副本独立实现。改 canonicalization 时两侧同步的既有约束不变。
8. **PG 不涉及**：PG spike 已于 2026-09-23 移除，当前仅 JSON/SQLite 两 backend，均覆盖。
9. **core 层保持零 schemas 导入**：helper 纯函数化，pydantic 胶水（取 prev/sequence、`model_copy` 盖 tag）留在各仓储内四行；跨后端 tag 一致性由 json/sqlite 参数化测试钉死，胶水漂移即红。

## 3. 交付物

- `app/core/audit_hmac.py`：`AUDIT_POLICY_ID`（`adjudication_audit_hmac_v1`）、`AUDIT_KEY_ENV`、`load_audit_key()`、`derive_adjudication_audit_hmac()`。
- `app/schemas/network.py`：`NetworkTargetAdjudication.audit_hmac` 可选字段（docstring 明示 server-private、永不投影）。
- `app/repositories/network_tasks.py` / `sqlite_network_tasks.py`：`append_adjudication` 锁内/CAS 环内盖 tag。
- `scripts/validate_adjudication_audit.py`：独立验证脚本（违规：tag mismatch / duplicate adjudication_id；`unaudited` 计数非违规；exit 0/1/2）。
- `.env` 文档：仓库无 `.env.example` 先例文件，密钥生成与语义写入本计划与 handoff（`python -c "import secrets; print(secrets.token_hex(32))"`）。

## 4. 验收标准（TDD，测试先行）

1. 未设 env：append 持久化事件 `audit_hmac is None`；POST 响应 JSON 键集合不含 `audit_hmac`；行为与今日一致。
2. 设 env：json/sqlite 两 backend 追加事件的持久化 tag 为 64 位 hex；同流两事件 tag 不同且链式可复导；同输入跨 backend tag 逐字节一致。
3. 快照/plan 派生不变性：`_adjudication_latest_snapshot` 对 tagged/untagged 同流输出逐字节一致；D9 validator 全流（evidence 组包→consume→validator 接受）在审计开启下依旧通过。
4. 独立脚本：真实流（JSON 与 SQLite）accept exit 0；篡改矩阵逐项 exit 1 且命中预期 issue 子串——改 decision / 改 reviewer_id / 改 decided_at / 改 adjudication_id / 改 audit_hmac 本身 / 删已审计事件 / 交换两事件 / 换 key 验证 / 非法配置 exit 2；无 tag 前缀报 `unaudited` 不报违规；tag 存在但非 64 字符串判违规；输入内重复 task_id 判违规；删尾/剥尾两个边界用例如实锁定（ok=True + unaudited 计数），把 §1 盲区钉成被测试证明的事实；零判定任务通过。真实状态接受测试的覆盖事件携带 CJK `reason`（「人工复核」），使两侧 `ensure_ascii=False` 同规跨过非 ASCII 字节被实际证明。
5. 红阶段实证：helper/schema/脚本未实现时新测试收集期 ImportError；行为断言红因内建（tag 缺失、脚本不可导入）。
6. 门禁：后端四项全绿；前端零 diff 认证；smoke 必跑（本切片有 `app/` 运行时 diff）。

## 5. 明确不做

- 不让任何 API 响应、报告、装配计划、消费记录、D9 validator 输入包含 `audit_hmac`（契约：公共路径不依赖不暴露）。
- 不做读取时校验/fail closed 读取（审计证据 ≠ 访问控制；读取永不修复的既有规则不动）。
- 不做外锚（尾部截断检测）：自洽链无法检出删/剥最后一个已审计事件；外锚（plan 绑定全流事件元组或独立计数器文件）属后续拍板候选，见 handoff 遗留。
- 不做密钥轮换协议、多 key 并验、HSM；单 env 单 key，轮换属后续 operator 事项。
- 不动 `rag_export_integrity.py` 既有进程内密钥语义。
