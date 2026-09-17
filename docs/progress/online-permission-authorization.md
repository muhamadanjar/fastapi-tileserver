# Tileserver Online Permission Authorization Progress

Related Plan: [Tileserver Online Permission Authorization Plan](../plans/online-permission-authorization.md)

## Status

In progress — authorization middleware exists but was disabled at the application
composition root and used a protected-prefix policy.

- [x] Define and confirm the public/managed route boundary.
- [x] Enable middleware and switch to default-protected public allowlist.
- [x] Enforce `tiles.manage` for durable public-workspace result saves.
- [x] Add and run focused regression coverage (`29 passed`).
- [x] Update configuration examples and publish feature documentation.
- [ ] Verify against a running User Management deployment. Local `localhost:8000`
  currently serves the dashboard and returns `404` for `/auth/authorize`; set
  `USERMANAGEMENT_API_URL` to the internal API endpoint before this check.
