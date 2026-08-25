# Tileserver Semantic Versioning Plan

Define a single default container image version so local and release builds use the semantic Docker tag `tileserver:0.0.1`.

Related Progress: [Tileserver Semantic Versioning Progress](../progress/tileserver-semantic-versioning.md)

## Scope

- Provide a build target with image name `tileserver` and version `0.0.1`.
- Record the version in OCI image metadata.
- Validate the semantic version on pushes to `main` or `master` and create the matching GitHub release in GitHub Actions.
- Document the build and run commands.
