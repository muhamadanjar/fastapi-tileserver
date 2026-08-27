# Python Dependency Profiles Plan

## Objective

Separate local development and production Python dependencies while keeping the
production image on `python:3.12-slim` and installing the shared
`service_auth` package through Git HTTPS.

## Scope

- Create shared, development, and production requirement files.
- Keep local development on the monorepo checkout of `service_auth` with its
  test extras.
- Make the production Docker build install the public `service_auth` package
  from GitHub over HTTPS, without copying the local library into the image.
- Provide named `dev` and `production` Docker targets.
- Remove SSH deploy-key requirements from the release image build.
- Update setup and release documentation.

## Non-goals

- Change the Python base image from `slim` to Alpine.
- Change application runtime behavior or dependency versions.

## Verification

- Resolve and install both dependency profiles with Python 3.12.
- Run the applicable test suite with the development profile.
- Validate Dockerfile syntax and the release workflow configuration.

Related Progress: [Python Dependency Profiles Progress](../progress/python-dependency-profiles.md)
