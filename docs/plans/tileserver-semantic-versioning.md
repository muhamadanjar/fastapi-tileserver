# Tileserver Semantic Versioning Plan

Define a single default container image version so local and release builds use the semantic Docker tag `tileserver:0.0.1`.

Related Progress: [Tileserver Semantic Versioning Progress](../progress/tileserver-semantic-versioning.md)

## Scope

- Derive the local container version from the latest semantic Git tag.
- Record the version in OCI image metadata.
- Use semantic-release on pushes to `main` or `master` to calculate, tag, and publish GitHub releases automatically.
- Publish a versioned container image to GitHub Container Registry when semantic-release creates a new release.
- Document the build and run commands.
