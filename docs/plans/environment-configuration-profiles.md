# Environment Configuration Profiles

Separate configuration used by local Python processes from configuration used
by Docker Compose, so changing a container endpoint cannot accidentally change
normal local development.

## Goals

- Keep `.env` as the configuration profile for local commands such as Uvicorn,
  Celery, Alembic, and tests.
- Use a distinct, ignored `.env.docker` profile for Docker Compose.
- Provide a safe Docker template and Make targets that select it consistently.
- Document how to choose external versus Compose-managed infrastructure.

## Design

- Compose loads `.env.docker` into application containers, while `.env` remains
  untouched and is not read by those containers, including the source-mounted
  development target.
- Docker-only connection settings use `TILESERVER_*` names. Compose translates
  them to the application variables (`DB_*`, `RABBITMQ_URL`, `REDIS_URL`, and
  `GEOSERVER_URL`). This keeps the Docker profile separate from the local
  runtime profile.
- Make targets call Compose with `--env-file .env.docker`; direct Compose use
  follows the same convention.

## Acceptance Criteria

- A developer can create `.env` and `.env.docker` independently from their
  respective example files.
- Local Python commands continue to read only `.env`.
- Docker application services no longer load `.env`.
- The documented Docker commands validate with `docker compose config`.

Active progress: [Environment Configuration Profiles Progress](../progress/environment-configuration-profiles.md)

Feature documentation: [Environment Configuration Profiles](../features/environment-configuration-profiles.md)
