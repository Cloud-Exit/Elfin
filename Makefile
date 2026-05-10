DEFAULT_GOAL := help

VENV ?= .venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
BOOTSTRAP_PYTHON ?= $(shell command -v python3.12 || command -v python3.13 || command -v python3.11 || command -v python3.10 || command -v python3)
BUN ?= bun
PIP ?= $(VENV)/bin/pip
MAX_WAIT_SECS ?= 60
CHAT_MODEL ?= gemma-4-E4B-it-Q5_K_M.gguf
CHAT_MMPROJ ?= mmproj-F16.gguf
EMBED_MODEL ?= nomic-embed-text-v1.5.Q8_0.gguf
CHAT_ARGS ?=
FINETUNE_CONFIG ?= ./config/training/elfin-gemma4-local.example.json
FINETUNE_RUN_DIR ?= ./artifacts/training/elfin-gemma4-local
FINETUNE_OUTPUT ?= ./artifacts/training/elfin-gemma4-local-q4_k_m.gguf
FINETUNE_BASELINE_REPORT ?= ./data/evals/baseline-report.json
FINETUNE_TUNED_REPORT ?= ./data/evals/tuned-report.json
FINETUNE_GEN_ARGS ?=
FINETUNE_TRAIN_ARGS ?=
FINETUNE_EXPORT_ARGS ?=
VISION_ARGS ?=

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

.PHONY: help ensure-venv dev dev-local dev-remote build build-frontend dev-frontend typecheck setup setup-python setup-training clean services download-assets download-assets-dry-run dataset-inventory ingest ingest-force ingest-plan ingest-validate train-validate test test-contracts test-install-prep verify-gemma4 smoke-gemma4 smoke-ingestion-live chat vision debug-kiwix verify-slice1 verify-slice1-config verify-slice1-assets verify-slice1-live verify-slice2 verify-slice3 evals-validate evals-dry-run finetune-dataset finetune-generate finetune-validate finetune-train finetune-train-validate finetune-smoke finetune-export finetune-eval db-generate db-push db-migrate db-studio db-seed

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "%-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: ## Build, start services, run Bun server (remote if ELFIN_REMOTE_HOST/RK1_TARGET set)
	@if [ -n "$$ELFIN_REMOTE_HOST" ] || [ -n "$$RK1_TARGET" ]; then \
		$(MAKE) dev-remote; \
	else \
		$(MAKE) dev-local; \
	fi

dev-local: build ## Local: build frontend, start services, wait for health, run Bun server
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
	@echo "Starting Elfin on :8885"
	$(BUN) run src/backend/server.ts

dev-remote: ## Sync project to RK1 via SSH, run remote stack, watch local files (--watch)
	@if [ -z "$$ELFIN_REMOTE_HOST" ] || [ -z "$$ELFIN_REMOTE_HOST_USER" ]; then \
		echo "ERROR: ELFIN_REMOTE_HOST and ELFIN_REMOTE_HOST_USER required"; \
		echo "Example: ELFIN_REMOTE_HOST=rk1.local ELFIN_REMOTE_HOST_USER=elfin make dev"; \
		exit 1; \
	fi
	bash scripts/dev_remote.sh

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

finetune-dataset: ## Build passage manifest from local corpus (PDF/MD)
	$(PYTHON) -m src.training.dataset_builder \
		--source-dir ./data/datasets/raw \
		--out ./data/training/passage-manifest.jsonl \
		--summary-out ./data/training/passage-summary.json

finetune-generate: ## Synthesize SFT dataset via OpenRouter (requires OPENROUTER_API_KEY)
	$(PYTHON) -m src.training.generate_sft_dataset \
		--manifest ./data/training/passage-manifest.jsonl \
		--out ./datasets/training/synthetic/openrouter.jsonl \
		$(FINETUNE_GEN_ARGS)

finetune-validate: ## Validate SFT dataset, detect duplicates/policy violations, emit splits
	$(PYTHON) -m src.training.validate_dataset \
		--dataset-dir ./datasets/training \
		--out ./data/training/dataset-summary.json \
		--splits-out ./datasets/training/splits

finetune-train: ## Run local LoRA SFT (requires config path via FINETUNE_CONFIG)
	$(PYTHON) -m src.training.train --config $(FINETUNE_CONFIG) $(FINETUNE_TRAIN_ARGS)

finetune-train-validate: ## Validate training config + dataset without running training
	$(PYTHON) -m src.training.train --config $(FINETUNE_CONFIG) --skip-train

