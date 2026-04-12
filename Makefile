.PHONY: dev dev-full server build build-frontend build-arm64 test typecheck lint ingest ingest-force setup clean

# Start full dev stack: llama-server + llama-embed + Qdrant (Docker) + lefin-server (native)
dev: build
	@echo "Starting services..."
	docker compose up -d llama-server llama-embed qdrant
	@echo "Waiting for llama-server..."
	@until curl -sf http://localhost:8081/health > /dev/null 2>&1; do sleep 1; done
	@echo "Waiting for llama-embed..."
	@until curl -sf http://localhost:8082/health > /dev/null 2>&1; do sleep 1; done
	@echo "Waiting for Qdrant..."
	@until curl -sf http://localhost:6333/healthz > /dev/null 2>&1; do sleep 1; done
	@echo "Starting lefin-server on :8080"
	./lefin-server

# Start with Open WebUI too
dev-full: build
	docker compose up -d
	@echo "Waiting for services..."
	@until curl -sf http://localhost:8081/health > /dev/null 2>&1; do sleep 1; done
	@until curl -sf http://localhost:8082/health > /dev/null 2>&1; do sleep 1; done
	@until curl -sf http://localhost:6333/healthz > /dev/null 2>&1; do sleep 1; done
	@echo "Open WebUI at http://localhost:3000"
	@echo "Starting lefin-server on :8080"
	./lefin-server

# Build everything
build: build-frontend
	go build -o lefin-server ./cmd/lefin-server/

# Build frontend (TypeScript → bundled JS)
build-frontend:
	cd frontend && bun build src/app.ts --outdir ../static --minify

# Frontend dev mode (watch + rebuild)
dev-frontend:
	cd frontend && bun build src/app.ts --outdir ../static --watch

# Run just the Go server (assumes backends already running)
server: build
	./lefin-server

# Run ingestion pipeline (requires llama-embed + Qdrant running)
ingest:
	python3 src/ingestion/pipeline.py

# Force re-ingest all documents
ingest-force:
	python3 src/ingestion/pipeline.py --force

# First-time setup: install all deps
setup:
	cd frontend && bun install
	pip install -r requirements.txt

# Run Go tests
test:
	go test ./...

# TypeScript type-check
typecheck:
	cd frontend && bunx tsc --noEmit

# Lint
lint:
	golangci-lint run ./...

# Cross-compile for ARM64
build-arm64: build-frontend
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o lefin-server-arm64 ./cmd/lefin-server/

# Clean build artifacts
clean:
	rm -f lefin-server lefin-server-arm64 static/app.js
