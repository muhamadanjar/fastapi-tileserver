IMAGE_NAME ?= tileserver
VERSION ?= 0.0.1
IMAGE_TAG := $(IMAGE_NAME):$(VERSION)
BUILD_CONTEXT := ../..

.PHONY: docker-build docker-run

docker-build:
	docker build --build-arg VERSION=$(VERSION) -f docker/Dockerfile -t $(IMAGE_TAG) $(BUILD_CONTEXT)

docker-run:
	docker run --rm -p 8000:8000 $(IMAGE_TAG)
