import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.eval import router as eval_router
from app.api.literature import router as literature_router
from app.api.metrics import router as metrics_router
from app.api.network import router as network_router
from app.api.rag import router as rag_router
from app.api.upload import router as upload_router
from app.core.access_control import LOCAL_FRONTEND_ORIGINS, install_access_token_middleware
from app.core.config import get_settings
from app.core.logging_config import init_logging
from app.core.logging_middleware import RequestLoggingMiddleware
from app.core.model_warmup import start_model_warmup, warmup_status

if "pytest" not in sys.modules:
    init_logging()

logger = logging.getLogger(__name__)

# Maximum request body size: 50MB (prevents DoS via large payloads)
MAX_REQUEST_SIZE = 50 * 1024 * 1024

# Resolve settings during application import so production validation fails
# before the server accepts health checks or business traffic.
_startup_settings = get_settings()



@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Preload real embedding / NLI models in a daemon thread when enabled;
    # a no-op with the default hashing embedding and NLI off.
    start_model_warmup(_startup_settings.nli_backend)
    yield


app = FastAPI(title=_startup_settings.app_name, lifespan=lifespan)


class _RequestBodyTooLarge(MultiPartException):
    """继承 multipart 异常，让解析器在超限时关闭已创建的上传临时文件。"""


class RequestSizeLimitMiddleware:
    """逐块计数实际字节；分块传输及虚假的 Content-Length 同样受限。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        def too_large() -> JSONResponse:
            return JSONResponse(
                status_code=413,
                content={"detail": f"请求体过大，最大允许 {MAX_REQUEST_SIZE // 1024 // 1024}MB"},
            )

        if scope["method"] in ("POST", "PUT", "PATCH"):
            content_length = Headers(scope=scope).get("content-length")
            if content_length:
                try:
                    declared_length = int(content_length)
                except ValueError:
                    await JSONResponse(
                        status_code=422,
                        content={"detail": "invalid Content-Length"},
                    )(scope, receive, send)
                    return
                if declared_length < 0:
                    await JSONResponse(
                        status_code=422,
                        content={"detail": "invalid Content-Length"},
                    )(scope, receive, send)
                    return
            else:
                declared_length = 0
            if declared_length > MAX_REQUEST_SIZE:
                await too_large()(scope, receive, send)
                return

        size = 0
        exceeded = False
        rejected = False

        async def limited_receive() -> Message:
            nonlocal size, exceeded
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > MAX_REQUEST_SIZE:
                    exceeded = True
                    raise _RequestBodyTooLarge("request body is too large")
            return message

        async def limited_send(message: Message) -> None:
            nonlocal rejected
            if exceeded:
                # FastAPI/Starlette 可能把读取异常转成 400；保持对外的 413 契约。
                if not rejected:
                    rejected = True
                    await too_large()(scope, receive, send)
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except _RequestBodyTooLarge:
            if not rejected:
                await too_large()(scope, receive, send)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unexpected exceptions to avoid leaking stack traces.

    Logs the full exception for debugging while returning a safe error to clients.
    In development, returns detailed error information for easier debugging.
    """
    # Log the full exception with stack trace for troubleshooting
    logger.exception(
        "Unhandled exception during %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )

    settings = get_settings()

    # In development, return detailed error information
    if settings.environment == "dev":
        return JSONResponse(
            status_code=500,
            content={
                "detail": "内部错误",
                "error": str(exc),
                "type": type(exc).__name__,
            },
        )

    # In production, return generic message
    return JSONResponse(
        status_code=500,
        content={"detail": "内部错误，请稍后重试。"},
    )


# Order matters: Starlette installs middleware via `insert(0, ...)` and builds
# the stack with `reversed(middleware)`, so the LAST one added is OUTERMOST.
# We want CORS outermost so that 401 responses from the access-control middleware
# still carry Access-Control-Allow-Origin headers for browser callers.
# RequestLoggingMiddleware goes before access control so it captures all requests
# (including 401s) and can log request_id for debugging.
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
# 鉴权/来源拒绝发生在读取上传 body 之前，CORS 仍在最外层。
install_access_token_middleware(app)
app.add_middleware(
    CORSMiddleware,
    # 3000 为主前端端口；3100 为内部预览/换端口试用场景（run-internal-preview.ps1
    # 文档化 -FrontendPort 3100）。仅本机回环地址，不放宽到其他来源。
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.include_router(literature_router)
app.include_router(rag_router)
app.include_router(eval_router)
app.include_router(upload_router)
app.include_router(network_router)
app.include_router(metrics_router)


@app.get("/health")
def health() -> dict[str, str | bool | None]:
    # Keep ``status`` / ``service`` stable: external launchers fingerprint on them.
    # ``embedding_ready`` / ``nli_ready``: null = model path disabled,
    # false = still loading (or failed), true = preloaded.
    return {
        "status": "ok",
        "service": "qiyan-nexus-api",
        **warmup_status(),
    }
