# Docker Compose: Optional Infrastructure

Create a Compose-based local deployment path that keeps the Tileserver API and
its optional infrastructure independent.

## Goals

- Provide distinct development and production application services using the
  existing Dockerfile targets.
- Start PostgreSQL, RabbitMQ, Redis, and GeoServer only when an explicit
  `infrastructure` Compose profile is selected.
- Keep application services usable with externally managed infrastructure via
  the existing environment variables.
- Document the supported commands and configuration boundaries.

## Design

- `tileserver-dev` binds the source directory and starts Uvicorn reload mode.
- `tileserver` is the production-target service and does not mount source.
- Infrastructure services use the `infrastructure` profile, named volumes, and
  health checks where supported.
- The application services stay outside that profile; their database, broker,
  cache, and GeoServer URLs are supplied through environment variables.

## Acceptance Criteria

- `docker compose config` validates the configuration.
- Development and production build targets are explicit.
- Infrastructure is not started unless its profile is requested.
- Developer documentation describes both managed and external infrastructure
  workflows.

Active progress: [Docker Compose Optional Infrastructure Progress](../progress/docker-compose-optional-infrastructure.md)
