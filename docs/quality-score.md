# 质量评分 — Harness Engineering 支柱三 · 熵管理

> 每次项目级对抗性 review、架构整改或事实源收口后更新。
> 评分体系：A = 无债务，B = 轻微债务（< 3 缺口），C = 中度债务（3-10 缺口），D = 严重债务

## 当前质量评分（2026-08-15：Gate 2 + owner-scoped adjudication + 候选装配计划；ADR-0018 方向草案）

| 领域 | 评分 | 缺口 | 最后更新 |
|------|------|------|---------|
| 产品需求 | C | 主轴已纠偏，双侧 artifact workflow、逐行判定与候选装配计划已具备工程能力；但尚无真人判定、真实最小科研闭环与组学验证 | 2026-08-15 |
| 技术架构 | B | 分层、安全、immutable snapshot、双 manifest、双 hash、lineage、独立复算、append-only adjudication、assembly plan 与 writer 消费契约（消费原语+装配计算+输出独立 validator）已落地；PG parity 与多 worker claim 仍未完成 | 2026-09-28 |
| 任务拆解 | B | 0017 Gate 2、adjudication、source-bound 装配门禁与 writer 消费契约（D1-D9 全部落地区含 D9 validator）已收口；下一步为真人 reviewer 判定与真实数据闭环；组学层 G3 切片已落地 | 2026-09-28 |
| 前端设计 | A | `/network` 支持双侧 artifact 上传、immutable child task、三集合审计表、adjudication 与装配计划面板；既有页面壳与可访问性门禁保持全绿 | 2026-08-15 |
| 后端 API | B | strict multipart、双 manifest、双 hash、owner-scoped lineage/adjudication/assembly-plan/consume API 与 fail-closed readiness 已落地（含输出信封独立 validator）；科学复核（真人判定）仍未完成 | 2026-09-28 |
| 合规 | A | 免责声明、mock 边界、reviewer 访问边界、客户端未验证路径、`server_verified_raw_artifact` 中间态与组学数据默认不外发边界均明确 | 2026-08-15 |
| 领域文档 | B | ADR-0017、ADR-0018、双侧 artifact guide、整改工作区与 handoff 已建立；EMNLP 论文产出等历史方向材料待归档 | 2026-08-15 |
| 科研就绪度 | D | 工程 provenance、判定与装配计划均可用，但无真人判定记录；`formal_network_ready` 恒 false；真实组学验证尚未实现 | 2026-08-15 |
| 可观测性 | A | Request ID、structured logging、nginx reviewer access log、raw artifact/import payload/plan hash 均有明确路径 | 2026-08-15 |

## 开发启动后需追踪的领域

| 领域 | 关注项 |
|------|--------|
| 前端 | 组件重用率、页面性能、可访问性 WCAG AA |
| 后端 API | 响应时间 SLI、错误率、测试覆盖率 |
| 数据 | runtime/seed 隔离、对象 ownership、SQLite 并发与 orphan upload 清理；pgvector/Neo4j/R2 仅在显式生产化 ADR 后再增加指标 |
| AI | deterministic 检索正确性、citation 可解析率、免责声明覆盖率；真实 provider 仅在 opt-in smoke 时追踪成功率、延迟、成本与配额 |
| 合规 | 免责声明覆盖率、PIPL 合规检查；外发数据流向已记录（ADR-0011） |

## 定期清理任务

| 任务 | 频率 | 工具 |
|------|------|------|
| 文档一致性扫描 | 每周 | `neat-freak` 流程检查代码、current-state、CONTEXT 与 handoff |
| 架构约束违规扫描 | 每次 PR | ESLint + Ruff 自定义规则 |
| 代码质量评分更新 | 每周 | `requesting-code-review` + `scripts/verify-local.ps1` |
| 依赖审计 | 每两周 | `pnpm outdated` / `pip list --outdated` |
| 死代码清理 | 每月 | 手动审查 + 删除未使用模块 |

## 熵积累预警信号

以下信号出现时，立即做一次对抗性 code review 与文档一致性检查：
- 同一概念在多个文件中以不同名称出现
- 新增功能需要修改 3+ 个不相关文件
- 测试覆盖率连续 2 周下降
- TypeScript `any` 类型数量增加
