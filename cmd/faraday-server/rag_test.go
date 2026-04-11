package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestEmbedQuery_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/embed" {
			http.Error(w, "not found", 404)
			return
		}
		resp := OllamaEmbedResponse{
			Embeddings: [][]float64{{0.1, 0.2, 0.3}},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	defer srv.Close()

	embedding, err := embedQuery(srv.URL, "test-model", "hello")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(embedding) != 3 {
		t.Errorf("expected 3 dimensions, got %d", len(embedding))
	}
}

func TestEmbedQuery_EmptyResponse(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"embeddings":[]}`))
	}))
	defer srv.Close()

	_, err := embedQuery(srv.URL, "test-model", "hello")
	if err == nil {
		t.Fatal("expected error for empty embeddings")
	}
}

func TestGetCollectionID_Found(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		collections := []ChromaCollection{
			{ID: "abc-123", Name: "faraday_docs"},
			{ID: "def-456", Name: "other"},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(collections)
	}))
	defer srv.Close()

	id, err := getCollectionID(srv.URL, "faraday_docs")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if id != "abc-123" {
		t.Errorf("expected abc-123, got %s", id)
	}
}

func TestGetCollectionID_NotFound(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`[]`))
	}))
	defer srv.Close()

	_, err := getCollectionID(srv.URL, "nonexistent")
	if err == nil {
		t.Fatal("expected error for missing collection")
	}
}

func TestQueryChromaDB_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		resp := ChromaQueryResponse{
			Documents: [][]string{{"Water purification methods include boiling.", "Solar stills work by evaporation."}},
			Metadatas: [][]map[string]any{
				{
					{"source_file": "FM 3-05.70", "page_label": "42"},
					{"source_file": "FM 3-05.70", "page_label": "45"},
				},
			},
			Distances: [][]float64{{0.1, 0.2}},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	defer srv.Close()

	sources, err := queryChromaDB(srv.URL, "test-id", []float64{0.1, 0.2}, 5)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(sources) != 2 {
		t.Fatalf("expected 2 sources, got %d", len(sources))
	}
	if sources[0].SourceFile != "FM 3-05.70" {
		t.Errorf("expected FM 3-05.70, got %s", sources[0].SourceFile)
	}
	if sources[0].Page != "42" {
		t.Errorf("expected page 42, got %s", sources[0].Page)
	}
}

func TestQueryChromaDB_Empty(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"documents":[[]],"metadatas":[[]],"distances":[[]]}`))
	}))
	defer srv.Close()

	sources, err := queryChromaDB(srv.URL, "test-id", []float64{0.1}, 5)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(sources) != 0 {
		t.Errorf("expected 0 sources, got %d", len(sources))
	}
}

func TestFullRAGChatFlow(t *testing.T) {
	// Mock Ollama: serves both /api/embed and /api/chat
	ollama := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/api/embed":
			resp := OllamaEmbedResponse{Embeddings: [][]float64{{0.1, 0.2, 0.3}}}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(resp)
		case "/api/chat":
			w.Header().Set("Content-Type", "application/x-ndjson")
			// Stream two tokens then done
			for _, token := range []string{"Water ", "purification."} {
				chunk := fmt.Sprintf(`{"message":{"content":"%s"},"done":false}`, token)
				_, _ = fmt.Fprintln(w, chunk)
			}
			_, _ = fmt.Fprintln(w, `{"message":{"content":""},"done":true}`)
		default:
			http.Error(w, "not found", 404)
		}
	}))
	defer ollama.Close()

	// Mock ChromaDB: serves collection list and query
	chroma := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.HasPrefix(r.URL.Path, "/api/v1/collections") && r.Method == "GET" {
			_ = json.NewEncoder(w).Encode([]ChromaCollection{{ID: "test-id", Name: "faraday_docs"}})
		} else if strings.Contains(r.URL.Path, "/query") {
			resp := ChromaQueryResponse{
				Documents: [][]string{{"Boil water for 1 minute to purify."}},
				Metadatas: [][]map[string]any{{{"source_file": "FM 3-05.70", "page_label": "42"}}},
				Distances: [][]float64{{0.05}},
			}
			_ = json.NewEncoder(w).Encode(resp)
		}
	}))
	defer chroma.Close()

	cfg := Config{
		OllamaURL:  ollama.URL,
		ChromaURL:  chroma.URL,
		Model:      "test",
		EmbedModel: "test",
		Collection: "faraday_docs",
	}

	handler := chatHandler(cfg)
	req := httptest.NewRequest(http.MethodPost, "/api/chat", strings.NewReader(`{"message":"how to purify water"}`))
	w := httptest.NewRecorder()
	handler(w, req)

	lines := strings.Split(strings.TrimSpace(w.Body.String()), "\n")
	if len(lines) < 4 {
		t.Fatalf("expected at least 4 NDJSON lines (sources + 2 tokens + done), got %d: %s", len(lines), w.Body.String())
	}

	// Line 0: sources
	var sourcesMsg StreamMessage
	if err := json.Unmarshal([]byte(lines[0]), &sourcesMsg); err != nil {
		t.Fatalf("parse sources: %v", err)
	}
	if sourcesMsg.Type != "sources" {
		t.Errorf("expected sources, got %s", sourcesMsg.Type)
	}
	if len(sourcesMsg.Sources) != 1 {
		t.Fatalf("expected 1 source, got %d", len(sourcesMsg.Sources))
	}
	if sourcesMsg.Sources[0].SourceFile != "FM 3-05.70" {
		t.Errorf("expected FM 3-05.70, got %s", sourcesMsg.Sources[0].SourceFile)
	}

	// Collect tokens
	var content string
	for _, line := range lines[1:] {
		var msg StreamMessage
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			continue
		}
		if msg.Type == "token" {
			content += msg.Content
		}
	}
	if content != "Water purification." {
		t.Errorf("expected 'Water purification.', got '%s'", content)
	}

	// Last line: done
	var doneMsg StreamMessage
	if err := json.Unmarshal([]byte(lines[len(lines)-1]), &doneMsg); err != nil {
		t.Fatalf("parse done: %v", err)
	}
	if doneMsg.Type != "done" {
		t.Errorf("expected done, got %s", doneMsg.Type)
	}
}
