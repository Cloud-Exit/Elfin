DEFAULT_GOAL := help

PYTHON ?= python3
BUN ?= bun
PIP ?= $(VENV)/bin/pip
VENV ?= .venv
MAX_WAIT_SECS ?= 60
CHAT_MODEL ?= gemma-4-E4B-it-Q5_K_M.gguf
CHAT_MMPROJ ?= mmproj-F16.gguf
EMBED_MODEL ?= nomic-embed-text-v1.5.Q8_0.gguf

define wait_for_http
	@for i in $$(seq 1 $(MAX_WAIT_SECS)); do \
		curl -sf $(1) > /dev/null 2>&1 && exit 0; \
		printf '.'; \
		sleep 1; \
	done; \
	echo ""; \
	echo "Timed out waiting for $(2)"; \
	docker compose ps $(3) || true; \
	echo "--- recent logs: $(3) ---"; \
	docker compose logs --tail=200 $(3) || true; \
	exit 1
endef

.PHONY: help dev build build-frontend dev-frontend typecheck setup setup-python clean services download-assets download-assets-dry-run dataset-inventory ingest ingest-force ingest-plan ingest-validate train-validate test test-contracts verify-gemma4 smoke-gemma4 smoke-ingestion-live verify-slice1 verify-slice1-config verify-slice1-assets verify-slice1-live verify-slice2 verify-slice3 evals-validate evals-dry-run

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "%-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: build ## Build frontend, start services, wait for health, run Bun server
	@echo "Starting services..."
	CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) EMBED_MODEL=$(EMBED_MODEL) docker compose up -d llama-server llama-embed qdrant kiwix
	@echo "Waiting for llama-server..."
	$(call wait_for_http,http://localhost:8081/health,llama-server,llama-server)
	@echo "Waiting for llama-embed..."
	$(call wait_for_http,http://localhost:8082/health,llama-embed,llama-embed)
	@echo "Waiting for Qdrant..."
	$(call wait_for_http,http://localhost:6333/healthz,Qdrant,qdrant)
	@echo "Waiting for Kiwix..."
	$(call wait_for_http,http://localhost:8083/catalog/v2/root.xml,Kiwix,kiwix)
	@echo "Starting Elfin on :8085"
	$(BUN) run src/backend/server.ts

services: ## Start Docker services only
	CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) EMBED_MODEL=$(EMBED_MODEL) docker compose up -d

download-assets: ## Download runtime models, raw docs, training base model, and ZIM assets
	bash scripts/download_assets.sh

download-assets-dry-run: ## Print planned asset downloads without network traffic
	DRY_RUN=1 bash scripts/download_assets.sh

dataset-inventory: ## Build dataset inventory from local raw docs and ZIMs
	$(PYTHON) src/infra/build_dataset_inventory.py

build: build-frontend ## Build frontend assets

build-frontend: ## Build frontend bundle (minified)
	$(BUN) build src/frontend/main.tsx --outdir static/dist --minify

dev-frontend: ## Watch and rebuild frontend assets
	$(BUN) build src/frontend/main.tsx --outdir static/dist --watch

ingest: ## Run ingestion pipeline (requires embed + Qdrant running)
	$(PYTHON) src/ingestion/pipeline.py

ingest-force: ## Re-ingest all documents
	$(PYTHON) src/ingestion/pipeline.py --force

ingest-plan: ## Dry-run ingestion planning and write report
	$(PYTHON) src/ingestion/pipeline.py --dry-run

ingest-validate: ## Validate source corpus and write manifest
	$(PYTHON) src/ingestion/validate_sources.py

train-validate: ## Validate fine-tune dataset and write summary
	$(PYTHON) src/training/validate_dataset.py

test: test-contracts ## Run default test suite

test-contracts: ## Run no-docker contract tests
	$(PYTHON) -m unittest discover -s tests

typecheck: ## Run TypeScript type-check
	$(BUN) x tsc --noEmit

verify-gemma4: ## Start llama-server with Docker and verify Gemma 4 health
	@echo "Starting llama-server via Docker..."
	CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) docker compose up -d llama-server
	@echo "Waiting for llama-server..."
	$(call wait_for_http,http://localhost:8081/health,llama-server,llama-server)
	$(PYTHON) src/infra/verify_gemma4.py --no-launch

smoke-gemma4: ## Start llama-server with Docker and run Gemma 4 chat smoke test
	@echo "Starting llama-server via Docker..."
	CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) docker compose up -d llama-server
	@echo "Waiting for llama-server..."
	$(call wait_for_http,http://localhost:8081/health,llama-server,llama-server)
	$(PYTHON) src/infra/verify_gemma4.py --chat --no-launch

smoke-ingestion-live: ## Start Docker services and run live ingestion smoke test
	@echo "Starting llama-embed + Qdrant via Docker..."
	EMBED_MODEL=$(EMBED_MODEL) docker compose up -d llama-embed qdrant
	@echo "Waiting for llama-embed..."
	$(call wait_for_http,http://localhost:8082/health,llama-embed,llama-embed)
	@echo "Waiting for Qdrant..."
	$(call wait_for_http,http://localhost:6333/healthz,Qdrant,qdrant)
	$(PYTHON) src/infra/smoke_ingestion_live.py

verify-slice1: ## Verify Slice 1 config and local assets
	$(PYTHON) src/infra/verify_slice1.py

verify-slice1-config: ## Verify Slice 1 static compose/config only
	$(PYTHON) src/infra/verify_slice1.py --config-only

verify-slice1-assets: ## Verify Slice 1 local model/ZIM assets only
	$(PYTHON) src/infra/verify_slice1.py --assets-only

verify-slice1-live: ## Verify Slice 1 and probe live endpoints
	$(PYTHON) src/infra/verify_slice1.py --check-endpoints

verify-slice2: ## Verify Slice 2 dataset procurement outputs
	$(PYTHON) src/infra/verify_slice2.py

verify-slice3: ## Verify Slice 3 dry-run ingestion planning
	$(PYTHON) src/ingestion/pipeline.py --dry-run --report-out ./data/ingestion/slice3-dry-run.json

evals-validate: ## Validate evaluation scenarios
	$(PYTHON) src/evals/validate.py

evals-dry-run: ## Dry-run evaluation harness without model calls
	$(PYTHON) src/evals/run.py --dry-run

$(VENV)/bin/python:
	$(PYTHON) -m venv $(VENV)

setup: $(VENV)/bin/python ## Create venv, install Python deps, install Bun deps
	$(BUN) install
	$(PIP) install -r requirements.txt

setup-python: $(VENV)/bin/python ## Create venv and install Python deps only
	$(PIP) install -r requirements.txt

clean: ## Remove generated build/test artifacts (keeps data/models qdrant zim media)
	rm -rf static/dist .pytest_cache data/evals data/ingestion data/training
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
