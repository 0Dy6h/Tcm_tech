# CONTEXT.md — TCM 平台领域共享语言

> Harness Engineering 支柱一 · 上下文工程
> 每次 Agent 会话必加载此文件。用精确术语替代冗长描述。
> 更新规则：收工时使用文档一致性检查（当前推荐 `neat-freak` 流程）按代码与 `docs/current-state.md` 增量更新。

## 核心领域术语

| 术语 | 简称 | 定义 |
|------|------|------|
| 特应性皮炎 | AD | Atopic Dermatitis，本平台唯一聚焦病种 |
| 肠-脑-皮肤轴 | GBS-Axis | Gut-Brain-Skin Axis，中西医结合核心方法论 |
| 网络药理学 | NetPharm | 从草药→成分→靶点→通路的计算分析方法论 |
| 组学策略 | Omics-Strategy | 以系统整体观组织知识、计算与真实测量验证的底层逻辑；网络药理学是系统层核心应用 |
| 辨证辅助 | Syndrome-Dx | 中医辨证论治的 AI 辅助（非替代） |
| 方剂 | Formula | 中药复方组合 |
| 研究协议 | Research-Protocol | 网络药理学任务的可复现前提：疾病、明确表型、物种、证据策略与查询日期；缺项时不得进入正式网络构建 |
| 靶点 Lineage | Target-Lineage | 以 source record 为观察单元的逐行来源与转换记录；同一 canonical symbol 可对应多条 lineage 行 |
| 疾病靶点 | Disease-Targets | 从独立疾病/表型来源采集并保留 provenance 的靶点集合，不能由成分靶点反推或复制得到 |
| 成分靶点 | Compound-Targets | 从方药成分相关来源或链路提取的靶点集合；它本身不等于疾病靶点 |
| 疾病导入快照 | Disease-Import-Snapshot | network task 创建时由服务端封存的独立疾病靶点输入；旧客户端导入为 `unverified_client_import`，离线 raw artifact 经服务端 hash、trusted manifest 与 parser 后可为 `server_verified_raw_artifact`。两者都不是人工终态 `verified` |
| 派生候选交集 | Intersection-Targets | `Disease-Targets ∩ Compound-Targets` 的 canonical symbol 派生集合；每个 symbol 一条 derivation row 并完整引用两侧 lineage row IDs，任一输入集合缺失时失败关闭为空；未完成人工判定前不称“可信交集” |
| 人工判定 | Adjudication | reviewer 对自动抽取行执行的纳入、排除或继续复核决策，必须与自动抽取状态分离并保留身份、时间和理由 |
| 产物一致性 | Artifact-Consistency | 独立复算确认导出计数、集合、转换和协议字段内部一致；不等于来源真实或科研结论成立 |
| 科研就绪度 | Scientific-Readiness | 对研究协议、真实来源版本、阈值、lineage、人工判定及独立复算是否足以支持正式科研使用的保守门禁 |
| 证据链 | Evidence-Chain | AI 输出的可追溯性保障。MVP 中即为 RAG 回答附带的引用卡片集合（来源→片段→置信度），后台不维护独立证据链对象 |
| 引用卡片 | Citation-Card | 证据链的前端展示单元：来源文献标题、页码/段落片段、置信度指标（必展示，非可选） |
| 魔法链接 | Magic-Link | 无密码登录方式，通过邮件发送一次性链接 |

## 历史规划组件简称（非当前实现）

> 下表保留早期架构讨论中的词汇，不能据此判断仓库已实现对应组件。当前默认是 JSON seed/runtime、可选 SQLite、deterministic keyword retrieval、inline SVG 网络图；不启用 Celery/Redis/Flower、MinIO、PgBouncer、真实 embedding 或按 endpoint 双模型路由。

