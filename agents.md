# LefinOS — Architecture Decisions

## Design Philosophy

**Lean. Offline. Indestructible.**

Every dependency must justify its existence. Every watt matters. This is a doomsday box — seeded once, never updated, runs until the hardware dies.

## Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Server** | Go (`lefin-server`) | Single binary, no runtime, cross-compiles to ARM64, debuggable in a pinch |
| **Frontend** | TypeScript + Arrow.js + Bun | Strict types everywhere, ~2KB reactive framework, Bun bundles to a single 23KB JS file |
| **Inference** | llama.cpp (`llama-server`) | Direct GGUF loading, OpenAI-compatible API, no Python runtime needed, CPU-only |
| **Embeddings** | llama.cpp (`llama-embed`) | Same binary, separate instance, `/v1/embeddings` endpoint |
| **Vector DB** | Qdrant (storage mode) | On-disk vectors + payloads, ~100MB RAM, survives power loss |
| **Ingestion** | Python + LlamaIndex | Runs once at seed time on the host, not on the device |
| **Encyclopedias** | Kiwix | Battle-tested ZIM serving, ~100MB RAM |
| **UI Theme** | Fallout Pip-Boy terminal | CRT scanlines, amber glow, monospace — because the apocalypse should look right |

## Architecture Decisions

### TypeScript everywhere (frontend)

All frontend code is TypeScript with strict mode. Bun bundles it. No webpack, no vite, no babel. One command: `bun build src/app.ts --outdir ../static --minify`.

Arrow.js is the UI framework — 2KB, reactive, no virtual DOM, no build step required. We augment its types via `arrow.d.ts` for strict TS compatibility.

### No framework bloat

- No React, Vue, Svelte, or Next.js
- No tailwind — hand-written CSS with CRT effects
- No state management library — Arrow.js `reactive()` is the store
- No router — tab switching via reactive state

### Fallout terminal aesthetic

The UI is styled after the Pip-Boy 3000 from Fallout:
- **CRT frame** with rounded bezel and inset shadows
- **Scanline overlay** via repeating CSS gradient
- **Amber text glow** (`text-shadow: 0 0 0.8rem`) on all text
- **Boot flicker animation** on page load
- **Gradient edge borders** that fade in the middle
- Roboto Mono everywhere

Color scheme is configurable via CSS custom properties (`--main`, `--alt`).

### llama.cpp over Ollama

Ollama wraps llama.cpp with a Go service layer and model management. We don't need any of that:
- Model files are GGUF files on disk — no registry, no pulling
- llama.cpp server exposes OpenAI-compatible `/v1/` API natively
- Open WebUI connects to it with zero configuration
- One fewer abstraction layer = one fewer thing to break

### Qdrant over ChromaDB

ChromaDB stores everything in RAM by default. On a 16GB node running an LLM, that's fatal. Qdrant with `on_disk: true` keeps vectors and payloads on NVMe, using ~100MB RAM regardless of dataset size.

### Two llama-server instances

Chat and embeddings use different models with different settings. Running them as separate processes means:
- Each can be sized independently
- Embedding requests don't block inference
- A crash in one doesn't kill the other

### Go server does RAG orchestration

No Python in production. The Go binary handles:
1. Embed query → llama-embed `/v1/embeddings`
2. Search → Qdrant `/collections/{name}/points/search`
3. Build prompt with source chunks
4. Stream → llama-server `/v1/chat/completions` (SSE)

This means the production runtime is: Go binary + two llama.cpp instances + Qdrant + Kiwix. No Python, no pip, no virtualenv.

### Open WebUI as optional secondary interface

The custom SPA is the primary interface — purpose-built for the 10.6" touchscreen. Open WebUI connects to the same llama-server and is available on `:3000` for users who prefer a richer chat interface. It auto-connects via `OPENAI_API_BASE_URLS` with no manual setup.

## Dependencies (total)

### Production (on device)
- `lefin-server` — single Go binary (~8MB)
- `llama-server` — single C++ binary (~5MB)
- `qdrant` — single Rust binary (~30MB)
- `kiwix-serve` — single C++ binary (~5MB)
- Frontend: one HTML file, one CSS file, one 23KB JS bundle

### Build time
- Go 1.26+
- Bun 1.x
- `@arrow-js/core` (2KB)
- `typescript` (dev only)

### Seed time (host machine only)
- Python 3.11+
- `llama-index-core`, `llama-index-readers-file`, `llama-index-embeddings-openai`, `llama-index-vector-stores-qdrant`
- `qdrant-client`

## File Structure

```
/workspace/
├── cmd/lefin-server/     # Go server source
│   ├── main.go             # HTTP server, routes, streaming
│   ├── rag.go              # RAG orchestration (embed, search, prompt)
│   ├── main_test.go        # Server tests
│   └── rag_test.go         # RAG integration tests (mock backends)
├── frontend/               # TypeScript source
│   ├── src/
│   │   ├── app.ts          # Arrow.js SPA
│   │   ├── api.ts          # API client (health, streaming chat)
│   │   ├── types.ts        # Shared type definitions
│   │   └── arrow.d.ts      # Arrow.js type augmentation
│   ├── package.json
│   └── tsconfig.json
├── static/                 # Served by lefin-server
│   ├── index.html
│   ├── style.css           # Pip-Boy theme
│   └── app.js              # Built by bun (gitignored)
├── src/ingestion/
│   └── pipeline.py         # LlamaIndex ingestion (seed time only)
├── data/                   # Runtime data (gitignored)
│   ├── models/             # GGUF files
│   ├── qdrant/             # Vector storage
│   └── media/              # Movies, music, books, games
├── datasets/               # Source content (gitignored)
│   ├── raw/                # PDFs for RAG ingestion
│   ├── zim/                # Kiwix archives
│   └── osm/                # OpenStreetMap data
├── plans/
│   └── faraday-os-prd.md   # Product requirements
├── docker-compose.yml
├── Makefile
├── .env                    # Model configuration
└── requirements.txt        # Python deps (seed time)
```
