.PHONY: dev server build test lint clean build-arm64 ingest setup

# Start full dev stack: Ollama + ChromaDB (Docker) + faraday-server (native)
dev: build
	@echo "Starting services..."
	docker compose up -d ollama chromadb
	@echo "Waiting for Ollama..."
	@until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 1; done
	@echo "Waiting for ChromaDB..."
	@until curl -sf http://localhost:8000/api/v1/heartbeat > /dev/null 2>&1; do sleep 1; done
	@echo "Starting faraday-server on :8080"
	./faraday-server

# Build the Go binary
build:
	go build -o faraday-server ./cmd/faraday-server/

# Run just the Go server (assumes backends already running)
server: build
	./faraday-server

# Run ingestion pipeline (requires Ollama + ChromaDB running)
ingest:
	python3 src/ingestion/pipeline.py

# Force re-ingest all documents
ingest-force:
	python3 src/ingestion/pipeline.py --force

# First-time setup: install Python deps, pull models
setup:
	pip install -r requirements.txt
	docker compose up -d ollama
	@until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 1; done
	docker compose exec ollama ollama pull nomic-embed-text
	docker compose exec ollama ollama pull gemma3:4b

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
