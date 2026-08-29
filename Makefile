IMAGE_NAME ?= tileserver
VERSION ?= $(shell git describe --tags --abbrev=0 --match '[0-9]*.[0-9]*.[0-9]*' 2>/dev/null || echo 0.0.0)
IMAGE_TAG := $(IMAGE_NAME):$(VERSION)
BUILD_CONTEXT := .

.PHONY: docker-build docker-build-dev docker-run docker-infra-up docker-up-dev docker-up-prod docker-down

docker-build:
	docker build --target production --build-arg VERSION=$(VERSION) -f docker/Dockerfile -t $(IMAGE_TAG) $(BUILD_CONTEXT)

docker-build-dev:
	docker build --target dev --build-arg VERSION=$(VERSION) -f docker/Dockerfile -t $(IMAGE_NAME):dev $(BUILD_CONTEXT)

docker-run:
	docker run --rm -p 8000:8000 $(IMAGE_TAG)

# Compose keeps infrastructure optional. Set TILESERVER_* variables when using
# the local infrastructure profile; otherwise the app uses external endpoints.
docker-infra-up:
	docker compose --profile infrastructure up --detach

docker-up-dev:
	docker compose --profile development up --build

docker-up-prod:
	docker compose --profile production up --build --detach

docker-down:
	docker compose down