finetune-smoke: ## Validate dataset + config and write run metadata without training
	$(PYTHON) -m src.training.validate_dataset \
		--dataset-dir ./datasets/training \
		--out ./data/training/dataset-summary.json \
		--splits-out ./datasets/training/splits
	$(PYTHON) -m src.training.train --config $(FINETUNE_CONFIG) --skip-train

finetune-export: ## Merge LoRA adapter and export GGUF artifact with metadata
	$(PYTHON) -m src.training.export \
		--run-dir $(FINETUNE_RUN_DIR) \
		--output $(FINETUNE_OUTPUT) \
		$(FINETUNE_EXPORT_ARGS)

finetune-eval: ## Compare baseline vs tuned eval reports and decide promotion
	$(PYTHON) -m src.training.eval \
		--baseline-report $(FINETUNE_BASELINE_REPORT) \
		--tuned-report $(FINETUNE_TUNED_REPORT) \
		--out ./data/training/eval-gate.json

test: test-contracts ## Run default test suite

test-contracts: ## Run no-docker contract tests
	$(PYTHON) -m unittest discover -s tests

test-install-prep: ## Run unit tests for tools/prepare_image.py
	$(PYTHON) -m unittest tests.test_prepare_image -v

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

chat: ## Start Docker services and open interactive cited RAG chat
	@echo "Starting llama-server + llama-embed + Qdrant + Kiwix via Docker..."
	CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) EMBED_MODEL=$(EMBED_MODEL) docker compose up -d llama-server llama-embed qdrant kiwix
	@echo "Waiting for llama-server..."
	$(call wait_for_http,http://localhost:8081/health,llama-server,llama-server)
	@echo "Waiting for llama-embed..."
	$(call wait_for_http,http://localhost:8082/health,llama-embed,llama-embed)
	@echo "Waiting for Qdrant..."
	$(call wait_for_http,http://localhost:6333/healthz,Qdrant,qdrant)
	@echo "Waiting for Kiwix..."
	$(call wait_for_http,http://localhost:8083/catalog/v2/root.xml,Kiwix,kiwix)
	$(PYTHON) src/cli/chat.py $(CHAT_ARGS)

vision: ## Start Docker services and run multimodal vision test on an image
	@echo "Starting llama-server via Docker..."
	CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) docker compose up -d llama-server
	@echo "Waiting for llama-server..."
	$(call wait_for_http,http://localhost:8081/health,llama-server,llama-server)
	$(PYTHON) src/cli/vision.py --image "$(IMAGE)" $(VISION_ARGS)

debug-kiwix: ## Probe local Kiwix search/article paths for a query
	$(PYTHON) src/infra/debug_kiwix.py

db-generate: ## Generate Prisma client from schema
	$(BUN) x prisma generate

db-push: ## Push schema to SQLite database (dev)
	$(BUN) x prisma db push

db-migrate: ## Create and apply Prisma migration
	$(BUN) x prisma migrate dev

db-studio: ## Open Prisma Studio GUI
	$(BUN) x prisma studio

db-seed: ## Seed initial admin user
	$(BUN) run src/backend/seed.ts

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

ensure-venv:
	@BOOTSTRAP="$$(basename $(BOOTSTRAP_PYTHON))"; \
	EXPECTED="$$( $(BOOTSTRAP_PYTHON) -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' )"; \
	if [ -x "$(VENV)/bin/python" ]; then \
		CURRENT="$$( $(VENV)/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' )"; \
		if [ "$$CURRENT" != "$$EXPECTED" ]; then \
			echo "Recreating $(VENV) with $$BOOTSTRAP (have $$CURRENT, need $$EXPECTED)"; \
			rm -rf $(VENV); \
		fi; \
	fi; \
	if [ ! -x "$(VENV)/bin/python" ]; then \
		echo "Creating $(VENV) with $$BOOTSTRAP"; \
		$(BOOTSTRAP_PYTHON) -m venv $(VENV); \
	fi

setup: ensure-venv ## Create venv, install Python deps, install Bun deps
	$(BUN) install
	$(PIP) install -r requirements.txt

setup-python: ensure-venv ## Create venv and install Python deps only
	$(PIP) install -r requirements.txt

setup-training: ensure-venv ## Install optional local fine-tuning dependencies
	$(PIP) install -r requirements-training.txt

clean: ## Remove generated build/test artifacts (keeps data/models qdrant zim media)
	rm -rf static/dist .pytest_cache data/evals data/ingestion data/training
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
