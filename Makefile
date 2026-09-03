IMAGE_NAME ?= tileserver
VERSION ?= $(shell git tag --list '[0-9]*.[0-9]*.[0-9]*' --sort=-version:refname 2>/dev/null | head -n 1 | awk 'NF { print; found=1 } END { if (!found) print "0.0.0" }')
IMAGE_TAG := $(IMAGE_NAME):$(VERSION)
GHCR_OWNER ?= muhamadanjar
GHCR_IMAGE ?= ghcr.io/$(GHCR_OWNER)/$(IMAGE_NAME)
BUILD_CONTEXT := .
COMPOSE_ENV_FILE ?= .env.docker
COMPOSE := VERSION=$(VERSION) TILESERVER_DOCKER_ENV_FILE=$(COMPOSE_ENV_FILE) docker compose --env-file $(COMPOSE_ENV_FILE)

.PHONY: docker-build docker-build-dev docker-run docker-login-ghcr docker-publish check-release-version docker-infra-up docker-up-dev docker-up-prod docker-down

docker-build:
	docker build --target production --build-arg VERSION=$(VERSION) -f docker/Dockerfile -t $(IMAGE_TAG) $(BUILD_CONTEXT)

docker-build-dev:
	docker build --target dev --build-arg VERSION=$(VERSION) -f docker/Dockerfile -t $(IMAGE_NAME):dev $(BUILD_CONTEXT)

docker-run:
	docker run --rm -p 8000:8000 $(IMAGE_TAG)

# Authenticate once with a GitHub PAT that has packages:write before publishing.
docker-login-ghcr:
	docker login ghcr.io

# Publishing is restricted to the semantic version tag at HEAD so an untagged
# commit cannot overwrite an existing release image by accident.
check-release-version:
	@test "$(VERSION)" != "0.0.0" || (echo "No semantic Git tag found; set a release tag before publishing." >&2; exit 1)
	@git tag --points-at HEAD --list "$(VERSION)" | grep --fixed-strings --line-regexp "$(VERSION)" >/dev/null || (echo "VERSION=$(VERSION) must be a semantic Git tag pointing at HEAD." >&2; exit 1)

docker-publish: check-release-version
	docker build --target production --build-arg VERSION=$(VERSION) -f docker/Dockerfile \
		-t $(IMAGE_TAG) \
		-t $(GHCR_IMAGE):$(VERSION) \
		-t $(GHCR_IMAGE):latest \
		$(BUILD_CONTEXT)
	docker push $(GHCR_IMAGE):$(VERSION)
	docker push $(GHCR_IMAGE):latest

# Compose keeps infrastructure optional. Set TILESERVER_* variables when using
# the local infrastructure profile; otherwise the app uses external endpoints.
docker-infra-up:
	$(COMPOSE) --profile infrastructure up --detach

docker-up-dev:
	$(COMPOSE) --profile development up --build

docker-up-prod:
	$(COMPOSE) --profile production up --build --detach

docker-down:
	$(COMPOSE) down
