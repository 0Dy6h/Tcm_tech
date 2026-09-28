# Handoff — writer 输出独立零共享 validator（D9=B 后续切片，2026-09-28）

## 背景与当日上下文

本日第四次会话，执行「继续优化/开发」（自主交接口径：选已拍板下一步、零新增拍板、门禁+走查+收工全口径）。切片来源：writer 消费契约决策包 D9=B（2026-08-16 拍板「validator 后续切片」），在 `docs/current-state.md` 未完成边界中明示为遗留——候选清单里真实数据闭环需 operator 拍板数据源与 manifest、检索迭代与 UX 循环均无 pre-approved plan，故 D9 validator 是唯一可自主开工的已拍板切片。同日时间线：network 拆分收口 → façade 私有面收缩（6532ca8）→ /review 整改（1896cac）→ 本切片。另有一笔独立 docs 提交 d9b706d（AGENTS.md 补 pwsh 宿主注记，/init 遗留）。

## 落地（TDD：篡改矩阵先红后绿）

1. **evidence 包扩展**（`backend/scripts/validate_network_assembly_plan.py`，全部可选、plan-only 包向后兼容）：`outputs`（输出信封）、`consumptions`（消费记录，含 owner_id——owner-scoped 审计字段，privileged 身份审计仍另切片）、`output_payload`（writer 原始载荷，提供时才重算 hash）。
2. **输出信封校验**：`assembly_input_ready=True`/`formal_network_ready=False` 钉死；信封↔plan 五字段绑定；`output_id` 派生复算（6 字段 canonical hash）；`output_sha256`↔payload 重算（**chains/warnings 不进 hash 域**，与 2026-09-11 拍板语义双侧一致）；免责声明逐字节；装配链诚实性——herb 恒空/formula 恒 null、`target_evidence_type∈{predicted,mock}`、mock 链恒 `mock_inferred`、predicted 链恒 `predicted` 且 `evidence_refs=[]`（不上浮 experimental/literature_supported）、`related_entity_ids[0]` 必须引用 plan selected intersection 且 target/disease 子集/compound 交集全对上。
3. **消费记录校验**：`consumption_id` 形态（nonce 参与派生故不复算）；消费↔plan 四字段绑定；消费↔被引用输出七字段绑定；owner_id 非空；exactly-once 三元组 `(task_id, owner_id, plan_id)` 无重复（D1）；输出↔消费一一对应（消费原语原子同写，孤儿输出即完整性违反）。
4. **测试**（`tests/test_validate_network_assembly_plan.py`，4→7——勘误：32cf2ae 提交信息误写为「6→9」，原文件为 4 个测试、本切片 +3）：`_build_evidence` 重构出 `_run_flow`（返回 child_id/plan_id）；新增消费流组包（真实 API：seal → consume 201 → 仓储取记录）+ 接受测试 + 15 项篡改矩阵（每项断言预期 issue 子串命中——红原因内建断言，非「反正红了」）+ plan-only 兼容测试。红阶段实证：validator 未实现时篡改矩阵全数漏放（accept 测试绿仅证明组包可用）。

## 关键事实

- producer 零改动：`app/services/`、`app/repositories/`、schemas 全未触；validator 是离线脚本，仅被测试导入，不进 app 运行路径。
- `scripts/` 不在后端门禁范围（format/check 只查 `app tests`）——本次顺手多查发现 3 个既有 scripts 格式漂移（seed_pubmed_corpus / validate_network_target_lineage / validate_omics_import），**非本切片未动**；只 format 了本切片触达的 validator。
- canonical hash 规则继续在脚本内零共享维护（与 `app/core/canonical_json.py` 的 `qiyan_canonical_json_v1` 逐字节同规），改 canonicalization 时三侧+本脚本同步的约束不变。

## 门禁与验证（收工口径，全绿）

