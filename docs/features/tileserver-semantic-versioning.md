# Tileserver Container Semantic Versioning

Tileserver's default container image is `tileserver:0.0.1`. The version is semantic (`MAJOR.MINOR.PATCH`) and is written to the image's `org.opencontainers.image.version` label.

Build it from this service directory:

```bash
make docker-build
```

Run the image:

```bash
make docker-run
```

To build a subsequent release, override `VERSION`:

```bash
make docker-build VERSION=0.0.2
```

The Make target uses the monorepo root as the Docker build context, allowing the Dockerfile to copy the shared `libs/service_auth` package.

Related Plan: [Tileserver Semantic Versioning Plan](../plans/tileserver-semantic-versioning.md)

Related Progress: [Tileserver Semantic Versioning Progress](../progress/tileserver-semantic-versioning.md)
