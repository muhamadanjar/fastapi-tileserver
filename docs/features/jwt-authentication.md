# Tileserver JWT Authentication

Tileserver requires a User Management internal access JWT for `/api/v1`, `/tiles`, `/downloads`, and `/attachments`. Send it in the request header:

```http
Authorization: Bearer <internal-access-jwt>
```

The token must be unexpired, have `token_type=access`, and contain `sub` (or the compatible `user_id`) claim. Health checks, the root endpoint, OpenAPI, and CORS preflight remain public.

## Configuration

For the current HS256 deployment, set Tileserver's `ACCESS_TOKEN_SECRET` to exactly the same value as User Management's `SECRET_KEY`, then set `ACCESS_TOKEN_ALGORITHMS=HS256`.

For production, RS256 is preferable: keep the private key only in User Management and set Tileserver's `ACCESS_TOKEN_PUBLIC_KEY` with `ACCESS_TOKEN_ALGORITHMS=RS256`.

`AUTH_DISABLED=true` is only for isolated development or tests. It must remain disabled in shared and production environments.

`UPLOAD_API_SERVICE_TOKEN` is separate from user authentication. It is a static, server-only credential used only when Tileserver calls Upload API for artifact lease, metadata, and content operations.

Related Plan: [Tileserver JWT Authentication Plan](../plans/tileserver-jwt-authentication.md)

Related Progress: [Tileserver JWT Authentication Progress](../progress/tileserver-jwt-authentication.md)
