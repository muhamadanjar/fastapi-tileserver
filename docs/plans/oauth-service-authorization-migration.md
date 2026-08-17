# Tileserver API OAuth Service Authorization Migration Plan

Master Plan: [Service Principal OAuth Authorization](../../../usermanagement_api/docs/plans/service-principal-oauth-authorization.md)

Execution Progress: [Tileserver API OAuth Service Authorization Progress](../progress/oauth-service-authorization-migration.md)

## Objective

Migrate Tileserver's machine-originated Upload API calls from a static bearer credential to OAuth `client_credentials`, while retaining current user authorization through User Management `/auth/authorize`.

## Unchanged contracts

- Protected user routes continue to require the internal user JWT.
- `/tiles`, `/downloads`, `/attachments`, and read-only `/api/v1` operations continue to require `tiles.read`; mutation operations continue to require `tiles.manage`.
- External map services and GeoServer credentials are not OAuth service tokens and are outside this migration.

## Deprecated targets

Mark `UPLOAD_API_SERVICE_TOKEN`, its compatibility aliases, and static bearer-header construction in Upload clients as deprecated when Upload dual mode is available. Emit startup and runtime usage telemetry and remove them at the master-plan deadline.

## OAuth client configuration

Create one Tileserver client per environment. Its Upload token uses audience `upload-api` and only `upload.artifacts.read` and `upload.artifacts.lease` where the current artifact workflow requires them. Do not grant `tiles.manage` to the service client merely because user routes use that Permission.

## Implementation phases

1. Adopt the shared token client in API and worker processes that call Upload.
2. Replace static Upload Authorization headers with short-lived tokens requested for `upload-api`.
3. Keep a deprecated, observable static fallback during dual mode.
4. Ensure background tiling/download tasks acquire their own in-memory token and never serialize it into task payloads.
5. Verify Upload observes only OAuth traffic for Tileserver.
6. Remove legacy settings, fallback code, and obsolete tests/docs after the deadline gate.

## Future inbound service requests

Machine calls to Tileserver require a token with audience `tileserver-api` and service-scoped Permissions. Delegated user calls require both User and Service Principal identities; direct user requests retain the current internal-JWT flow.

## Verification

- Existing `tiles.read` and `tiles.manage` online authorization behavior remains unchanged.
- API and worker Upload calls succeed using OAuth and fail on wrong audience, missing scope, revocation, or introspection outage.
- Tokens are not stored in task payloads, database records, or logs.
- Legacy fallback usage reaches zero before removal.
