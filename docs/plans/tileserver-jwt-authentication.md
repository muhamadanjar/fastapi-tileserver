# Tileserver JWT Authentication Plan

## Objective

Require User Management internal access JWTs for Tileserver's business and static-resource routes, while preserving the separate server-to-server Upload API caller secret.

## Design

- Verify signed Bearer JWTs locally using `ACCESS_TOKEN_SECRET` for HS256 or `ACCESS_TOKEN_PUBLIC_KEY` for RS256.
- Require an unexpired `token_type=access` token with a subject.
- Protect `/api/v1`, `/tiles`, `/downloads`, and `/attachments`; keep `/health`, the root endpoint, OpenAPI, and CORS preflight public for operations and browser interoperability.
- Fail closed when authentication is enabled but no verification key is configured.
- Retain `UPLOAD_API_SERVICE_TOKEN` exclusively for Tileserver-to-Upload API artifact requests; it is not accepted as an inbound user credential.

## Compatibility and rollout

This is a breaking authentication change for protected paths. Configure Tileserver with the same User Management HMAC signing secret only when using HS256. Prefer an RS256 setup so Tileserver receives only the public verification key.

Related Progress: [Tileserver JWT Authentication Progress](../progress/tileserver-jwt-authentication.md)
