# Writer 输出独立零共享 validator 实现切片计划（D9=B 后续切片）

- date: 2026-09-28
- status: implemented
- 契约草案：`docs/plans/2026-08-14-writer-consumption-contract-draft.md`（status: approved）
- 决策包：`docs/plans/2026-08-14-writer-consumption-contract-decision-pack.md`（2026-08-16 D1-D9 全部拍板，D9=B：validator 后续切片，当前切片即为该后续切片）
- 前置切片：`docs/plans/2026-09-06-writer-consumption-primitive.md`（消费原语本体，预留输出信封最小 schema）、`docs/plans/2026-09-11-writer-assembly-computation.md`（装配计算，chains/warnings 刻意不进 `output_sha256` hash 域）
- 边界：不改动 producer（`app/services/`、`app/repositories/`、schemas 零改动）；不做 privileged reviewer-identity audit（owner_id 仅作为消费记录既有审计字段参与校验，不新增身份面）；不翻转 `formal_network_ready`；不做 PostgreSQL 活库 parity。

## 1. 切片范围

把 `backend/scripts/validate_network_assembly_plan.py` 的独立复算路径从「候选装配计划」扩展到「消费输出信封 + 消费记录绑定」，关闭决策包 D9 的遗留缺口。validator 与 producer 继续保持零共享代码（canonical hash 规则按 `qiyan_canonical_json_v1` 在脚本内独立维护）。

## 2. Evidence package 扩展（全部可选，向后兼容 plan-only 包）

| 新字段 | 类型 | 语义 |
|---|---|---|
| `outputs` | `NetworkAssemblyOutput[]` | 该 task 已持久化的输出信封（append-only，exactly-once 语义下实践中 ≤1 条） |
| `consumptions` | `NetworkAssemblyConsumptionRecord[]`（含 owner_id，owner-scoped 审计字段） | 消费记录流 |
| `output_payload` | `object` | writer 提交的原始输出载荷；提供时才重算 `output_sha256` |

## 3. 校验矩阵（每一条都必须能被独立拒绝）

### 3.1 输出信封（`outputs[*]`）

1. 信封钉死：`assembly_input_ready is True`、`formal_network_ready is False`（消费是审计不是推进）。
2. 信封 ↔ plan 绑定：`task_id` / `source_task_id` / `plan_id` / `plan_sequence` / `canonical_plan_input_sha256` 逐字段相等。
3. `output_id` 派生复算：`"assembly-output-" + canonical_sha256({task_id, source_task_id, plan_id, plan_sequence, canonical_plan_input_sha256, output_sha256})`。
4. `output_sha256` ↔ `output_payload` 重算（payload 在包内时）；chains/warnings 不在 hash 域（2026-09-11 拍板语义，validator 同样不得把它们算进去）。
5. 免责声明逐字节 `非诊断结论、需结合临床。`。
6. 装配链结构诚实性（复算-lite，不重跑 KEGG/分级器）：
   - `herb == ""` 且 `formula is None`（冻结协议无药材信息，诚实留空）；
   - `target_evidence_type ∈ {"predicted", "mock"}`（装配不产 known_activity/mixed）；
   - mock 行链 `evidence_level == "mock_inferred"`、predicted 行链 `evidence_level == "predicted"` 且 `evidence_refs == []`（不上浮 experimental / literature_supported）；
   - `related_entity_ids[0]` 必须是 plan `selected_intersections` 中某条的 `lineage_row_id`，且该链 `target` 等于该条 `canonical_symbol`、该条 `selected_disease_lineage_row_ids` ⊆ `related_entity_ids`、`selected_compound_lineage_row_ids` 与 `related_entity_ids` 有交。

### 3.2 消费记录（`consumptions[*]`）

1. `consumption_id` 形态 `^assembly-consumption-[0-9a-f]{64}$`（nonce 参与派生，不复算）。
2. 消费 ↔ plan 绑定：`task_id` / `plan_id` / `plan_sequence` / `canonical_plan_input_sha256` 逐字段相等。
3. 消费 ↔ 输出绑定：引用的 `output_id` 必须存在，且 `task_id` / `plan_id` / `plan_sequence` / `canonical_plan_input_sha256` / `output_sha256` / `writer_id` / `consumed_at` 与被引用输出逐字段相等。
4. `owner_id` 非空（owner-scoped 审计字段）。
5. exactly-once（D1）：`(task_id, owner_id, plan_id)` 三元组无重复。
6. 输出 ↔ 消费一一对应：输出无消费记录 = 完整性违反（消费原语原子同写）。

## 4. 测试与验收

- TDD：先在 `tests/test_validate_network_assembly_plan.py` 新增消费流测试（真实 API 流：seal → consume → 组包），确认对扩展字段 validator 暂不校验时变红，再实现转绿。
- 变异矩阵：每条校验规则至少一个 evidence 级篡改变体，断言拒绝且 issue 文本命中预期子串（核对红原因，不接受「反正红了」）。
- 向后兼容：既有 plan-only 测试零改动通过。

## 5. 验收口径

- 后端门禁四项全绿（ruff format/check、mypy strict、pytest 全量）。
- validator 脚本为离线工具、零 `app/` 运行时 diff → smoke 免跑（循 9-28 test-only 提交先例；唯一被改的 `backend/scripts/` 不进 app 运行路径，但被 pytest 直接导入测试）。
- 文档同步：`docs/current-state.md` 未完成边界、AGENTS.md writer 段、本计划 status。
