# Python Dependency Profiles

Related Plan: [Python Dependency Profiles Plan](../plans/python-dependency-profiles.md)  
Related Progress: [Python Dependency Profiles Progress](../progress/python-dependency-profiles.md)

The service uses Python 3.12 and separates dependencies by environment:

- `requirements.txt` contains packages shared by all environments.
- `requirements-dev.txt` adds the monorepo's editable `service_auth[test]`
  checkout. Use it for local development and tests.
- `requirements-prod.txt` installs the pinned `service_auth` commit from GitHub
  over HTTPS. Use it for production builds.

## Local development

From the service directory, install the development profile:

```bash
pip install -r requirements-dev.txt
```

## Docker targets

The Dockerfile provides two named targets:

- `dev` uses the builder image, includes `service_auth` test extras, and starts
  Uvicorn with `--reload`.
- `production` is the final, minimal `python:3.12-slim` runtime image.

Build the development target with:

```bash
make docker-build-dev
```

## Production image builds

The production Dockerfile remains based on `python:3.12-slim` and uses a
multi-stage build. `service_auth` is installed from its pinned public Git HTTPS
revision only in the builder stage; the source checkout is not copied into the
runtime image.

From the service directory, run:

```bash
make docker-build
```

No SSH agent, deploy key, or BuildKit SSH mount is required.
