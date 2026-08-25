# Tileserver Online Permission Authorization Plan

Related Progress: [Tileserver Online Permission Authorization Progress](../progress/online-permission-authorization.md)

Related System Plan: [Online Permission Authorization](../../../usermanagement_api/docs/plans/online-permission-authorization.md)

## Objective

Replace Tileserver's local JWT-only authorization with an online, fail-closed
authorization decision from User Management for every protected route.

## Route permission matrix

| Route family | Method | Permission |
| --- | --- | --- |
| `/tiles`, `/downloads`, `/attachments` | any protected read | `tiles.read` |
| `/api/v1` | `GET`, `HEAD` | `tiles.read` |
| `/api/v1` | other methods | `tiles.manage` |

`/health`, `/`, OpenAPI/docs, and `OPTIONS` remain public. This is an initial
coarse-grained matrix; individual mutation families may later split from
`tiles.manage` without altering the authorization client contract.

## Implementation

1. Add User Management URL and authorization timeout configuration.
2. Replace local JWT verification in middleware with a POST to
   `/auth/authorize`, forwarding the bearer token and a middleware-selected
   permission.
3. Map denial to `403`; map User Management timeout/error to `503`; preserve
   `401` for missing/malformed credentials.
4. Set `request.state.principal` from the returned minimal identity.
5. Add middleware tests for allow, deny, and unavailable authorization service.
