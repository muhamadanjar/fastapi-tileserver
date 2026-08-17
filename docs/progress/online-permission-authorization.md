# Tileserver Online Permission Authorization Progress

Related Plan: [Tileserver Online Permission Authorization Plan](../plans/online-permission-authorization.md)

## Status

Implemented — awaiting end-to-end deployment verification against User Management.

- [x] Define initial route permission matrix.
- [x] Implement online authorization middleware.
- [x] Add unit coverage for allow and denial; unavailable User Management is mapped fail-closed to `503`.
- [x] Run focused middleware tests.
- [ ] Verify against a running User Management deployment and publish feature documentation.
