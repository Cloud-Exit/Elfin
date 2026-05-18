DEFAULT_GOAL := help

VENV ?= .venv
PYTHON ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
BOOTSTRAP_PYTHON ?= $(shell command -v python3.12 || command -v python3.13 || command -v python3.11 || command -v python3.10 || command -v python3)
BUN ?= bun
PIP ?= $(VENV)/bin/pip
MAX_WAIT_SECS ?= 60
TARGET ?= local
CHAT_MODEL ?= gemma-4-E2B-it-IQ4_XS.gguf
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

define wait_for_llm
	@for i in $$(seq 1 $(MAX_WAIT_SECS)); do \
		curl -sf http://localhost:8081/health > /dev/null 2>&1 && exit 0; \
		printf '.'; \
		sleep 1; \
	done; \
	echo ""; \
	echo "Timed out waiting for llama-server"; \
	if [ "$(TARGET)" = "rockchip" ]; then \
		echo "--- recent logs: rk-llama.cpp ---"; \
		tail -200 data/logs/rk-llama-server.log 2>/dev/null || true; \
	else \
		docker compose ps llama-server || true; \
		echo "--- recent logs: llama-server ---"; \
		docker compose logs --tail=200 llama-server || true; \
	fi; \
	exit 1
endef

define start_llm
	@if [ "$(TARGET)" = "rockchip" ]; then \
		echo "Starting rk-llama.cpp RKNPU2 llama-server..."; \
		docker compose rm -sf llama-server >/dev/null 2>&1 || true; \
		bash scripts/rk_llama_cpp.sh server-bg; \
	else \
		echo "Starting llama-server via Docker..."; \
		CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) docker compose up -d llama-server; \
	fi
endef

define start_rag_services
	@if [ "$(TARGET)" = "rockchip" ]; then \
		echo "Starting llama-embed + Qdrant + Kiwix via Docker; llama-server via rk-llama.cpp..."; \
		docker compose rm -sf llama-server >/dev/null 2>&1 || true; \
		EMBED_MODEL=$(EMBED_MODEL) docker compose up -d llama-embed qdrant kiwix; \
		bash scripts/rk_llama_cpp.sh server-bg; \
	else \
		echo "Starting llama-server + llama-embed + Qdrant + Kiwix via Docker..."; \
		CHAT_MODEL=$(CHAT_MODEL) CHAT_MMPROJ=$(CHAT_MMPROJ) EMBED_MODEL=$(EMBED_MODEL) docker compose up -d llama-server llama-embed qdrant kiwix; \
	fi
endef

.PHONY: help ensure-venv dev dev-local dev-remote install-remote build build-frontend dev-frontend typecheck setup setup-python setup-training clean services download-assets download-assets-dry-run dataset-inventory ingest ingest-force ingest-remote ingest-remote-force ingest-plan ingest-validate train-validate test test-contracts test-install-prep verify-gemma4 smoke-gemma4 smoke-ingestion-live chat vision debug-kiwix verify-slice1 verify-slice1-config verify-slice1-assets verify-slice1-live verify-slice2 verify-slice3 evals-validate evals-dry-run finetune-dataset finetune-generate finetune-validate finetune-train finetune-train-validate finetune-smoke finetune-export finetune-eval db-generate db-push db-migrate db-studio db-seed

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "%-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: ## Build, start services, run Bun server (set TARGET=rockchip for RK1 NPU backend)
	@if [ -n "$$ELFIN_REMOTE_HOST" ] || [ -n "$$RK1_TARGET" ]; then \
		if [ -n "$$RK1_TARGET" ] && [ -z "$$TARGET" ]; then \
			TARGET=rockchip $(MAKE) dev-remote; \
		else \
			$(MAKE) dev-remote; \
		fi; \
	else \
		$(MAKE) dev-local; \
	fi

