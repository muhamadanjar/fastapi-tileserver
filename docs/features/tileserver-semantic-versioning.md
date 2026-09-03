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

Docker Compose receives that same resolved version automatically. To publish a
release image manually, authenticate with a GitHub PAT that has
`packages:write`, check out the matching semantic Git tag, then run:

```bash
make docker-login-ghcr
make docker-publish
```

`docker-publish` refuses to run unless `HEAD` is exactly on the resolved
semantic Git tag. It builds and pushes both
`ghcr.io/muhamadanjar/tileserver:<version>` and
`ghcr.io/muhamadanjar/tileserver:latest`. Override `GHCR_OWNER` only when
publishing the image to another GitHub owner or organization.

Run the image:

```bash
make docker-run
```

`make docker-build` derives the image tag from the highest semantic Git tag in the repository. Before the first release, it uses `tileserver:0.0.0`.

## GitHub Container Registry

When semantic-release creates a new release, the same workflow builds and publishes `ghcr.io/muhamadanjar/tileserver:<version>` and `ghcr.io/muhamadanjar/tileserver:latest`. It does not publish an image when no new release is created.

The production build installs the pinned public `muhamadanjar/service_auth` revision through Git HTTPS. No deploy key or SSH agent is required for local or CI image builds.

Related Plan: [Tileserver Semantic Versioning Plan](../plans/tileserver-semantic-versioning.md)

Related Progress: [Tileserver Semantic Versioning Progress](../progress/tileserver-semantic-versioning.md)
