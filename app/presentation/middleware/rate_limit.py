"""Redis-backed fixed-window request rate limiting."""

from __future__ import annotations

import logging
import time
from typing import Any

from redis.exceptions import RedisError
from starlette.responses import JSONResponse


logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """Limit HTTP requests per client IP using an atomic Redis counter."""

    excluded_paths = {"/health", "/docs", "/redoc", "/openapi.json"}

    def __init__(
        self,
        app: Any,
        redis_client: Any,
        max_requests: int = 100,
        window_seconds: int = 60,
        key_prefix: str = "tileserver:rate-limit",
        enabled: bool = True,
    ) -> None:
        self.app = app
        self.redis = redis_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix
        self.enabled = enabled

    @staticmethod
    def _client_ip(scope: dict[str, Any]) -> str:
        client = scope.get("client")
        return client[0] if client else "unknown"

    def _key(self, client_ip: str, window: int) -> str:
        return f"{self.key_prefix}:{client_ip}:{window}"

    async def _increment(self, key: str) -> int:
        async with self.redis.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, self.window_seconds)
            count, _ = await pipeline.execute()
        return int(count)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "").rstrip("/") or "/"
        if (
            not self.enabled
            or scope.get("type") != "http"
            or path in self.excluded_paths
        ):
            return await self.app(scope, receive, send)

        now = int(time.time())
        window = now // self.window_seconds
        reset_at = (window + 1) * self.window_seconds
        remaining = self.max_requests
        try:
            count = await self._increment(self._key(self._client_ip(scope), window))
        except (RedisError, OSError, RuntimeError) as exc:
            logger.warning("Rate-limit store unavailable; allowing request: %s", exc)
            return await self.app(scope, receive, send)

        remaining = max(0, self.max_requests - count)
        headers = {
            "X-RateLimit-Limit": str(self.max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_at),
        }
        if count > self.max_requests:
            headers["Retry-After"] = str(max(1, reset_at - now))
            return await JSONResponse(
                {"detail": "Rate limit exceeded."},
                status_code=429,
                headers=headers,
            )(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (name.lower().encode(), value.encode())
                    for name, value in headers.items()
                ]
            await send(message)

        return await self.app(scope, receive, send_with_headers)
