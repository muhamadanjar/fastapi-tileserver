# Tileserver Container Semantic Versioning

Tileserver versions are generated automatically by semantic-release. Each release is semantic (`MAJOR.MINOR.PATCH`), becomes a Git tag and GitHub Release, and is written to the container's `org.opencontainers.image.version` label when built.

## GitHub releases

GitHub releases use `MAJOR.MINOR.PATCH` while Docker images use `tileserver:MAJOR.MINOR.PATCH`. On pushes to `main` or `master`, semantic-release uses Conventional Commits to calculate the version, create its Git tag, and publish the GitHub Release. The corresponding container image tag is `tileserver:MAJOR.MINOR.PATCH`.

```bash
# A Conventional Commit merged to main or master creates the release automatically.
git push origin main
```

Build it from this service directory:

```bash
make docker-build
```

Run the image:

```bash
make docker-run
```

`make docker-build` derives the image tag from the latest semantic Git tag. Before the first release, it uses `tileserver:0.0.0`.

The Make target uses the monorepo root as the Docker build context, allowing the Dockerfile to copy the shared `libs/service_auth` package.

Related Plan: [Tileserver Semantic Versioning Plan](../plans/tileserver-semantic-versioning.md)

Related Progress: [Tileserver Semantic Versioning Progress](../progress/tileserver-semantic-versioning.md)
