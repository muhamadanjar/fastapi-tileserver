Related Plan: [Tileserver API OAuth Service Authorization Migration](../plans/oauth-service-authorization-migration.md)

Execution Progress: [Tileserver API OAuth Service Authorization Progress](../progress/oauth-service-authorization-migration.md)

# OAuth Upload Service Client

Tileserver API's synchronous Upload client obtains a short-lived token from User Management for audience `upload-api`, with `upload.artifacts.read` and `upload.artifacts.lease`.

Configure `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OAUTH_TOKEN_URL`, and `UPLOAD_API_URL`. Both OAuth credential fields must be present together. The token remains in process memory and is renewed before expiry.

`UPLOAD_API_SERVICE_TOKEN` remains a deprecated fallback during the bounded dual-mode window and emits a warning when configured. Each fallback request also emits a secret-safe `legacy_static_token` event with `outcome=used`. Remove it after both caller and Upload resource metrics report zero legacy usage and before the agreed two-release/30-day deadline.

Build from the service directory. The pinned public `service_auth` dependency
is installed over Git HTTPS:

```bash
docker build --target production -f docker/Dockerfile -t tileserver-api:local .
```
