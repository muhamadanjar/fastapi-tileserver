ARG VERSION=0.0.0

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1
WORKDIR /opt/app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Build from monorepo root: docker build -f services/tileserver_api/docker/Dockerfile .
COPY libs/service_auth /opt/service_auth
COPY services/tileserver_api/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --requirement requirements.txt

FROM python:3.11-slim AS runtime

ARG VERSION
LABEL org.opencontainers.image.title="tileserver" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends libpq5 libmagic1 libexpat1 libjpeg62-turbo libpng16-16t64 libtiff6 libwebp7 libgeos-c1t64 libproj25 libnetcdf22 libhdf5-310 libsqlite3-0 libgomp1 libcurl4t64 liblzma5 libzstd1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system tileserver \
    && useradd --system --gid tileserver --create-home tileserver

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/service_auth /opt/service_auth
WORKDIR /app
COPY services/tileserver_api/app ./app
COPY services/tileserver_api/alembic ./alembic
COPY services/tileserver_api/alembic.ini ./alembic.ini

RUN mkdir --parents /app/data /app/logs \
    && chown --recursive tileserver:tileserver /app/data /app/logs

USER tileserver
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
