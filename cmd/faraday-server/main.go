package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

// Config holds server configuration loaded from environment variables.
type Config struct {
	Port      string
	OllamaURL string
	StaticDir string
	Model     string
}

func loadConfig() Config {
	return Config{
		Port:      envOr("FARADAY_PORT", "8080"),
		OllamaURL: envOr("OLLAMA_URL", "http://localhost:11434"),
		StaticDir: envOr("STATIC_DIR", "./static"),
		Model:     envOr("FARADAY_MODEL", "gemma3:4b"),
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

func chatHandler(cfg Config) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req ChatRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, `{"error":"invalid request"}`, http.StatusBadRequest)
			return
		}

		ollamaReq := OllamaChatRequest{
			Model: cfg.Model,
			Messages: []OllamaMessage{
				{Role: "user", Content: req.Message},
			},
			Stream: true,
		}

		body, err := json.Marshal(ollamaReq)
		if err != nil {
			http.Error(w, `{"error":"marshal error"}`, http.StatusInternalServerError)
			return
		}

		resp, err := http.Post(cfg.OllamaURL+"/api/chat", "application/json", bytes.NewReader(body))
		if err != nil {
			http.Error(w, fmt.Sprintf(`{"error":"ollama unreachable: %s"}`, err.Error()), http.StatusBadGateway)
			return
		}
		defer func() { _ = resp.Body.Close() }()

		w.Header().Set("Content-Type", "application/x-ndjson")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("X-Content-Type-Options", "nosniff")

		flusher, ok := w.(http.Flusher)
		if !ok {
			http.Error(w, `{"error":"streaming not supported"}`, http.StatusInternalServerError)
			return
		}

		buf := make([]byte, 4096)
		for {
			n, readErr := resp.Body.Read(buf)
			if n > 0 {
				if _, writeErr := w.Write(buf[:n]); writeErr != nil {
					return
				}
				flusher.Flush()
			}
			if readErr != nil {
				return
			}
		}
	}
}

func healthHandler(cfg Config) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		client := &http.Client{Timeout: 2 * time.Second}
		resp, err := client.Get(cfg.OllamaURL + "/api/tags")
		w.Header().Set("Content-Type", "application/json")
		if err != nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			_, _ = io.WriteString(w, `{"status":"unhealthy","ollama":"unreachable"}`)
			return
		}
		_ = resp.Body.Close()
		_, _ = io.WriteString(w, `{"status":"healthy","ollama":"connected"}`)
	}
}
