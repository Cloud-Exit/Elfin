.PHONY: dev server ollama build test lint clean build-arm64

# Start full dev stack: Ollama (Docker) + faraday-server (native)
dev: build
	@echo "Starting Ollama..."
	docker compose up -d ollama
	@echo "Waiting for Ollama..."
	@until curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; do sleep 1; done
	@echo "Starting faraday-server on :8080"
	./faraday-server

# Build the Go binary
build:
	go build -o faraday-server ./cmd/faraday-server/

# Run just the Go server (assumes Ollama already running)
server: build
	./faraday-server

# Run tests
test:
	go test ./...

# Lint
lint:
	~/go/bin/golangci-lint run ./...

# Cross-compile for ARM64
build-arm64:
	CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o faraday-server-arm64 ./cmd/faraday-server/

# Clean build artifacts
clean:
	rm -f faraday-server faraday-server-arm64
