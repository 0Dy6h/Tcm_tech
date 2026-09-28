# Handoff — façade 私有面收缩：网络服务导入面收敛到兄弟模块（2026-09-28）

## 背景

同日 `/review`（9-28 network 拆分收口）遗留的 🟡 项「私有面固化」：拆分后 `services/network.py` 仍以 69 名字的 `__all__` 充当事实公共导入面，`app/api/network.py` 与测试全部从 façade 导入。本切片按 handoff 待拍板候选 #1 执行（自主交接口径：纯工程、零产品决策、门禁+走查+收工全口径）。

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

## 基线

- `main` 工作树：本切片单笔提交；远端同步后干净。
- 后端 994+1skipped / 前端 309+typecheck+build 为新基线。
