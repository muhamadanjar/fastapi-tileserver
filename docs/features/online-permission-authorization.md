# Tileserver Online Permission Authorization

Tileserver delegates authorization for every non-public request to User
Management. Send the User Management internal JWT as a bearer token. Tileserver
forwards it to `/auth/authorize` with either `tiles.read` or `tiles.manage`.

Configure the service with:

```dotenv
AUTH_DISABLED=false
USERMANAGEMENT_API_URL=http://usermanagement-api:8000
AUTHORIZATION_TIMEOUT_SECONDS=5
```

No User Management JWT signing secret or public verification key belongs in
Tileserver. Raw OAuth tokens are not resource tokens; callers must first obtain
or exchange for the User Management internal JWT.

The service protects every route by default. The public exceptions are root,
health, API documentation, CORS preflight, and the browser-owned analysis
workspace. Workspace data is isolated by `X-Analysis-Session`; its durable
`POST /api/v1/analysis-workspace/jobs/{job_id}/save` operation requires
`tiles.manage`.

Protected reads require `tiles.read`; mutations and analysis-reference
configuration require `tiles.manage`. Missing or invalid tokens receive `401`,
permission denials receive `403`, and unavailable or malformed User Management
responses receive `503`.

Related Plan: [Tileserver Online Permission Authorization Plan](../plans/online-permission-authorization.md)

Execution Progress: [Tileserver Online Permission Authorization Progress](../progress/online-permission-authorization.md)
