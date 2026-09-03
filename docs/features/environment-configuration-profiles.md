# Environment Configuration Profiles

Related Plan: [Environment Configuration Profiles](../plans/environment-configuration-profiles.md)  
Related Progress: [Environment Configuration Profiles Progress](../progress/environment-configuration-profiles.md)

The service keeps local Python configuration and Docker Compose configuration
in separate files:

| Usage | Configuration file | Commands |
|---|---|---|
| Local development | `.env` | Uvicorn, Celery, Alembic, tests |
| Docker Compose | `.env.docker` | `make docker-*` or Compose with `--env-file .env.docker` |

Both files are ignored by Git. Start from the matching tracked template:

```bash
cp .env.example .env
cp .env.docker.example .env.docker
```

## Local Python usage

Set `DB_*`, `RABBITMQ_URL`, `REDIS_URL`, and `GEOSERVER_*` directly in `.env`.
Local commands retain the existing behavior:

```bash
uvicorn app.main:app --reload --port 8080
celery -A app.workers.celery_app worker --loglevel=info
```

## Docker Compose usage

Set Docker infrastructure endpoints in `.env.docker` with `TILESERVER_*`
variables. Compose maps those values to the application's normal `DB_*`,
`RABBITMQ_URL`, `REDIS_URL`, and `GEOSERVER_URL` variables. It also loads any
other application settings in `.env.docker`, such as authentication secrets.

The template targets the Compose service names, so local infrastructure can be
started with:

```bash
docker compose --env-file .env.docker --profile infrastructure --profile development up --build
```

For externally managed infrastructure, change the corresponding
`TILESERVER_*` values in `.env.docker`, then start only the application:

```bash
make docker-up-dev
```

All `make docker-*` Compose targets select `.env.docker` automatically. To use
a differently named Docker profile, pass `COMPOSE_ENV_FILE`, for example:

```bash
make COMPOSE_ENV_FILE=.env.staging docker-up-prod
```

The application honors `TILESERVER_ENV_FILE`; Compose sets it to
`/app/.env.docker`. This prevents the mounted source directory's local `.env`
from affecting Docker development containers.
