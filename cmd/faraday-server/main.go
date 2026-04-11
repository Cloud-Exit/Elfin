package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

// Config holds server configuration loaded from environment variables.
type Config struct {
	Port       string
	OllamaURL  string
	ChromaURL  string
	StaticDir  string
	Model      string
	EmbedModel string
	Collection string
}

func loadConfig() Config {
	return Config{
		Port:       envOr("FARADAY_PORT", "8080"),
		OllamaURL:  envOr("OLLAMA_URL", "http://localhost:11434"),
		ChromaURL:  envOr("CHROMA_URL", "http://localhost:8000"),
		StaticDir:  envOr("STATIC_DIR", "./static"),
		Model:      envOr("FARADAY_MODEL", "gemma3:4b"),
		EmbedModel: envOr("FARADAY_EMBED_MODEL", "nomic-embed-text"),
		Collection: envOr("FARADAY_COLLECTION", "faraday_docs"),
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

// OllamaChatRequest is what we forward to Ollama's /api/chat.
type OllamaChatRequest struct {
	Model    string          `json:"model"`
	Messages []OllamaMessage `json:"messages"`
	Stream   bool            `json:"stream"`
}

// OllamaMessage represents a single chat message.
type OllamaMessage struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// OllamaChatChunk is a single streamed chunk from Ollama.
type OllamaChatChunk struct {
	Message struct {
		Content string `json:"content"`
	} `json:"message"`
	Done bool `json:"done"`
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

		// Try RAG: embed → ChromaDB → build prompt with sources
		messages, sources := ragOrFallback(cfg, req.Message)

		// Send sources first (may be empty if RAG failed)
		writeStreamLine(w, flusher, StreamMessage{Type: "sources", Sources: sources})

		// Build Ollama request
		ollamaReq := OllamaChatRequest{
			Model:    cfg.Model,
			Messages: messages,
			Stream:   true,
		}
		body, err := json.Marshal(ollamaReq)
		if err != nil {
			writeStreamLine(w, flusher, StreamMessage{Type: "error", Error: "marshal error"})
			return
		}

		resp, err := http.Post(cfg.OllamaURL+"/api/chat", "application/json", bytes.NewReader(body))
		if err != nil {
			writeStreamLine(w, flusher, StreamMessage{Type: "error", Error: fmt.Sprintf("ollama unreachable: %s", err.Error())})
			return
		}
		defer func() { _ = resp.Body.Close() }()

		// Stream tokens from Ollama
		decoder := json.NewDecoder(resp.Body)
		for decoder.More() {
			var chunk OllamaChatChunk
			if err := decoder.Decode(&chunk); err != nil {
				break
			}
			if chunk.Message.Content != "" {
				writeStreamLine(w, flusher, StreamMessage{Type: "token", Content: chunk.Message.Content})
			}
			if chunk.Done {
				break
			}
		}

		writeStreamLine(w, flusher, StreamMessage{Type: "done"})
	}
}

// ragOrFallback attempts RAG orchestration. If any step fails, falls back to direct chat.
func ragOrFallback(cfg Config, query string) ([]OllamaMessage, []Source) {
	// Step 1: embed the query
	embedding, err := embedQuery(cfg.OllamaURL, cfg.EmbedModel, query)
	if err != nil {
		log.Printf("RAG embed failed (falling back to direct): %v", err)
		return buildDirectPrompt(query), nil
	}

	// Step 2: find the collection
	collectionID, err := getCollectionID(cfg.ChromaURL, cfg.Collection)
	if err != nil {
		log.Printf("RAG collection lookup failed (falling back to direct): %v", err)
		return buildDirectPrompt(query), nil
	}

	// Step 3: query ChromaDB
	sources, err := queryChromaDB(cfg.ChromaURL, collectionID, embedding, 5)
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

		ollamaOK := "connected"
		resp, err := client.Get(cfg.OllamaURL + "/api/tags")
		if err != nil {
			ollamaOK = "unreachable"
		} else {
			_ = resp.Body.Close()
		}

		chromaOK := "connected"
		resp, err = client.Get(cfg.ChromaURL + "/api/v1/heartbeat")
		if err != nil {
			chromaOK = "unreachable"
		} else {
			_ = resp.Body.Close()
		}

		status := "healthy"
		code := http.StatusOK
		if ollamaOK != "connected" || chromaOK != "connected" {
			status = "degraded"
			code = http.StatusOK // still 200 — degraded is informational
		}

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)

		result := map[string]string{
			"status":   status,
			"ollama":   ollamaOK,
			"chromadb": chromaOK,
		}
		_ = json.NewEncoder(w).Encode(result)
	}
}
