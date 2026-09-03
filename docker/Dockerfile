ARG VERSION=0.0.0

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1
WORKDIR /opt/app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends build-essential git libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Build from this service directory.
COPY requirements.txt ./requirements.txt
COPY requirements-prod.txt ./requirements-prod.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --requirement requirements-prod.txt

FROM builder AS dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

# The container development target includes service_auth test extras.
RUN /opt/venv/bin/pip install \
    'base-project-service-auth[test] @ git+https://github.com/muhamadanjar/service_auth.git@f514e99ff224fed80b22b5c54385c4c59f8bc83b'

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM python:3.12-slim AS production

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
WORKDIR /app
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

RUN mkdir --parents /app/data /app/logs \
    && chown --recursive tileserver:tileserver /app/data /app/logs

USER tileserver
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
