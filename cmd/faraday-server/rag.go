package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// Source is a retrieved document chunk returned to the SPA.
type Source struct {
	Text       string `json:"text"`
	SourceFile string `json:"source_file"`
	Page       string `json:"page,omitempty"`
}

// --- OpenAI-compatible embeddings (llama.cpp /v1/embeddings) ---

// EmbedRequest is the payload for the OpenAI-compatible embeddings endpoint.
type EmbedRequest struct {
	Model string `json:"model"`
	Input string `json:"input"`
}

// EmbedResponse is the response from the OpenAI-compatible embeddings endpoint.
type EmbedResponse struct {
	Data []struct {
		Embedding []float64 `json:"embedding"`
	} `json:"data"`
}

// embedQuery calls the embedding server's OpenAI-compatible endpoint.
func embedQuery(embedURL, model, query string) ([]float64, error) {
	req := EmbedRequest{Model: model, Input: query}
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal embed request: %w", err)
	}

	resp, err := http.Post(embedURL+"/v1/embeddings", "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("embed request: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("embed status %d: %s", resp.StatusCode, string(b))
	}

	var embedResp EmbedResponse
	if err := json.NewDecoder(resp.Body).Decode(&embedResp); err != nil {
		return nil, fmt.Errorf("decode embed response: %w", err)
	}

	if len(embedResp.Data) == 0 {
		return nil, fmt.Errorf("no embeddings returned")
	}
	return embedResp.Data[0].Embedding, nil
}

// --- Qdrant vector search ---

// QdrantSearchRequest is the payload for Qdrant's search endpoint.
type QdrantSearchRequest struct {
	Vector      []float64 `json:"vector"`
	Limit       int       `json:"limit"`
	WithPayload bool      `json:"with_payload"`
}

// QdrantSearchResponse is the response from Qdrant's search endpoint.
type QdrantSearchResponse struct {
	Result []QdrantPoint `json:"result"`
}

// QdrantPoint is a single search result from Qdrant.
type QdrantPoint struct {
	ID      any            `json:"id"`
	Score   float64        `json:"score"`
	Payload map[string]any `json:"payload"`
}

// queryQdrant retrieves the top-k nearest chunks from Qdrant.
func queryQdrant(qdrantURL, collection string, embedding []float64, topK int) ([]Source, error) {
	req := QdrantSearchRequest{
		Vector:      embedding,
		Limit:       topK,
		WithPayload: true,
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal qdrant search: %w", err)
	}

	url := qdrantURL + "/collections/" + collection + "/points/search"
	resp, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("qdrant search: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("qdrant search status %d: %s", resp.StatusCode, string(b))
	}

	var searchResp QdrantSearchResponse
	if err := json.NewDecoder(resp.Body).Decode(&searchResp); err != nil {
		return nil, fmt.Errorf("decode qdrant response: %w", err)
	}

	var sources []Source
	for _, point := range searchResp.Result {
		s := Source{}
		if text, ok := point.Payload["text"].(string); ok {
			s.Text = text
		}
		if sf, ok := point.Payload["source_file"].(string); ok {
			s.SourceFile = sf
		}
		if pg, ok := point.Payload["page_label"].(string); ok {
			s.Page = pg
		}
		if s.Text != "" {
			sources = append(sources, s)
		}
	}
	return sources, nil
}

// --- Prompt building ---

// buildRAGPrompt constructs a prompt with retrieved context for Reference Mode.
func buildRAGPrompt(query string, sources []Source) []OllamaMessage {
	var contextBuilder strings.Builder
	for i, s := range sources {
		fmt.Fprintf(&contextBuilder, "--- Source %d: %s", i+1, s.SourceFile)
		if s.Page != "" {
			fmt.Fprintf(&contextBuilder, " (page %s)", s.Page)
		}
		contextBuilder.WriteString(" ---\n")
		contextBuilder.WriteString(s.Text)
		contextBuilder.WriteString("\n\n")
	}

	systemPrompt := `You are Lefin, a survival reference assistant. Answer the user's question using ONLY the provided source material below. Rules:
- Cite which source you are drawing from (e.g. "According to FM 3-05.70...")
- If the sources do not contain enough information to answer, say: "I don't have information on that in my reference materials. Try the Encyclopedia tab."
- Never speculate or add information not present in the sources.
- Be concise and direct.

` + contextBuilder.String()

	return []OllamaMessage{
		{Role: "system", Content: systemPrompt},
		{Role: "user", Content: query},
	}
}

// buildDirectPrompt constructs a prompt for direct chat (no RAG, fallback).
func buildDirectPrompt(query string) []OllamaMessage {
	return []OllamaMessage{
		{Role: "user", Content: query},
	}
}
