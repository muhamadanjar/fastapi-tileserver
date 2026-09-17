# Tileserver Online Authorization

Tileserver is an OAuth2 resource server. Protected requests require the User
Management internal access JWT in the request header:

```http
Authorization: Bearer <internal-access-jwt>
```

Tileserver forwards the token to User Management's `/auth/authorize` endpoint
on every protected request. User Management validates the JWT and evaluates the
requested permission. Raw OAuth access tokens are identity-only and are not
accepted by Tileserver; exchange them for the User Management internal JWT
first.

## Configuration

Set `USERMANAGEMENT_API_URL` to the internal User Management API address and
`AUTHORIZATION_TIMEOUT_SECONDS` to the desired bounded request timeout. Do not
configure a User Management JWT signing key or public key in Tileserver.

`AUTH_DISABLED=true` is only for isolated local development or tests. It must
remain `false` in shared and production environments.

## Route policy

All routes are protected by default. `/`, health, OpenAPI/docs, and `OPTIONS`
are public. The browser-facing `/api/v1/analysis-workspace/*` workflow is also
public, but its input and result resources require an `X-Analysis-Session`
capability and are isolated by that capability. Saving a workspace result as a
durable catalog layer is an exception: `POST .../jobs/{job_id}/save` requires
`tiles.manage`.

Protected `GET` and `HEAD` requests require `tiles.read`. Mutations and all
`/api/v1/analysis-references/*` configuration routes require `tiles.manage`.
Permissions are service-wide; there is not yet per-layer or per-project
ownership authorization.

## Error behavior

- Missing, malformed, expired, or invalid bearer token: `401`.
- Valid token without the required permission: `403`.
- User Management timeout, outage, or malformed authorization response: `503`.

There is no local JWT-claim fallback, so permission changes and token
revocation take effect at the next Tileserver request.

Related Plan: [Tileserver Online Permission Authorization Plan](../plans/online-permission-authorization.md)

Related Progress: [Tileserver Online Permission Authorization Progress](../progress/online-permission-authorization.md)

For the concise deployment guide, see [Online Permission Authorization](online-permission-authorization.md).
