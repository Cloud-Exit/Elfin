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
		if r.URL.Path != "/v1/embeddings" {
			http.Error(w, "not found", 404)
			return
		}
		resp := EmbedResponse{
			Data: []struct {
				Embedding []float64 `json:"embedding"`
			}{{Embedding: []float64{0.1, 0.2, 0.3}}},
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
		_, _ = w.Write([]byte(`{"data":[]}`))
	}))
	defer srv.Close()

	_, err := embedQuery(srv.URL, "test-model", "hello")
	if err == nil {
		t.Fatal("expected error for empty embeddings")
	}
}

func TestQueryQdrant_Success(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		resp := QdrantSearchResponse{
			Result: []QdrantPoint{
				{
					ID:    1,
					Score: 0.95,
					Payload: map[string]any{
						"text":        "Water purification methods include boiling.",
						"source_file": "FM 3-05.70",
						"page_label":  "42",
					},
				},
				{
					ID:    2,
					Score: 0.88,
					Payload: map[string]any{
						"text":        "Solar stills work by evaporation.",
						"source_file": "FM 3-05.70",
						"page_label":  "45",
					},
				},
			},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	defer srv.Close()

	sources, err := queryQdrant(srv.URL, "test-collection", []float64{0.1, 0.2}, 5)
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

func TestQueryQdrant_Empty(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"result":[]}`))
	}))
	defer srv.Close()

	sources, err := queryQdrant(srv.URL, "test-collection", []float64{0.1}, 5)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(sources) != 0 {
		t.Errorf("expected 0 sources, got %d", len(sources))
	}
}

func TestFullRAGChatFlow(t *testing.T) {
	// Mock llama-embed (OpenAI-compatible embeddings)
	embedSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		resp := EmbedResponse{
			Data: []struct {
				Embedding []float64 `json:"embedding"`
			}{{Embedding: []float64{0.1, 0.2, 0.3}}},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	defer embedSrv.Close()

	// Mock Qdrant
	qdrantSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		resp := QdrantSearchResponse{
			Result: []QdrantPoint{{
				ID:    1,
				Score: 0.95,
				Payload: map[string]any{
					"text":        "Boil water for 1 minute to purify.",
					"source_file": "FM 3-05.70",
					"page_label":  "42",
				},
			}},
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(resp)
	}))
	defer qdrantSrv.Close()

	// Mock llama-server (OpenAI-compatible chat with SSE streaming)
	llamaSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		for _, token := range []string{"Water ", "purification."} {
			chunk := fmt.Sprintf(`{"choices":[{"delta":{"content":"%s"}}]}`, token)
			_, _ = fmt.Fprintf(w, "data: %s\n\n", chunk)
		}
		_, _ = fmt.Fprint(w, "data: [DONE]\n\n")
	}))
	defer llamaSrv.Close()

	cfg := Config{
		LlamaURL:   llamaSrv.URL,
		EmbedURL:   embedSrv.URL,
		QdrantURL:  qdrantSrv.URL,
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
		t.Fatalf("expected at least 4 NDJSON lines, got %d: %s", len(lines), w.Body.String())
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
