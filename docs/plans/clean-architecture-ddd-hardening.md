# Plan: Clean Architecture & DDD Hardening

> Related progress: [clean-architecture-ddd-hardening.md](../progress/clean-architecture-ddd-hardening.md)

## Goal

Make dependency direction enforceable and restore the reference-analysis workflow.

## Rules

- Domain contains business concepts and ports only; it must not import framework or infrastructure modules.
- Application/use cases depend on domain and ports, never on infrastructure, presentation, or workers.
- Infrastructure implements ports and owns database, filesystem, HTTP, geospatial I/O, and queue adapters.
- Presentation and workers are entry-point adapters. They translate transport data and assemble dependencies only.

## Scope

1. Add explicit rules to `AGENTS.md` and a boundary test.
2. Replace inner-layer `infrastructure.wiring` imports with dependency injection at entry points.
3. Repair reference-analysis constructor, operation propagation, result/save behaviour, and endpoint delegation, including an idempotent permanent-save workflow.
4. Move database/session interaction behind ports for reference analysis where practical in this change.
5. Run focused tests and the architecture-boundary test.

## Non-goals

- A wholesale replacement of the existing SQLModel persistence model in one change. This requires an incremental ORM/domain separation migration because it affects all repositories and Alembic metadata.
