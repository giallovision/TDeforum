# TDeforum ops. `make` (or `make help`) lists the targets.
#
#   make build         build tdeforum-a1111:local (BuildKit cache mounts: rebuilds re-use downloads)
#   make up            start the image named by A1111_TAG (default local) and wait for the API
#   make bake          freeze :local as :stable (+ a dated stable-YYYYMMDD-HHMM tag)
#   make save / load   snapshot :stable to a tarball / restore it without rebuilding
#   make lock          pin Dockerfile refs to the commits running right now
#   make unload/reload free / restore VRAM without restarting the container

SHELL := /bin/bash
-include .env
export

COMPOSE      ?= docker compose
SERVICE      ?= a1111-api
CONTAINER    ?= tdeforum-a1111
IMAGE        ?= $(or $(A1111_IMAGE),tdeforum-a1111)
TAG          ?= $(or $(A1111_TAG),local)
API          ?= http://127.0.0.1:7865
STAMP        := $(shell date +%Y%m%d-%H%M)
GZIP         := $(shell command -v pigz 2>/dev/null || echo gzip)
SNAPSHOT_DIR ?= $(or $(IMAGE_SNAPSHOT_DIR),$(if $(SHARED_NVME_MOUNT),$(SHARED_NVME_MOUNT)/tdeforum/images,$(CURDIR)/.images))
SNAPSHOT     ?= $(SNAPSHOT_DIR)/$(IMAGE)_stable.tar.gz

.DEFAULT_GOAL := help
.PHONY: help build rebuild up down stop start restart logs wait shell ps versions lock \
        bake rollback images save load unload reload test doctor

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-9s\033[0m %s\n", $$1, $$2}'

build: ## Build the :local image (never overwrites :stable)
	A1111_TAG=local DOCKER_BUILDKIT=1 $(COMPOSE) build $(SERVICE)

rebuild: ## Build :local ignoring the layer cache (wheel downloads still cached)
	A1111_TAG=local DOCKER_BUILDKIT=1 $(COMPOSE) build --no-cache $(SERVICE)

up: ## Start the A1111_TAG image (no rebuild if present) and wait for the API
	@docker image inspect $(IMAGE):$(TAG) >/dev/null 2>&1 || [ "$(TAG)" = local ] || \
	  { echo "$(IMAGE):$(TAG) not found: run 'make bake' or 'make load'"; exit 1; }
	$(COMPOSE) up -d $(SERVICE)
	@bash docker/tools/wait_healthy.sh $(CONTAINER) 600 $(API)

down: ## Stop and remove the container (named volumes are kept)
	$(COMPOSE) down

stop: ## Stop the container (keeps it for a fast start)
	$(COMPOSE) stop $(SERVICE)

start: ## Start a stopped container and wait for the API
	$(COMPOSE) start $(SERVICE)
	@bash docker/tools/wait_healthy.sh $(CONTAINER) 600 $(API)

restart: ## Restart the container and wait for the API
	$(COMPOSE) restart $(SERVICE)
	@bash docker/tools/wait_healthy.sh $(CONTAINER) 600 $(API)

logs: ## Follow container logs
	$(COMPOSE) logs -f --tail=200 $(SERVICE)

wait: ## Block until the API answers (10 min timeout)
	@bash docker/tools/wait_healthy.sh $(CONTAINER) 600 $(API)

shell: ## Shell inside the container
	docker exec -it $(CONTAINER) bash

ps: ## Container status and health
	$(COMPOSE) ps

versions: ## torch / xformers versions and source commits inside the container
	@docker exec -i $(CONTAINER) bash -s < docker/tools/versions.sh

lock: ## Pin Dockerfile *_REF defaults to the commits running now
	@bash docker/tools/lock_refs.sh $(CONTAINER)

bake: ## Promote :local to :stable and keep a dated stable-YYYYMMDD-HHMM copy
	@docker image inspect $(IMAGE):local >/dev/null
	docker tag $(IMAGE):local $(IMAGE):stable
	docker tag $(IMAGE):local $(IMAGE):stable-$(STAMP)
	@echo "Baked $(IMAGE):stable (= stable-$(STAMP)). Set A1111_TAG=stable in .env, then: make up"

rollback: ## Point :stable back at an older bake: make rollback TO=stable-20261016-1200
	@test -n "$(TO)" || { echo "usage: make rollback TO=<tag>   (see: make images)"; exit 1; }
	docker tag $(IMAGE):$(TO) $(IMAGE):stable

images: ## List local image tags
	@docker images $(IMAGE)

save: ## Save :stable to a .tar.gz under SNAPSHOT_DIR for offline restore
	@mkdir -p $(SNAPSHOT_DIR)
	docker save $(IMAGE):stable | $(GZIP) -1 > $(SNAPSHOT).partial && mv $(SNAPSHOT).partial $(SNAPSHOT)
	@ls -lh $(SNAPSHOT)

load: ## Restore :stable from that tarball (no build, no downloads)
	docker load -i $(SNAPSHOT)

unload: ## Free VRAM (unload the checkpoint), container stays up
	@curl -fsS -X POST $(API)/sdapi/v1/unload-checkpoint >/dev/null && echo "checkpoint unloaded"

reload: ## Load the checkpoint back into VRAM
	@curl -fsS -X POST $(API)/sdapi/v1/reload-checkpoint >/dev/null && echo "checkpoint reloaded"

test: ## Unit tests for scripts/tdeforum (no TouchDesigner needed)
	python3 -m unittest discover -s tests

doctor: ## GPU, API and persistent-volume checks
	@docker exec $(CONTAINER) nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader \
	  || echo "GPU: not visible in $(CONTAINER)"
	@curl -fsS $(API)/internal/ping >/dev/null && echo "A1111 API: up" || echo "A1111 API: DOWN"
	@curl -fsS $(API)/deforum_api/jobs >/dev/null && echo "Deforum API: up" || echo "Deforum API: DOWN"
	@docker volume ls --format '{{.Name}}' | grep -E '_(a1111_state|a1111_cache|deforum_models|controlnet_annotators)$$' \
	  || echo "no persistent volumes yet (the first 'make up' creates them)"
