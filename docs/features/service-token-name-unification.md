# Tileserver Upload API Service Token

Configure Tileserver API and workers with `UPLOAD_API_SERVICE_TOKEN`. Its value must match the `tileserver` entry in Upload API's `UPLOAD_API_SERVICE_TOKENS` map.

```env
UPLOAD_API_SERVICE_TOKEN=<tileserver-secret>
```

`UPLOAD_API_CALLER_TOKEN` remains a temporary compatibility alias. This is a server-only static service credential, not a user JWT.

Related Plan: [Service Token Name Unification Plan](../plans/service-token-name-unification.md)

Related Progress: [Service Token Name Unification Progress](../progress/service-token-name-unification.md)
