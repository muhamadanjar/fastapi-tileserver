# Docker Compose with Optional Infrastructure

Related Plan: [Docker Compose: Optional Infrastructure](../plans/docker-compose-optional-infrastructure.md)  
Related Progress: [Docker Compose: Optional Infrastructure Progress](../progress/docker-compose-optional-infrastructure.md)

`docker-compose.yml` provides two application profiles and one optional
infrastructure profile:

- `development` starts `tileserver-dev` (Uvicorn reload) and its Celery worker.
  The source directory is mounted into both containers.
- `production` starts the production Dockerfile target and its Celery worker.
- `infrastructure` starts PostGIS, RabbitMQ, Redis, and GeoServer. It is never
  implicitly started by either application profile.

## External infrastructure

Use this when database, broker, cache, or GeoServer is already managed outside
Docker. Set the relevant `TILESERVER_*` values and start only an application
profile:

```bash
make docker-up-dev
# or
make docker-up-prod
```

The defaults point to `host.docker.internal`, which is mapped to the Docker
host. Override them for any remote service, for example:

```bash
export TILESERVER_DB_HOST=db.example.internal
export TILESERVER_RABBITMQ_URL=amqp://user:password@rabbit.example.internal:5672/vhost
make docker-up-prod
```

## Local infrastructure

To use the optional containers, application URLs must address Compose service
names rather than the host. Export the values once for the current shell, then
start both profiles:

```bash
export TILESERVER_DB_HOST=postgres
export TILESERVER_RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
export TILESERVER_REDIS_URL=redis://redis:6379/0
export TILESERVER_GEOSERVER_URL=http://geoserver:8080/geoserver
docker compose --profile infrastructure --profile development up --build
```

For the production Dockerfile target, replace `development` with `production`.
The API is exposed on port `8000` by default; set `TILESERVER_API_PORT` to use a
different host port.

Stop the stack with `make docker-down`. Named volumes preserve application data
and infrastructure data between container restarts.