| 简称 | 组件 | 用途 |
|------|------|------|
| 文献引擎 | LitEngine | 中英文文献检索管道：中文预建本地 pgvector 索引 + 英文 PubMed API 实时检索（见 ADR-0001） |
| RAG | 检索增强生成 | 文献检索 + 问答流水线 |
| Celery | 异步任务队列 | 网络药理学分析后台处理 |
| Flower | Celery 监控面板 | 端口 5555 的任务监控 UI |
| G6 | AntV G6 | 前端图谱可视化引擎 |
| R2 / MinIO | MinIO 对象存储 | 本地 Docker Compose S3 兼容存储，PDF 文件仓库（见 ADR-0007）。阶段 2 可无缝迁移至 Cloudflare R2 |

## 流程中的术语

> `中英分流`、`语义缓存`、`模型路由` 描述历史/长期方案；当前实现只把它们作为讨论词汇或显式 opt-in 方向。`异步长任务` 当前对应本地 network task 状态机，不代表 Celery 已接入。

| 术语 | 含义 |
|------|------|
| 中英分流 | 根据 `language` 字段选择 text2vec-chinese 或 PubMedBERT 做 Embedding |
| 异步长任务 | 网络药理学分析等耗时操作，通过 task_id 轮询状态 |
| 语义缓存 | Redis 中对同用户同会话内精确匹配文本的 LLM 响应缓存，减少重复 API 调用。仅精确文本匹配，不做向量相似度 |
| 模型路由 | Model-Route | 按 API endpoint 决定 LLM：文献/RAG→DeepSeek V4 Flash，报告/辨证→Claude Sonnet 4.6（见 ADR-0004） |
| 红-绿-重构 | TDD 循环：先写失败测试→实现→重构 |

## 角色术语

> 这些角色是产品语言，不是已实现的 RBAC 权限表。当前云端预览只建立 reviewer identity 与 network-task owner isolation。

| 角色 | 权限层级 |
|------|---------|
| 皮肤科医师 | 标准用户（受邀） |
| 科研助理/研究生 | 标准用户 + 批量分析 |
| PI/方法学合作者 | 标准用户 + 数据导出 |
| 管理员 | 全权限（账户管理、监控面板） |

## 已记录的 ADR（架构决策）

详见 `docs/adr/` 目录。ADR 记录长期架构决策与阶段边界；当前开发事实源仍以 `docs/current-state.md`、代码、测试和最新 handoff 为准。

> ADR-0001 至 ADR-0008 是历史规划提案或 deferred 方向，不能当作当前默认实现；各文件顶部已标状态。当前活跃边界优先看 ADR-0009 以后及 `docs/current-state.md`。

| 编号 | 决策 |
|------|------|
| 0001 | 中英文文献分源索引：中文预建本地索引 + 英文 PubMed API |
| 0002 | MVP 仅桌面端，不做移动端适配 |
| 0003 | MVP 不集成付费，全部导出免费 |
| 0004 | 双模型路由：DeepSeek V4 Flash（日常）+ Claude Sonnet 4.6（医学推理） |
| 0005 | 双 Embedding 模型分流：text2vec-base-chinese + PubMedBERT |
| 0006 | NextAuth.js 魔法链接 + 邀请白名单认证 |
| 0007 | 本地 MinIO 对象存储（S3 兼容，阶段 2 可迁 Cloudflare R2） |
| 0008 | Celery + Redis 异步任务架构 |
| 0009 | 前端实际版本基线与 Ant Design 使用策略 |
| 0010 | 研究工作台模块路线图：MVP-A 证据工作台，MVP-B 网络药理学，MVP-C 分子对接/MD |
| 0011 | 外部 LLM 数据流与 PIPL 边界 |
| 0012 | 真实 LLM 显式启用与治理门禁 |
| 0014 | Retrieval provider 与 hybrid search 边界 |
| 0015 | 网络药理学证据分级与指南一致性层 |
| 0016 | RAG 引用透明检索匹配度 |
| 0017 | 网络药理学是唯一产品主轴；文献/PDF/RAG 是证据服务层 |
| 0018 | 组学策略为底层逻辑；网络药理学是系统层核心；真实组学数据为 opt-in 验证层 |
