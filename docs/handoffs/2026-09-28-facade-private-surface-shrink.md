# Handoff — façade 私有面收缩：网络服务导入面收敛到兄弟模块（2026-09-28）

## 背景与当日上下文

本日第三次会话，执行前一份 handoff「待拍板候选 #1」（自主交接口径：纯工程、零产品决策、门禁+走查+收工全口径）。同日时间线：日间 network 拆分收口（见 `2026-09-28-network-facade-split-closeout.md`）→ 本切片（6532ca8）→ /review 整改（1896cac，见下方整改节）。

溯源备注：当日早些时候 /init 维护 AGENTS.md 时实测 tcmtech 三份 shim 已从本机消失（`~/bin` 为空、`where tcmtech` 无结果、无 handoff 记录移除），已在 AGENTS.md 命令段加「当前不可用+替代路径」注记——该编辑未单独成笔，随本切片 6532ca8 的 AGENTS.md 修改一并入库（提交信息未单列，特此溯源）。

## 落地（TDD：守护断言先红后绿）

1. **守护扩展**（`tests/test_network_facade_late_binding.py` 5→8 断言），新增三条：
   - `test_api_layer_does_not_import_facade`：AST 扫描 `app/api/*.py`，禁止任何形式的 façade 导入。
   - `test_only_the_guard_test_imports_facade`：AST 扫描 `tests/*.py`，除 guard 本体禁止导入 façade。
   - `test_facade_all_is_exactly_the_patch_surface`：façade `__all__` 恰为 `_get_repository`/`select_network_provider`/`uuid4`。
   - 原 5 断言全保留；3 个行为断言升级为「patch 打在 façade + 入口从兄弟模块直取」形态——比原先「façade 自导自调」更强的 late-binding 证明。
2. **消费方迁移**（12 文件）：`app/api/network.py` 12 个名字改直连 5 个兄弟模块；7 个测试文件调用位点直连兄弟模块、12 处 monkeypatch 改字符串形式 `monkeypatch.setattr("app.services.network.<name>", ...)`（conftest.py:92 既有先例）；guard test 成为全仓唯一导入 façade 的测试（conftest 仅字符串 patch，不算导入）。
3. **façade 收缩**（`services/network.py`）：69 名字 → 16 个模块属性 = 3 个 patch 面 + 13 个被 sibling `_facade.X` 引用的管道名；`__all__` 69→3。管道名 re-export 必须用冗余别名形式 `from x import y as y`——plain 导入过不了 mypy strict 的 `no_implicit_reexport`（sibling 的 `_facade.X` 访问会报 attr-defined，实测 18 错），also 被 ruff isort 拆分为逐条语句属本仓 ruff 配置的规范形态（combine-as-imports 默认 false）。

## 关键事实

- patch 面不变：monkeypatch 仍打在 `app.services.network` 模块属性上（字符串定位），sibling 函数体内 `_facade.` 调用时解析——façade 从「导入面 + patch 面」降级为纯 patch 面，late-binding 机制零改动。
- façade 不再 re-export 的 53 个名字现无任何消费方（迁移前逐名盘点：`_facade.X` 引用面 16 名、测试导入/patch 面全覆盖），`from app.services.network import *` 语义同步收缩。
- 验证路径发现的环境事实：`run-internal-preview.ps1` 是 UTF-8 无 BOM，**必须用 pwsh（7.x）执行**；`powershell`（5.1）按 GBK 误读中文注释会在 line 26 报解析错误。AGENTS.md「本机是 pwsh」口径再次确认。

## 门禁与验证（收工口径，全绿）

- 后端：ruff format --check / ruff check / mypy strict（79 文件）/ **pytest 994 通过 + 1 skipped**（991 基线 + 3 新守护断言）。
- 前端（零改动认证）：test（0 fail）/ typecheck / build 全绿；`next-env.d.ts` build 漂移已 `git checkout` 还原。
- preview smoke（pwsh 起停，isolated runtime `.tmp/trial-facade-shrink`）：literature / PDF 两步 / RAG / **network_analyze→result(chains=5)→report** 全通过——api 层直连迁移端到端验证；runtime 目录已清，8010/3000 无监听残留。

## 遗留与下一个切片候选

1. **真实科研数据闭环**（产品主轴缺口）：装配 writer 已具备消费原语与装配计算，尚无真实数据端到端（Open Targets 真实 artifact + trusted manifest + 真实判定记录）；需 operator 参与拍板数据源与 manifest。
2. 检索质量下一轮迭代 / 前端 UX 新一轮循环（按既往节奏）。

## /review 整改（同日，紧随 6532ca8）

/review 对 6532ca8 给出 0🔴/1🟠/1🟡/2⚪，本轮全部闭环（TDD + 物理变异验证）：

- **🟠 相对导入盲区**：`_facade_import_offenders` 与 sibling 扫描此前只匹配 `node.module` 绝对形态，`from ..services.network import x`（level=2）/`from .network import x`/`from . import network` 三形态全部漏检（AST 模拟实证）。修复：新增 `_is_relative_facade_import` 尾段匹配（AST 无包上下文，按 last-segment 判定；`network_common` 等合法兄弟不会落在裸 `network` 段，负控制锁定零误报），两个扫描器同步接入；新增强制形态矩阵单元测试 `test_facade_import_scanner_catches_every_import_shape`（8 捕获形态 + 4 负控制），红→绿。
- **🟡 扫描面**：测试层扫描 `glob("test_*.py")` → `rglob("*.py")`（嵌套目录不再逃逸），`conftest.py` 纳入扫描（字符串 patch 非 import,天然合法不误报）。
- **⚪**：`test_network_omics.py` 中段导入统一括号块风格；`CLAUDE.md` 项目入口行同步「sibling 即公共导入面、network.py 仅为私有 patch hub」。

### 变异验证记录（cp 备份还原，非 git checkout）

| 组 | 注入 | 红形态与原因 |
|---|---|---|
| M1 | api 文件尾追加绝对 façade 导入 | 扫描红，精确行号 `app/api/network.py:528` |
| M2 | api 首行相对导入 `from ..services.network import ...` | 扫描红 `:1 relative import of the network façade`（整改前此形态漏检——单元测试红阶段实证） |
| M3 | `tests/nested/test_probe_facade.py` 嵌套 façade 导入 | rglob 扫描红（旧 `glob("test_*.py")` 会漏） |
| M4a | conftest 导入 façade **已移除**的名字 | **崩溃形态**：conftest 收集期 ImportError——fail loud,但不计扫描器验证 |
| M4b | conftest 导入 façade 仍导出的 `uuid4` | 扫描红 `tests/conftest.py:113`（崩溃形态不可替代扫描验证,故重做） |
| M5 | façade `__all__` 混入 `grade_chains_evidence` | 断言红（sorted 集合差） |

## 基线（整改后）

- 后端门禁四项全绿：ruff format/check、mypy strict（79 文件）、**pytest 995 通过 + 1 skipped**（994 + 1 scanner 形态矩阵断言）。
- 前端零 diff 认证：test 309/0 + typecheck + build 全绿。
- smoke 免跑：本轮零 `app/` 运行时 diff（仅 guard 测试、omics 测试风格、两份文档），循 9-28 test-only 提交先例；运行时代码与 6532ca8 smoke 验证态逐字节一致。