dev-local: build ## Local: build frontend, start target services, wait for health, run Bun server
	$(call start_rag_services)
	@echo "Waiting for llama-server..."
	$(call wait_for_llm)
	@echo "Waiting for llama-embed..."
	$(call wait_for_http,http://localhost:8082/health,llama-embed,llama-embed)
	@echo "Waiting for Qdrant..."
	$(call wait_for_http,http://localhost:6333/healthz,Qdrant,qdrant)
	@echo "Waiting for Kiwix..."
	$(call wait_for_http,http://localhost:8083/catalog/v2/root.xml,Kiwix,kiwix)
	@echo "Starting Elfin on :8885"
	$(BUN) run src/backend/server.ts

dev-remote: ## Sync project to RK1 via SSH, run target stack, watch local files (--watch)
	@if [ -z "$$ELFIN_REMOTE_HOST" ] || [ -z "$$ELFIN_REMOTE_HOST_USER" ]; then \
		echo "ERROR: ELFIN_REMOTE_HOST and ELFIN_REMOTE_HOST_USER required"; \
		echo "Example: ELFIN_REMOTE_HOST=rk1.local ELFIN_REMOTE_HOST_USER=elfin make dev"; \
		exit 1; \
	fi
	bash scripts/dev_remote.sh

install-remote: build-frontend ## Build, sync, generate .env, install systemd services + browser autostart on remote
	@if [ -z "$$ELFIN_REMOTE_HOST" ] || [ -z "$$ELFIN_REMOTE_HOST_USER" ]; then \
		echo "ERROR: ELFIN_REMOTE_HOST and ELFIN_REMOTE_HOST_USER required"; \
		exit 1; \
	fi
	@REMOTE_PATH="$${ELFIN_REMOTE_PATH:-$${ELFIN_DATA_PATH:-/home/$$ELFIN_REMOTE_HOST_USER/elfin}}"; \
	DATA_PATH="$${ELFIN_DATA_PATH:-$$REMOTE_PATH}"; \
	TARGET="$${TARGET:-rockchip}"; \
	SSH_PORT="$${ELFIN_REMOTE_PORT:-22}"; \
	SSH_TARGET="$$ELFIN_REMOTE_HOST_USER@$$ELFIN_REMOTE_HOST"; \
	SSH_OPTS="-p $$SSH_PORT -o StrictHostKeyChecking=accept-new"; \
	CHAT_MODEL="$${CHAT_MODEL:-gemma-4-E2B-it-IQ4_XS.gguf}"; \
	CHAT_MMPROJ="$${CHAT_MMPROJ:-mmproj-F16.gguf}"; \
	EMBED_MODEL="$${EMBED_MODEL:-nomic-embed-text-v1.5.Q8_0.gguf}"; \
	CHAT_CTX_SIZE="$${CHAT_CTX_SIZE:-4096}"; \
	ELFIN_PORT="$${ELFIN_PORT:-8885}"; \
	DEMO_MODE="$${DEMO_MODE:-true}"; \
	echo "[install] syncing project to $$SSH_TARGET:$$REMOTE_PATH..."; \
	ssh $$SSH_OPTS $$SSH_TARGET "mkdir -p $$REMOTE_PATH"; \
	rsync -az --progress --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		--exclude=.git/ \
		--exclude=node_modules/ \
		--exclude=.venv/ \
		--exclude=__pycache__/ \
		--exclude='*.pyc' \
		--exclude=.DS_Store \
		--exclude=.env \
		./ "$$SSH_TARGET:$$REMOTE_PATH/"; \
	if ssh $$SSH_OPTS $$SSH_TARGET "test -f $$REMOTE_PATH/.env"; then \
		echo "[install] .env already exists on remote, skipping (edit manually on remote)"; \
	else \
		echo "[install] generating .env (TARGET=$$TARGET, MODEL=$$CHAT_MODEL)..."; \
		ENV_TMP=$$(mktemp); \
		printf '%s\n' \
			"TARGET=$$TARGET" \
			"ELFIN_DATA_PATH=$$DATA_PATH" \
			"LLAMA_IMAGE=$${LLAMA_IMAGE:-ghcr.io/ggml-org/llama.cpp:server}" \
			"LLAMA_NGL=$${LLAMA_NGL:-0}" \
			"LLAMA_THREADS=$${LLAMA_THREADS:-6}" \
			"CHAT_MODEL=$$CHAT_MODEL" \
			"CHAT_MMPROJ=$$CHAT_MMPROJ" \
			"RK_LLAMA_CPP_VISION=$${RK_LLAMA_CPP_VISION:-1}" \
			"EMBED_MODEL=$$EMBED_MODEL" \
			"CHAT_CTX_SIZE=$$CHAT_CTX_SIZE" \
			"ELFIN_PORT=$$ELFIN_PORT" \
			"ELFIN_INFERENCE_ENDPOINT=$${ELFIN_INFERENCE_ENDPOINT:-http://localhost:8081}" \
			"ELFIN_EMBED_ENDPOINT=$${ELFIN_EMBED_ENDPOINT:-http://localhost:8082}" \
			"QDRANT_URL=$${QDRANT_URL:-http://localhost:6333}" \
			"KIWIX_URL=$${KIWIX_URL:-http://localhost:8083}" \
			"DATABASE_URL=$${DATABASE_URL:-file:$$DATA_PATH/elfin.db}" \
			"ELFIN_SOURCE_DIR=$${ELFIN_SOURCE_DIR:-$$DATA_PATH/datasets/raw}" \
			"DEMO_MODE=$$DEMO_MODE" \
			> "$$ENV_TMP"; \
		ssh $$SSH_OPTS $$SSH_TARGET "cat > $$REMOTE_PATH/.env" < "$$ENV_TMP"; \
		rm -f "$$ENV_TMP"; \
	fi; \
	echo "[install] generating systemd units for $$SSH_TARGET ($$REMOTE_PATH)..."; \
	ssh $$SSH_OPTS $$SSH_TARGET " \
		set -e; \
		BUN_PATH=\$$(command -v bun || echo \$$HOME/.bun/bin/bun); \
		sed -e \"s|__USER__|$$ELFIN_REMOTE_HOST_USER|g\" \
		    -e \"s|__ELFIN_DIR__|$$REMOTE_PATH|g\" \
		    -e \"s|__BUN_PATH__|\$$BUN_PATH|g\" \
		    $$REMOTE_PATH/config/systemd/elfin.service.tpl \
		    | sudo tee /etc/systemd/system/elfin.service >/dev/null; \
		sudo systemctl daemon-reload; \
		sudo systemctl disable rk-llama 2>/dev/null || true; \
		sudo systemctl enable elfin 2>/dev/null || true; \
		echo '[install] systemd services installed and enabled'; \
		chmod +x $$REMOTE_PATH/scripts/elfin-browser.sh; \
		mkdir -p \$$HOME/.local/bin \$$HOME/.config/autostart; \
		ln -sf $$REMOTE_PATH/scripts/elfin-browser.sh \$$HOME/.local/bin/elfin-browser; \
		cp $$REMOTE_PATH/config/autostart/elfin-browser.desktop \$$HOME/.config/autostart/; \
		echo '[install] browser autostart installed'; \
		echo '[install] running bun install + prisma db push...'; \
		export BUN_INSTALL=\"\$$HOME/.bun\"; \
		export PATH=\"\$$BUN_INSTALL/bin:\$$PATH\"; \
		cd $$REMOTE_PATH && bun install --frozen-lockfile 2>/dev/null || bun install && \
		bunx prisma db push --accept-data-loss && \
		echo '[install] database ready'; \
		if [ \"$$TARGET\" = 'rockchip' ]; then \
			if [ -f $$DATA_PATH/toolchains/rk-llama.cpp/build/bin/llama-server ]; then \
				echo '[install] rk-llama.cpp binary exists, skipping build'; \
			else \
				echo '[install] building rk-llama.cpp...'; \
				cd $$REMOTE_PATH && sg render -c 'bash scripts/rk_llama_cpp.sh build' 2>&1; \
			fi; \
		fi; \
		sudo systemctl restart elfin 2>/dev/null || true; \
		echo '[install] elfin service restarted'; \
	"

services: ## Start target services only
	$(call start_rag_services)

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

ingest-remote: ## Run full ingestion pipeline on remote RK1 (sync raw docs, setup venv, ingest)
	@if [ -z "$$ELFIN_REMOTE_HOST" ] || [ -z "$$ELFIN_REMOTE_HOST_USER" ]; then \
		echo "ERROR: ELFIN_REMOTE_HOST and ELFIN_REMOTE_HOST_USER required"; \
		exit 1; \
	fi
	@REMOTE_PATH="$${ELFIN_REMOTE_PATH:-/home/$$ELFIN_REMOTE_HOST_USER/elfin}"; \
	SSH_PORT="$${ELFIN_REMOTE_PORT:-22}"; \
	SSH_TARGET="$$ELFIN_REMOTE_HOST_USER@$$ELFIN_REMOTE_HOST"; \
	SSH_OPTS="-p $$SSH_PORT -o StrictHostKeyChecking=accept-new"; \
	echo "[ingest-remote] syncing raw docs to $$SSH_TARGET:$$REMOTE_PATH/data/datasets/raw/..."; \
	ssh $$SSH_OPTS $$SSH_TARGET "mkdir -p $$REMOTE_PATH/data/datasets/raw"; \
	rsync -az --delete --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./data/datasets/raw/ "$$SSH_TARGET:$$REMOTE_PATH/data/datasets/raw/"; \
	echo "[ingest-remote] syncing compose + ingestion code..."; \
	rsync -az --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./docker-compose.yml "$$SSH_TARGET:$$REMOTE_PATH/docker-compose.yml"; \
	rsync -az --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./src/ingestion/ "$$SSH_TARGET:$$REMOTE_PATH/src/ingestion/"; \
	rsync -az --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./requirements.txt "$$SSH_TARGET:$$REMOTE_PATH/requirements.txt"; \
	echo "[ingest-remote] ensuring llama-embed is up to date..."; \
	ssh $$SSH_OPTS $$SSH_TARGET "cd $$REMOTE_PATH && docker compose up -d --force-recreate llama-embed"; \
	echo "[ingest-remote] setting up Python venv and running ingestion..."; \
	ssh $$SSH_OPTS $$SSH_TARGET " \
		cd $$REMOTE_PATH && \
		if [ ! -x .venv/bin/pip ]; then \
			rm -rf .venv; \
			python3 -m venv .venv 2>/dev/null || { \
				echo '[ingest-remote] installing python3-venv...'; \
				if command -v sudo >/dev/null 2>&1; then \
					sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv; \
				fi; \
				rm -rf .venv && python3 -m venv .venv; \
			}; \
		fi && \
		.venv/bin/pip install -q -r requirements.txt && \
		echo '[ingest-remote] waiting for llama-embed...' && \
		for i in \$$(seq 1 30); do curl -sf http://localhost:8082/health >/dev/null 2>&1 && break; sleep 1; done && \
		echo '[ingest-remote] waiting for Qdrant...' && \
		for i in \$$(seq 1 30); do curl -sf http://localhost:6333/healthz >/dev/null 2>&1 && break; sleep 1; done && \
		echo '[ingest-remote] running ingestion pipeline...' && \
		.venv/bin/python src/ingestion/pipeline.py \
	"; \
	echo "[ingest-remote] done."

ingest-remote-force: ## Re-ingest all documents on remote RK1 (force re-embed all chunks)
	@if [ -z "$$ELFIN_REMOTE_HOST" ] || [ -z "$$ELFIN_REMOTE_HOST_USER" ]; then \
		echo "ERROR: ELFIN_REMOTE_HOST and ELFIN_REMOTE_HOST_USER required"; \
		exit 1; \
	fi
	@REMOTE_PATH="$${ELFIN_REMOTE_PATH:-/home/$$ELFIN_REMOTE_HOST_USER/elfin}"; \
	SSH_PORT="$${ELFIN_REMOTE_PORT:-22}"; \
	SSH_TARGET="$$ELFIN_REMOTE_HOST_USER@$$ELFIN_REMOTE_HOST"; \
	SSH_OPTS="-p $$SSH_PORT -o StrictHostKeyChecking=accept-new"; \
	echo "[ingest-remote] syncing raw docs to $$SSH_TARGET:$$REMOTE_PATH/data/datasets/raw/..."; \
	ssh $$SSH_OPTS $$SSH_TARGET "mkdir -p $$REMOTE_PATH/data/datasets/raw"; \
	rsync -az --delete --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./data/datasets/raw/ "$$SSH_TARGET:$$REMOTE_PATH/data/datasets/raw/"; \
	echo "[ingest-remote] syncing compose + ingestion code..."; \
	rsync -az --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./docker-compose.yml "$$SSH_TARGET:$$REMOTE_PATH/docker-compose.yml"; \
	rsync -az --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./src/ingestion/ "$$SSH_TARGET:$$REMOTE_PATH/src/ingestion/"; \
	rsync -az --no-owner --no-group \
		-e "ssh $$SSH_OPTS" \
		./requirements.txt "$$SSH_TARGET:$$REMOTE_PATH/requirements.txt"; \
	echo "[ingest-remote] ensuring llama-embed is up to date..."; \
	ssh $$SSH_OPTS $$SSH_TARGET "cd $$REMOTE_PATH && docker compose up -d --force-recreate llama-embed"; \
	echo "[ingest-remote] force re-ingesting all documents..."; \
	ssh $$SSH_OPTS $$SSH_TARGET " \
		cd $$REMOTE_PATH && \
		if [ ! -x .venv/bin/pip ]; then \
			rm -rf .venv; \
			python3 -m venv .venv 2>/dev/null || { \
				echo '[ingest-remote] installing python3-venv...'; \
				if command -v sudo >/dev/null 2>&1; then \
					sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv; \
				fi; \
				rm -rf .venv && python3 -m venv .venv; \
			}; \
		fi && \
		.venv/bin/pip install -q -r requirements.txt && \
		echo '[ingest-remote] waiting for llama-embed...' && \
		for i in \$$(seq 1 30); do curl -sf http://localhost:8082/health >/dev/null 2>&1 && break; sleep 1; done && \
		echo '[ingest-remote] waiting for Qdrant...' && \
		for i in \$$(seq 1 30); do curl -sf http://localhost:6333/healthz >/dev/null 2>&1 && break; sleep 1; done && \
		echo '[ingest-remote] running ingestion pipeline (--force)...' && \
		.venv/bin/python src/ingestion/pipeline.py --force \
	"; \
	echo "[ingest-remote] done."

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

verify-gemma4: ## Start target llama-server and verify Gemma 4 health
	$(call start_llm)
	@echo "Waiting for llama-server..."
	$(call wait_for_llm)
	$(PYTHON) src/infra/verify_gemma4.py --no-launch

smoke-gemma4: ## Start target llama-server and run Gemma 4 chat smoke test
	$(call start_llm)
	@echo "Waiting for llama-server..."
	$(call wait_for_llm)
	$(PYTHON) src/infra/verify_gemma4.py --chat --no-launch

smoke-ingestion-live: ## Start Docker services and run live ingestion smoke test
	@echo "Starting llama-embed + Qdrant via Docker..."
	EMBED_MODEL=$(EMBED_MODEL) docker compose up -d llama-embed qdrant
	@echo "Waiting for llama-embed..."
	$(call wait_for_http,http://localhost:8082/health,llama-embed,llama-embed)
	@echo "Waiting for Qdrant..."
	$(call wait_for_http,http://localhost:6333/healthz,Qdrant,qdrant)
	$(PYTHON) src/infra/smoke_ingestion_live.py

chat: ## Start target services and open interactive cited RAG chat
	$(call start_rag_services)
	@echo "Waiting for llama-server..."
	$(call wait_for_llm)
	@echo "Waiting for llama-embed..."
	$(call wait_for_http,http://localhost:8082/health,llama-embed,llama-embed)
	@echo "Waiting for Qdrant..."
	$(call wait_for_http,http://localhost:6333/healthz,Qdrant,qdrant)
	@echo "Waiting for Kiwix..."
	$(call wait_for_http,http://localhost:8083/catalog/v2/root.xml,Kiwix,kiwix)
	$(PYTHON) src/cli/chat.py $(CHAT_ARGS)

vision: ## Start target llama-server and run multimodal vision test on an image
	$(call start_llm)
	@echo "Waiting for llama-server..."
	$(call wait_for_llm)
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
