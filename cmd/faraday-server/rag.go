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

// OllamaEmbedRequest is the payload for Ollama's /api/embed endpoint.
type OllamaEmbedRequest struct {
	Model string `json:"model"`
	Input string `json:"input"`
}

// OllamaEmbedResponse is the response from Ollama's /api/embed endpoint.
type OllamaEmbedResponse struct {
	Embeddings [][]float64 `json:"embeddings"`
}

// embedQuery calls Ollama to get an embedding vector for the query.
func embedQuery(ollamaURL, model, query string) ([]float64, error) {
	req := OllamaEmbedRequest{Model: model, Input: query}
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal embed request: %w", err)
	}

	resp, err := http.Post(ollamaURL+"/api/embed", "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("ollama embed request: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("ollama embed status %d: %s", resp.StatusCode, string(b))
	}

	var embedResp OllamaEmbedResponse
	if err := json.NewDecoder(resp.Body).Decode(&embedResp); err != nil {
		return nil, fmt.Errorf("decode embed response: %w", err)
	}

	if len(embedResp.Embeddings) == 0 {
		return nil, fmt.Errorf("no embeddings returned")
	}
	return embedResp.Embeddings[0], nil
}

// ChromaQueryRequest is the payload for ChromaDB's collection query endpoint.
type ChromaQueryRequest struct {
	QueryEmbeddings [][]float64 `json:"query_embeddings"`
	NResults        int         `json:"n_results"`
	Include         []string    `json:"include"`
}

// ChromaQueryResponse is the response from ChromaDB's query endpoint.
type ChromaQueryResponse struct {
	Documents [][]string            `json:"documents"`
	Metadatas [][]map[string]any    `json:"metadatas"`
	Distances [][]float64           `json:"distances"`
}

// ChromaCollection represents a ChromaDB collection.
type ChromaCollection struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// getCollectionID looks up the ChromaDB collection ID by name.
func getCollectionID(chromaURL, name string) (string, error) {
	url := chromaURL + "/api/v1/collections?limit=100"
	resp, err := http.Get(url)
	if err != nil {
		return "", fmt.Errorf("chroma list collections: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	var collections []ChromaCollection
	if err := json.NewDecoder(resp.Body).Decode(&collections); err != nil {
		return "", fmt.Errorf("decode collections: %w", err)
	}

	for _, c := range collections {
		if c.Name == name {
			return c.ID, nil
		}
	}
	return "", fmt.Errorf("collection %q not found", name)
}

// queryChromaDB retrieves the top-k nearest chunks for a query embedding.
func queryChromaDB(chromaURL, collectionID string, embedding []float64, topK int) ([]Source, error) {
	req := ChromaQueryRequest{
		QueryEmbeddings: [][]float64{embedding},
		NResults:        topK,
		Include:         []string{"documents", "metadatas", "distances"},
	}

	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal chroma query: %w", err)
	}

	url := chromaURL + "/api/v1/collections/" + collectionID + "/query"
	resp, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("chroma query: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("chroma query status %d: %s", resp.StatusCode, string(b))
	}

	var chromaResp ChromaQueryResponse
	if err := json.NewDecoder(resp.Body).Decode(&chromaResp); err != nil {
		return nil, fmt.Errorf("decode chroma response: %w", err)
	}

	if len(chromaResp.Documents) == 0 || len(chromaResp.Documents[0]) == 0 {
		return nil, nil
	}

	var sources []Source
	docs := chromaResp.Documents[0]
	metas := chromaResp.Metadatas[0]

	for i, doc := range docs {
		s := Source{Text: doc}
		if i < len(metas) && metas[i] != nil {
			if sf, ok := metas[i]["source_file"].(string); ok {
				s.SourceFile = sf
			}
			if pg, ok := metas[i]["page_label"].(string); ok {
				s.Page = pg
			}
		}
		sources = append(sources, s)
	}
	return sources, nil
}

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

	systemPrompt := `You are Faraday, a survival reference assistant. Answer the user's question using ONLY the provided source material below. Rules:
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
