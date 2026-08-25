Related Plan: [Tileserver API OAuth Service Authorization Migration](../plans/oauth-service-authorization-migration.md)

# Tileserver API OAuth Service Authorization Progress

## Status

In progress.

## Checklist

- [x] Integrate shared client-credentials token provider.
- [x] Migrate API and worker Upload clients to OAuth.
- [x] Retain observable deprecated static-token fallback during dual mode.
- [x] Ensure tokens never enter task payloads or persistence.
- [x] Verify audience, scope, revocation, outage, renewal, and redaction behavior.
- [x] Confirm existing `/auth/authorize` behavior remains unchanged.
- [ ] Remove legacy configuration after Upload reports zero static usage.
- [x] Publish feature documentation.
- [x] Add and verify an internal-package-aware container build.
- [x] Complete `.env.example` audience/scope and secret-manager guidance.
- [x] Count deprecated static-token use at request time, not only at startup.
