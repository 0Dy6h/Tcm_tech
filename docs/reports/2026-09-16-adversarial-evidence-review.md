# 2026-09-16 前后端对抗审查

本轮在隔离副本中修复证据存储、并发更新、导出完整性、前端错误反馈和已发布依赖漏洞；未使用真实研究数据、外部科研数据库或付费模型，`formal_network_ready=false`、owner 隔离、omics/live 显式 opt-in 与免责声明保持原契约。正式环境应安装下述已验证版本后再启用新代码。

## 已修复问题

| 问题 | 结果 |
| --- | --- |
| 同名/相同 slug PDF 覆盖旧引用，长文件名上传成功却不能下载 | 实际上传 ID 绑定文献、完整文件名和内容 SHA-256；固定长度、原子发布，旧合法 ID 继续可读 |
| MIME 伪装的空文件/HTML 被当作 PDF 保存 | 落盘前验证 `%PDF-`；拒绝时不修改文献元数据 |
| 解析期间替换 PDF，旧解析结果污染新文件 | 前端发送 upload ID，服务层检查后由 JSON/SQLite/PostgreSQL 仓储做条件更新，冲突返回 409 |
| 两个 JSON 仓储实例同时更新时丢失记录 | canonical path 共享进程内锁，完整文件原子发布；仅承诺单进程预览安全 |
| 未篡改 RAG 答案在浏览器导出时返回 409 | 签名兼容 `1.0`→`1` 的 JSON 数字往返；仍校验完整原始字段，拒绝增删字段、数值或其他类型篡改 |
| 非 ASCII 完整性 token 触发 500 | 不合法 token、不可序列化字段均拒绝导出 |
| HTTP 错误被误报成服务未启动，鉴权错误被当作文献缺页 | fetcher 保留 `ApiStatusError`；404 才进入缺页；失败实体缓存可重试，错误使用可访问 alert |
| 替换 PDF 解析失败仍显示旧预览，旧检索覆盖新检索 | 上传和解析反馈分开，清除旧预览；取消过期请求并核对请求身份，防双提交 |
| 手机界面被长 ID/路径撑宽 | 元数据可在任意必要位置换行，390 px 上传控件完整可见 |
| 本地默认后端端口不一致 | 本地 dev/preview/E2E 默认 8010；容器/云端部署语境保持原有配置 |

## 已验证依赖版本

前端 Next **16.3.3**、sharp **0.35.4**、PostCSS **8.5.23**、nanoid 3.x **3.3.18**、baseline-browser-mapping **2.11.0**、esbuild **0.28.1**，精确解析见 `frontend/pnpm-lock.yaml`。其中 Next 修复 Windows App Router RCE（GHSA-p293-qw3h-jr36）及 AVIF 图片优化 RCE（GHSA-2xp9-vwfh-vxw4）。

后端保留 FastAPI **0.136.3**，升级 pypdf **6.16.1**、Starlette **1.3.1**、python-multipart **0.0.31**、pydantic-settings **2.14.2**、transformers **5.10.4**。最后两项属于开发/可选模型环境；5.10.0 已被上游撤回，没有采用。已用现有 Windows CPython **3.13.12** 及隔离补丁包验证实际 import，完整环境依赖关系无冲突。

## 验证结果

- 后端：format、ruff、mypy（75 个源文件）通过；pytest **988 passed / 1 skipped**。默认 JSON 运行跳过 SQLite 专属同步集成用例，JSON/SQLite 仓储合同与 SQLite CAS 交错测试已执行。保留 6 条既有 SciPy 精度告警及 1 条 Starlette TestClient 的 httpx 弃用提示。
- 前端：Linux 与 Windows 各 **309 passed**，typecheck、Next 生产构建均通过。Windows 原生 sharp 合成 AVIF 编解码通过。
- 浏览器：隔离 Next/FastAPI 的 **12 项**桌面/窄屏流程通过，覆盖 HTTP 故障、检索交错、PDF 替换与旧引用、过期解析、RAG Markdown/DOCX、mock 网络任务和报告；无 pageerror，自有服务全部停止。
- 并发变异：正常实现 3 项通过；替换共享锁为实例锁导致 2 项失败，移除 SQLite 条件更新导致 1 项失败，证明回归能检出数据覆盖。
- npm 复查 **0 vulnerabilities**；Windows 私有 pnpm 缓存已证明完全离线 `--frozen-lockfile --ignore-scripts` 安装，锁文件未变化。Python 补丁保留可离线安装的原始 universal wheels 与 SHA-256 清单。

## 保留边界

OSV 仍报告现有可选 PyTorch 2.12.0 的 `torch.jit.script` 内存错误（low）和 setuptools 81.0.0 在 macOS sdist 的 Unicode 排除绕过（moderate，GHSA/PYSEC 是同一问题）。代码未调用前者，当前验证平台为 Windows/Linux；PyTorch 当前要求 setuptools<82，不能孤立升级到修复版 83。此轮未扩大到大型可选模型运行库升级，也不把 npm 的零公告当作全部依赖零公告。

PostgreSQL 实现已同步并经过类型检查，未连接真实 PostgreSQL。PDF 签名检查不是完整恶意文件检测，OCR 与 mock chunk 生成边界保持不变；JSON 文件锁不提供跨进程事务。RAG 签名密钥仍按现有单进程预览契约保存在进程内，重启会使旧导出 token 失效。未验证云端真实鉴权代理或真人科研判定。
