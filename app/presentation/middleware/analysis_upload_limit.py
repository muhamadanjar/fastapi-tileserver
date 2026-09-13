"""Bound the multipart stream before Starlette spools uploaded files to disk."""
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class AnalysisUploadLimitMiddleware:
    def __init__(self, app, max_bytes):
        self.app = app
        self.max_bytes = max_bytes + 1024 * 1024  # Multipart envelope allowance.

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") != "/api/v1/analysis-workspace/inputs" or scope.get("method") != "POST":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Content-Length tidak valid."}, status_code=400)(scope, receive, send)
        if length > self.max_bytes:
            return await JSONResponse({"detail": "Ukuran ZIP melebihi batas unggahan."}, status_code=413)(scope, receive, send)
        consumed = 0

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            if message["type"] == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.max_bytes:
                    raise HTTPException(413, "Ukuran ZIP melebihi batas unggahan.")
            return message

        return await self.app(scope, limited_receive, send)
