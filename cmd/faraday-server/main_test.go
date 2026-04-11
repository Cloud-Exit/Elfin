package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testConfig() Config {
	return Config{
		LlamaURL:   "http://127.0.0.1:1",
		EmbedURL:   "http://127.0.0.1:1",
		QdrantURL:  "http://127.0.0.1:1",
		Model:      "test",
		EmbedModel: "test",
		Collection: "test",
	}
}

func TestHealthHandler_AllDown(t *testing.T) {
	cfg := testConfig()
	handler := healthHandler(cfg)

	req := httptest.NewRequest(http.MethodGet, "/api/health", nil)
	w := httptest.NewRecorder()
	handler(w, req)

	var result map[string]string
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatalf("invalid json: %v", err)
	}
	if result["status"] != "degraded" {
		t.Errorf("expected degraded, got %s", result["status"])
	}
	if result["llama"] != "unreachable" {
		t.Errorf("expected llama unreachable, got %s", result["llama"])
	}
	if result["qdrant"] != "unreachable" {
		t.Errorf("expected qdrant unreachable, got %s", result["qdrant"])
	}
}

func TestChatHandler_InvalidJSON(t *testing.T) {
	cfg := testConfig()
	handler := chatHandler(cfg)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader("not json"))
	w := httptest.NewRecorder()
	handler(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", w.Code)
	}
}

func TestChatHandler_RAGFallback(t *testing.T) {
	cfg := testConfig()
	handler := chatHandler(cfg)

	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(`{"message":"hello"}`))
	w := httptest.NewRecorder()
	handler(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}

	lines := strings.Split(strings.TrimSpace(w.Body.String()), "\n")
	if len(lines) < 2 {
		t.Fatalf("expected at least 2 NDJSON lines, got %d: %s", len(lines), w.Body.String())
	}

	var sourcesMsg StreamMessage
	if err := json.Unmarshal([]byte(lines[0]), &sourcesMsg); err != nil {
		t.Fatalf("parse sources line: %v", err)
	}
	if sourcesMsg.Type != "sources" {
		t.Errorf("expected sources message, got %s", sourcesMsg.Type)
	}

	var errMsg StreamMessage
	if err := json.Unmarshal([]byte(lines[1]), &errMsg); err != nil {
		t.Fatalf("parse error line: %v", err)
	}
	if errMsg.Type != "error" {
		t.Errorf("expected error message, got %s", errMsg.Type)
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

func TestBuildRAGPrompt(t *testing.T) {
	sources := []Source{
		{Text: "Water can be purified by boiling.", SourceFile: "FM 3-05.70", Page: "42"},
		{Text: "Solar stills collect condensation.", SourceFile: "FM 3-05.70", Page: "45"},
	}

	messages := buildRAGPrompt("how to purify water", sources)

	if len(messages) != 2 {
		t.Fatalf("expected 2 messages, got %d", len(messages))
	}
	if messages[0].Role != "system" {
		t.Errorf("expected system role, got %s", messages[0].Role)
	}
	if !strings.Contains(messages[0].Content, "FM 3-05.70") {
		t.Error("system prompt should contain source file name")
	}
	if !strings.Contains(messages[0].Content, "page 42") {
		t.Error("system prompt should contain page number")
	}
	if messages[1].Content != "how to purify water" {
		t.Errorf("expected query in user message, got %s", messages[1].Content)
	}
}

func TestBuildDirectPrompt(t *testing.T) {
	messages := buildDirectPrompt("hello")
	if len(messages) != 1 {
		t.Fatalf("expected 1 message, got %d", len(messages))
	}
	if messages[0].Role != "user" || messages[0].Content != "hello" {
		t.Errorf("unexpected message: %+v", messages[0])
	}
}
