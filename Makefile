.PHONY: dev server build test lint clean build-arm64 ingest ingest-force setup

# Start full dev stack: llama-server + llama-embed + Qdrant (Docker) + faraday-server (native)
dev: build
	@echo "Starting services..."
	docker compose up -d llama-server llama-embed qdrant
	@echo "Waiting for llama-server..."
	@until curl -sf http://localhost:8081/health > /dev/null 2>&1; do sleep 1; done
	@echo "Waiting for llama-embed..."
	@until curl -sf http://localhost:8082/health > /dev/null 2>&1; do sleep 1; done
	@echo "Waiting for Qdrant..."
	@until curl -sf http://localhost:6333/healthz > /dev/null 2>&1; do sleep 1; done
	@echo "Starting faraday-server on :8080"
	./faraday-server

# Start with Open WebUI too
dev-full: build
	docker compose up -d
	@echo "Waiting for services..."
	@until curl -sf http://localhost:8081/health > /dev/null 2>&1; do sleep 1; done
	@until curl -sf http://localhost:8082/health > /dev/null 2>&1; do sleep 1; done
	@until curl -sf http://localhost:6333/healthz > /dev/null 2>&1; do sleep 1; done
	@echo "Open WebUI at http://localhost:3000"
	@echo "Starting faraday-server on :8080"
	./faraday-server

# Build the Go binary
build:
	go build -o faraday-server ./cmd/faraday-server/

# Run just the Go server (assumes backends already running)
server: build
	./faraday-server

# Run ingestion pipeline (requires llama-embed + Qdrant running)
ingest:
	python3 src/ingestion/pipeline.py

# Force re-ingest all documents
ingest-force:
	python3 src/ingestion/pipeline.py --force

# First-time setup: install Python deps
setup:
	pip install -r requirements.txt

# Run tests
test:
	go test ./...

# Lint
lint:
	golangci-lint run ./...

# Cross-compile for ARM64
build-arm64:
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o faraday-server-arm64 ./cmd/faraday-server/

# Clean build artifacts
clean:
	rm -f faraday-server faraday-server-arm64
