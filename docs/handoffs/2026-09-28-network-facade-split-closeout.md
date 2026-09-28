# Handoff — network service 拆分收口、AST 保真度审查与 late-binding 守护（2026-09-28）

## 背景

2026-09-24 12:13 日间会话把 `backend/app/services/network.py`（2554 行单文件）拆分为 façade + 按域子模块，但**中途遗留、未跑门禁**：`network.py` 已改成 re-export 外壳，7 个子模块落盘，工作树悬空两天。2026-09-28 会话按「继续开发」（自主交接口径：选已拍板下一步、零新增拍板、门禁+走查+收工全口径）收口，随后同日完成 /review 严格审查与整改。

关键事实：日间遗留改动**没有跑过任何门禁**——ruff 抓出 4 个真实 F821 未定义名（子模块裸用了搬走后未接回的函数），全部落在可执行主路径（建任务、verified 导入、装配门禁、`_advance_record` 证据分级），运行时必炸。重构类变更在「移动完成」的同一会话内必须跑门禁，这条流程约束是本次的实际防线。

## 落地（3 笔提交，全部已推送）

| 提交 | 内容 |
|---|---|
| `adf711c` | style: ruff 0.15 格式规则漂移修正（`app/main.py`、`tests/test_health.py` 顶层双空行；HEAD 既有漂移，venv 内 ruff 0.15.14 触发，与拆分无关，单独提交保证每个提交点门禁皆绿） |
| `0cabc23` | refactor: 拆分本体——`network.py` 收敛为兼容 re-export（`app/api/network.py` 与测试导入零改动），实现移入 `network_common`/`network_imports`/`network_lineage`/`network_tasks`/`network_assembly`/`network_adjudication`/`network_queries` 七子模块；补齐 4 处 F821 + ruff --fix；AGENTS.md 同步 façade 结构约束 |
| `57b0718` | test: late-binding 不变量守护落地（审查整改）——详见下节 |

## 审查方法论与结论（/review，2026-09-28）

重构审查核心是**移动保真度**，本次用 AST 语义级比对实测：

- 旧 monolith 69 个顶层符号 vs 新 8 文件：**50 个逐字一致（AST-identical）、19 个经归一化证明为纯 `_facade.` late-binding 改写、0 丢失、0 重复定义、仅新增 `__all__`**。归一化方法：剥离函数体内新增的 `from app.services import network as _facade` 语句 + 把 `_facade.` 限定还原为裸名后再比对 AST。
- monkeypatch 面实测：全仓只有 `_get_repository`/`uuid4`/`select_network_provider` 三个名字在 façade 上被 patch（12 处）；grep 证实兄弟模块无裸调用、无模块级 façade 导入（无环）。
- 消费方盘点：app 层只走 façade，测试走 façade + 既有独立子模块，无新耦合。
- 结论：0 🔴 / 1 🟠（不变量无自动守护）/ 2 🟡（规则未成文、私有面固化）/ 1 ⚪（docstring 空白损坏）。

## 整改（57b0718，TDD + 变异验证）

新增 `backend/tests/test_network_facade_late_binding.py` 五断言，三层防护：

1. **静态扫描**：兄弟模块顶层禁止任何形式的 façade 导入；三个可 patch 名禁止裸调用（必须 `_facade.<name>`）。
2. **行为断言**：patch façade 后驱动真实入口证明生效——sentinel repo 经 `get_network_analysis_task`、固定 uuid 经 `_create_queued_network_task`（断言 `task_id == "network-bada55cafe"`）、包装真实 selector 经 `_advance_record` 完整 mock 管线。
3. **变异验证三组全红**：裸调用探测（扫描红 + 精确行号）；文件尾模块级 façade 导入（**未触发循环崩溃、静默存活**——正是守护针对的「全绿但失效」形态，被扫描逮住）；真实回归形态（`from uuid import uuid4` + 裸调用，静态+行为双红）。

同步：façade docstring 成文跨模块引用规则（唯一模块级例外 `network_common`：零依赖、不在 monkeypatch 面）；修复 `network_assembly.py:185` R6 说明空白损坏；AGENTS.md façade 约束条目补记守护与例外。

## 当前基线（2026-09-28 收工）

- 后端门禁：ruff format/check、mypy strict（79 文件）全绿；**pytest 991 通过 + 1 skipped**（986 + 5 守护）。
- 前端门禁：309 测试 + typecheck + build 全绿（本轮零前端改动）。
- preview smoke：literature/PDF 两步/RAG/network_analyze→result(chains=5) 全通过（当日早些时候验证拆分时）。
- git：`main` 与 `origin/main` 同步于 `57b0718`，工作树干净；预览已停、8010/3000 无监听残留；会话临时产物（/tmp 变异备份、`.tmp/trial-20260928`）已清。

## 待拍板（下一个切片候选，当前无 status: planned 文档）

1. **façade 私有面收缩**（审查 🟡 遗留）：`app/api/network.py` 与测试迁移到兄弟模块直连后收缩 `__all__`，跨约 15 个文件的独立切片。
2. **真实科研数据闭环**：装配 writer 具备消费原语与装配计算，但尚无真实数据端到端（Open Targets 真实 artifact + 真实判定记录）。
3. 检索质量下一轮迭代 / 前端 UX 新一轮循环（按既往节奏）。
