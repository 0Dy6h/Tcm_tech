# HTTP 入口对抗审查与修复

日期：2026-09-14。全部写入测试在独立临时 JSON/SQLite/上传目录执行，未读取运行时密钥、未调用真实 LLM、未触碰 8000 或现有预览实例。

## 复现与修复

1. **P1 开放预览跨站写入 / DNS rebinding。** 原入口仅靠 CORS 响应头；来自外站或 `Origin: null` 的普通 multipart 表单仍成功返回 201 并持久化 PDF。任意 Host 的无 Origin 请求也能读取 API。现于开放模式鉴权层校验回环 Host 和固定前端/自身 Origin；来源不合法直接 403，在读取上传体之前拒绝。受 token 保护部署的代理身份契约保持原样。
2. **P1 分块上传绕过体积限制。** 原 50 MB 总上限只信 Content-Length。将测试上限缩到 512 B 后，超过上限的 chunked multipart 仍返回 201。现 ASGI receive 逐块计数；超限块不会交给业务层，multipart 解析器关闭已产生的临时文件，外部统一收到 413。非法 Content-Length 仍按既有 422 契约返回。

前端允许来源由一份常量供 CORS 与开放模式请求防线共同使用；开发者文档/测试统一使用真实回环主机名，未把测试域名加入生产白名单。

## 验证

- 新增 HTTP 边界 11 项：修前 6 failed / 5 passed，修后全部通过。包含真实 PDF 路由的持久化前拒绝、合法来源正例、DNS rebinding、无长度与谎报长度的多块 ASGI 读取停止。
- 完整后端：ruff format --check、ruff check、mypy 全部通过；pytest **964 passed, 1 skipped**。
- 测试环境为已有 Windows `.uv-test-venv`，源码在隔离副本。mypy 2.1.0 默认把缓存写到 WSL UNC 路径时内部崩溃，改用 Windows 临时缓存后完整检查通过，74 个源码文件没有类型问题；未跳过或禁用类型检查。
- 两个 PubMed XML fixture 从原测试目录原样补入隔离副本，仅用于验证，未改变内容。

## 保持的边界

科研协议、owner 授权、逐行人工判定、omics opt-in、writer 消费与 `formal_network_ready=false` 不变。回环 Host 检查不能替代服务监听在 loopback 的部署要求，也不把开放预览提升为面向公网的认证方案。
