# Tileserver Online Permission Authorization Plan

Related Progress: [Tileserver Online Permission Authorization Progress](../progress/online-permission-authorization.md)

Related System Plan: [Online Permission Authorization](../../../usermanagement_api/docs/plans/online-permission-authorization.md)

## Objective

Make Tileserver an OAuth2 resource server. It accepts only User Management's
internal user JWT, forwards that bearer token to User Management for an online,
fail-closed authorization decision, and leaves the browser-owned analysis
workspace public without making the rest of the service public.

Raw OAuth access tokens are identity-only and are not accepted by Tileserver.
An OAuth login must first be exchanged by User Management for its internal JWT.

## Route permission matrix

| Route family | Method | Permission |
| --- | --- | --- |
| All protected routes | `GET`, `HEAD` | `tiles.read` |
| All protected routes | `POST`, `PUT`, `PATCH`, `DELETE` | `tiles.manage` |
| `/api/v1/analysis-references/*` | any | `tiles.manage` |
| `/api/v1/analysis-workspace/jobs/{job_id}/save` | `POST` | `tiles.manage` |

The public allowlist is `/`, health, OpenAPI/docs, `OPTIONS`, and
`/api/v1/analysis-workspace/*` except its durable-result `save` operation.
Workspace data remains isolated by the required `X-Analysis-Session` capability.
Every route not on this allowlist is protected by default. Permissions are
service-wide in this phase; resource ownership and tenant authorization are out
of scope until User Management exposes that contract.

## Implementation

1. Enable the authorization middleware in the application composition root.
2. Use a narrow public allowlist rather than a protected-prefix list.
3. POST each protected request's bearer token and required permission to
   `/auth/authorize`; do not verify or fall back to local JWT claims.
4. Map missing/malformed or invalid tokens to `401`, denial to `403`, and User
   Management outage/malformed response to `503`.
5. Keep `AUTH_DISABLED` as an explicit local/test escape hatch only.
6. Add regression coverage for the allowlist, route permissions, unavailable
   User Management, and the protected workspace save boundary.
