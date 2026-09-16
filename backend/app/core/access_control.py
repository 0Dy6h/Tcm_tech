"""X-Access-Token middleware for the Qiyan Nexus API.

A2 minimum access control. ``QIYAN_ACCESS_TOKENS`` is read at app construction
time as a comma-separated allowlist. When the allowlist is empty (dev default)
only loopback Hosts and the documented local browser origins are accepted.
Otherwise every request that is not ``/health`` or
a CORS preflight (``OPTIONS``) must carry a matching ``X-Access-Token`` header
or receive ``401``.

Token comparison is case-sensitive and whitespace-stripped at parse time.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.reviewer_identity import (
    LOCAL_REVIEWER_ID,
    REVIEWER_ID_HEADER,
    REVIEWER_ID_STATE_ATTR,
    normalize_reviewer_id,
)

ACCESS_TOKEN_HEADER = "X-Access-Token"
ACCESS_TOKENS_ENV = "QIYAN_ACCESS_TOKENS"
_OPEN_PATHS: frozenset[str] = frozenset({"/health"})
LOCAL_FRONTEND_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3100",
    "http://127.0.0.1:3100",
)

logger = logging.getLogger(__name__)


def _local_request_error(request: Request) -> str | None:
    """开放预览仍须阻断 DNS rebinding 与无需预检的跨站表单写入。"""
    host = request.headers.get("host", "")
    try:
        authority = urlsplit(f"http://{host}")
        if (
            authority.hostname not in {"127.0.0.1", "localhost", "::1"}
            or authority.username is not None
            or authority.password is not None
            or authority.path
            or authority.query
            or authority.fragment
        ):
            return "local preview requires a loopback Host"
        # 访问 port 属性也会拒绝非法端口，不只校验 hostname。
        _ = authority.port
    except ValueError:
        return "local preview requires a loopback Host"

    origin = request.headers.get("origin")
    if origin is not None:
        if origin not in LOCAL_FRONTEND_ORIGINS and origin != f"{request.url.scheme}://{host}":
            return "cross-origin request is not allowed"
    elif request.headers.get("sec-fetch-site") == "cross-site":
        return "cross-origin request is not allowed"
    return None


def parse_access_tokens(raw: str | None) -> frozenset[str]:
    """Parse ``QIYAN_ACCESS_TOKENS`` raw value into a stripped token allowlist."""

    if not raw:
        return frozenset()
    return frozenset(token.strip() for token in raw.split(",") if token.strip())


class AccessTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, allowed_tokens: frozenset[str]) -> None:
        super().__init__(app)
        self._allowed_tokens = allowed_tokens

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not self._allowed_tokens:
            error = _local_request_error(request)
            if error is not None:
                return JSONResponse(status_code=403, content={"detail": error})
            setattr(request.state, REVIEWER_ID_STATE_ATTR, LOCAL_REVIEWER_ID)
            return await call_next(request)
        # CORS preflight is normally absorbed by CORSMiddleware (installed outer);
        # this branch stays as a defensive net for OPTIONS requests that reach
        # us anyway (e.g. without an Origin header).
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)

        token = request.headers.get(ACCESS_TOKEN_HEADER)
        if token is None or token not in self._allowed_tokens:
            return JSONResponse(
                status_code=401,
                content={"detail": "missing or invalid X-Access-Token"},
            )

        reviewer_id = normalize_reviewer_id(request.headers.get(REVIEWER_ID_HEADER))
        if reviewer_id is not None:
            setattr(request.state, REVIEWER_ID_STATE_ATTR, reviewer_id)

        return await call_next(request)


def install_access_token_middleware(app: FastAPI) -> None:
    """Install ``AccessTokenMiddleware`` reading the env at call time.

    Emits an INFO log line so an empty env does not silently leave the API
    fully open in production. Token values are never logged.
    """

    allowed = parse_access_tokens(os.getenv(ACCESS_TOKENS_ENV))
    if not allowed:
        logger.info(
            "access control disabled: %s unset or empty (open mode)",
            ACCESS_TOKENS_ENV,
        )
    else:
        logger.info(
            "access control enabled with %d token(s) via %s",
            len(allowed),
            ACCESS_TOKENS_ENV,
        )
    app.add_middleware(AccessTokenMiddleware, allowed_tokens=allowed)