- 后端：ruff format --check（163 文件）/ ruff check / mypy strict（79 文件）/ **pytest 998 通过 + 1 skipped**（基线 995 + 3 新测试）。
- 前端（零改动认证）：test 309/0 + typecheck + build 全绿；`next-env.d.ts` 无漂移。
- smoke 免跑：零 `app/` 运行时 diff（循 9-28 test-only 提交先例）。

## 遗留与下一个切片候选

1. **真实科研数据闭环**（产品主轴缺口，最高优先）：需 operator 拍板数据源与 trusted manifest（Open Targets 真实 artifact 或 ChEMBL known_activity），随后端到端走 verified 导入 → 判定 → seal → consume → 独立 validator 全链。
2. privileged reviewer-identity audit HMAC（消费契约明示另切片）。
3. 检索质量下一轮迭代 / 前端 UX 新一轮循环（按既往节奏，由研究者发起）。
4. 小额技术债（非阻塞）：`scripts/` 三个文件的 ruff format 既有漂移；`docs/current-state.md` 的 PG parity 边界句已随本切片理顺（PG spike 2026-09-23 移除）。

## /review 整改（同日，紧随 32cf2ae）

/review 对 32cf2ae 给出 0🔴/3🟠（含 1 项文档事实错误）/2🟡/3⚪，本轮全部闭环（TDD 红→绿）：

- **🟠1 篡改矩阵覆盖缺口**：15 突变只覆盖约 22 条规则中的 11 条，违反切片计划 §4 自己的验收标准。补 16 个突变（assembly_input_ready 钉死 / 信封↔plan task_id·plan_id·source_task_id / formula 恒 null / target_evidence_type 越档 / predicted 链 evidence_refs 非空 / chain target≠selection symbol / disease 子集缺失 / compound 交集缺失 / 计数（见 🟠2）/ consumption_id 形态 / 消费↔plan plan_sequence / owner_id 空 / 消费↔输出 writer_id·consumed_at），矩阵 15→31，逐项断言预期 issue 子串。红阶段核对：15 个既有规则突变当场全绿（证明既有规则真实会红），唯一红是计数突变——红因精准。
- **🟠2 链数量完备性**：per-chain 校验只覆盖「存在的链是否诚实」，「应有的链是否都在」失明——2026-09-11 派生规则确定性可复算期望链数 Σ per-selection `len(selected_compound_lineage_row_ids)`。新增计数断言 `output chain count N does not match the count M derived from plan selections`，封住「少产链」类 producer 回归（删链突变 TDD 红→绿）。
- **🟠3 文档事实错误**：32cf2ae 提交信息与 handoff 均误写测试计数「6→9」（实际 4→7）。本节即勘误记录；提交信息不可改写，整改提交信息显式更正。
- **🟡4 可选扩展字段畸形包崩溃**：`outputs`/`output.chains` 结构错误原先以 ValueError 炸栈退出（main 只 catch OSError/JSONDecodeError），审计者拿不到 issue 清单。改为 `_validate_outputs_and_consumptions` 内 try/except ValueError → `issues.append(str(exc))` 降级为干净 INVALID（缺失 chains / outputs 非数组两形态有测试锁定）。
- **🟡5 孤儿 `output_payload` 静默忽略**：只给 payload 不给 outputs 时早退、重算从未发生且无提示。新增 issue `output_payload provided without outputs; sha256 recompute skipped`。
- **⚪**：`consumed_output_ids` 去掉两处冗余 `str()` 强转（add 位本就 isinstance-str 守卫）；`test_validator_ignores_...` 改名 `test_validator_still_accepts_plan_only_packages`；模块 docstring 明示 `warnings` 文案刻意不做内容校验（producer copy，非 integrity binding）。

### 整改后基线

- 后端门禁四项全绿：ruff format/check、mypy strict（79 文件）、**pytest 1000 通过 + 1 skipped**（998 + 2 新测试；矩阵 15→31 突变在既有测试函数内）。
- 前端零改动认证：test 309/0 + typecheck + build 全绿（零前端 diff）。
- smoke 免跑：仍零 `app/` 运行时 diff（validator 离线脚本 + 测试 + 文档）。
