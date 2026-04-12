package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

// Config holds server configuration loaded from environment variables.
type Config struct {
	Port       string
	LlamaURL   string // llama-server (chat) OpenAI-compatible base URL
	EmbedURL   string // llama-embed (embeddings) OpenAI-compatible base URL
	QdrantURL  string
	StaticDir  string
	Model      string // model name for chat completions
	EmbedModel string // model name for embeddings
	Collection string // Qdrant collection name
}

func loadConfig() Config {
	return Config{
		Port:       envOr("LEFIN_PORT", "8080"),
		LlamaURL:   envOr("LLAMA_URL", "http://localhost:8081"),
		EmbedURL:   envOr("EMBED_URL", "http://localhost:8082"),
		QdrantURL:  envOr("QDRANT_URL", "http://localhost:6333"),
		StaticDir:  envOr("STATIC_DIR", "./static"),
		Model:      envOr("LEFIN_MODEL", "gemma-4-e4b"),
		EmbedModel: envOr("LEFIN_EMBED_MODEL", "nomic-embed-text"),
		Collection: envOr("LEFIN_COLLECTION", "faraday_docs"),
	}
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func main() {
	cfg := loadConfig()

	mux := http.NewServeMux()
	mux.HandleFunc("POST /api/chat", chatHandler(cfg))
	mux.HandleFunc("GET /api/health", healthHandler(cfg))
	mux.Handle("/", spaHandler(cfg.StaticDir))

	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 120 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	done := make(chan os.Signal, 1)
	signal.Notify(done, os.Interrupt, syscall.SIGTERM)

	go func() {
		log.Printf("faraday-server listening on :%s", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatalf("server error: %v", err)
		}
	}()

	<-done
	log.Println("shutting down...")

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Fatalf("shutdown error: %v", err)
	}
}

func spaHandler(dir string) http.Handler {
	fs := http.FileServer(http.Dir(dir))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := dir + r.URL.Path
		if _, err := os.Stat(path); os.IsNotExist(err) {
			http.ServeFile(w, r, dir+"/index.html")
			return
		}
		fs.ServeHTTP(w, r)
	})
}

// ChatRequest is the JSON payload from the SPA.
type ChatRequest struct {
	Message string `json:"message"`
}

// StreamMessage is a single NDJSON line sent to the SPA.
type StreamMessage struct {
	Type    string   `json:"type"`
	Content string   `json:"content,omitempty"`
	Sources []Source `json:"sources,omitempty"`
	Error   string   `json:"error,omitempty"`
}

// OllamaMessage is used for building message arrays (OpenAI chat format).
type OllamaMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// OpenAIChatRequest is the payload for the OpenAI-compatible /v1/chat/completions.
type OpenAIChatRequest struct {
	Model    string          `json:"model"`
	Messages []OllamaMessage `json:"messages"`
	Stream   bool            `json:"stream"`
}

// OpenAIChatChunk is a single SSE chunk from the streaming response.
type OpenAIChatChunk struct {
	Choices []struct {
		Delta struct {
			Content string `json:"content"`
		} `json:"delta"`
		FinishReason *string `json:"finish_reason"`
	} `json:"choices"`
}

func chatHandler(cfg Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, `{"error":"invalid request"}`, http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/x-ndjson")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("X-Content-Type-Options", "nosniff")

		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, `{"error":"streaming not supported"}`, http.StatusInternalServerError)
			return
		}

		// RAG orchestration: embed → Qdrant → build prompt
		messages, sources := ragOrFallback(cfg, req.Message)
		writeStreamLine(w, flusher, StreamMessage{Type: "sources", Sources: sources})

		// Call llama-server via OpenAI-compatible API
		chatReq := OpenAIChatRequest{
			Model:    cfg.Model,
			Messages: messages,
			Stream:   true,
		}
		body, err := json.Marshal(chatReq)
		if err != nil {
			writeStreamLine(w, flusher, StreamMessage{Type: "error", Error: "marshal error"})
			return
		}

		resp, err := http.Post(cfg.LlamaURL+"/v1/chat/completions", "application/json", bytes.NewReader(body))
		if err != nil {
			writeStreamLine(w, flusher, StreamMessage{Type: "error", Error: fmt.Sprintf("llama-server unreachable: %s", err.Error())})
			return
		}
		defer func() { _ = resp.Body.Close() }()

		// Parse SSE stream from llama-server
		scanner := bufio.NewScanner(resp.Body)
		for scanner.Scan() {
			line := scanner.Text()

			// SSE format: "data: {...}" or "data: [DONE]"
			if !strings.HasPrefix(line, "data: ") {
				continue
			}
			data := strings.TrimPrefix(line, "data: ")
			if data == "[DONE]" {
				break
			}

			var chunk OpenAIChatChunk
			if err := json.Unmarshal([]byte(data), &chunk); err != nil {
				continue
			}
			for _, choice := range chunk.Choices {
				if choice.Delta.Content != "" {
					writeStreamLine(w, flusher, StreamMessage{Type: "token", Content: choice.Delta.Content})
				}
			}
		}

		writeStreamLine(w, flusher, StreamMessage{Type: "done"})
	}
}

// ragOrFallback attempts RAG orchestration. If any step fails, falls back to direct chat.
func ragOrFallback(cfg Config, query string) ([]OllamaMessage, []Source) {
	embedding, err := embedQuery(cfg.EmbedURL, cfg.EmbedModel, query)
	if err != nil {
		log.Printf("RAG embed failed (falling back to direct): %v", err)
		return buildDirectPrompt(query), nil
	}

	sources, err := queryQdrant(cfg.QdrantURL, cfg.Collection, embedding, 5)
	if err != nil {
		log.Printf("RAG query failed (falling back to direct): %v", err)
		return buildDirectPrompt(query), nil
	}

	if len(sources) == 0 {
		log.Printf("RAG: no sources found for query")
		return buildDirectPrompt(query), nil
	}

	log.Printf("RAG: found %d sources for query", len(sources))
	return buildRAGPrompt(query, sources), sources
}

func writeStreamLine(w http.ResponseWriter, flusher http.Flusher, msg StreamMessage) {
	data, err := json.Marshal(msg)
	if err != nil {
		return
	}
	_, _ = w.Write(data)
	_, _ = w.Write([]byte("\n"))
	flusher.Flush()
}

func healthHandler(cfg Config) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		client := &http.Client{Timeout: 2 * time.Second}

		llamaOK := "connected"
		resp, err := client.Get(cfg.LlamaURL + "/health")
		if err != nil {
			llamaOK = "unreachable"
		} else {
			_ = resp.Body.Close()
		}

		embedOK := "connected"
		resp, err = client.Get(cfg.EmbedURL + "/health")
		if err != nil {
			embedOK = "unreachable"
		} else {
			_ = resp.Body.Close()
		}

		qdrantOK := "connected"
		resp, err = client.Get(cfg.QdrantURL + "/healthz")
		if err != nil {
			qdrantOK = "unreachable"
		} else {
			_ = resp.Body.Close()
		}

		status := "healthy"
		if llamaOK != "connected" || embedOK != "connected" || qdrantOK != "connected" {
			status = "degraded"
		}

		w.Header().Set("Content-Type", "application/json")
		result := map[string]string{
			"status":    status,
			"llama":     llamaOK,
			"embedding": embedOK,
			"qdrant":    qdrantOK,
		}
		_ = json.NewEncoder(w).Encode(result)
	}
}
