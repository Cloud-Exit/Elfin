package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestHealthHandler_OllamaDown(t *testing.T) {
	cfg := Config{OllamaURL: "http://127.0.0.1:1"}
	handler := healthHandler(cfg)

	req := httptest.NewRequest(http.MethodGet, "/api/health", nil)
	w := httptest.NewRecorder()
	handler(w, req)

	if w.Code != http.StatusServiceUnavailable {
		t.Errorf("expected 503, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "unhealthy") {
		t.Errorf("expected unhealthy in body, got %s", w.Body.String())
	}
}

func TestChatHandler_InvalidJSON(t *testing.T) {
	cfg := Config{OllamaURL: "http://127.0.0.1:1", Model: "test"}
	handler := chatHandler(cfg)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader("not json"))
	w := httptest.NewRecorder()
	handler(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", w.Code)
	}
}

func TestChatHandler_OllamaUnreachable(t *testing.T) {
	cfg := Config{OllamaURL: "http://127.0.0.1:1", Model: "test"}
	handler := chatHandler(cfg)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(`{"message":"hello"}`))
	w := httptest.NewRecorder()
	handler(w, req)

	if w.Code != http.StatusBadGateway {
		t.Errorf("expected 502, got %d", w.Code)
	}
}

func TestSPAHandler_FallbackToIndex(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte("<html>spa</html>"), 0644); err != nil {
		t.Fatal(err)
	}

	handler := spaHandler(dir)
	req := httptest.NewRequest(http.MethodGet, "/nonexistent", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}
	if !strings.Contains(w.Body.String(), "spa") {
		t.Errorf("expected index.html content, got %s", w.Body.String())
	}
}

func TestSPAHandler_ServesStaticFile(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "app.js"), []byte("console.log('ok')"), 0644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "index.html"), []byte("<html>spa</html>"), 0644); err != nil {
		t.Fatal(err)
	}

	handler := spaHandler(dir)
	req := httptest.NewRequest(http.MethodGet, "/app.js", nil)
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)

	if !strings.Contains(w.Body.String(), "console.log") {
		t.Errorf("expected app.js content, got %s", w.Body.String())
	}
}

func TestEnvOr(t *testing.T) {
	if got := envOr("DEFINITELY_NOT_SET_12345", "fallback"); got != "fallback" {
		t.Errorf("expected fallback, got %s", got)
	}

	t.Setenv("TEST_ENV_OR", "value")
	if got := envOr("TEST_ENV_OR", "fallback"); got != "value" {
		t.Errorf("expected value, got %s", got)
	}
}
