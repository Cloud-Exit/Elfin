# Elfin — Architecture Decisions

*May it be a light to you in dark places, when all other lights go out.*

## Design Philosophy

**Lean. Offline. Indestructible.**

Every dependency must justify its existence. Every watt matters. This is a survival companion — seeded once, never updated, runs until the hardware dies.

## Stack

### Application Layer (TypeScript)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Desktop** | Electrobun | Bun-native, single runtime, lighter than Electron |
| **Frontend** | React 19 + React Router | Mature, assistant-ui integration, large ecosystem |
| **AI Chat UI** | assistant-ui | Streaming chat, tool calls, message history |
| **App Backend** | Bun (TypeScript) | HTTP server, auth, API routes, media serving |
| **Database** | Prisma + SQLite | Type-safe ORM, zero-server DB, survives power loss |
| **Theme** | Pip-Boy / Fallout terminal | CRT scanlines, amber glow, Roboto Mono |

### AI Layer (Python)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Ingestion** | LlamaIndex | PDF chunking, embedding, vector indexing |
| **Embeddings** | OpenAI-compatible client | Calls llama-embed /v1/embeddings |
| **Vector Store** | qdrant-client | Writes to Qdrant on-disk storage |

### Infrastructure (pre-built binaries)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Inference** | llama.cpp (llama-server) | GGUF loading, OpenAI-compatible API, multimodal vision |
| **Embeddings** | llama.cpp (llama-embed) | Separate instance, nomic-embed-text |
| **Vector DB** | Qdrant (on-disk storage) | ~100 MB RAM, vectors/payloads on NVMe |
| **Encyclopedias** | Kiwix-serve | ZIM file serving, verification source |

## Key Decisions

### Right tool for the right job

TypeScript for the application layer — UI, backend server, database, auth, API routes. Python for all AI/ML work — ingestion, embeddings, data pipelines. Both are debuggable and well-understood. Neither replaces the other.

### Bun for the app, not for AI

Bun runs the HTTP server, builds the frontend, manages the database via Prisma. It does NOT do AI work. LlamaIndex and qdrant-client are Python libraries with no TypeScript equivalent of the same maturity.

### llama.cpp over Ollama

Ollama wraps llama.cpp with model management we don't need. Our models are GGUF files on disk — no registry, no pulling. llama-server exposes OpenAI-compatible `/v1/` APIs natively.

### Qdrant over ChromaDB

ChromaDB stores vectors in RAM. On a 16 GB device running an 8 GB LLM, that's fatal. Qdrant with `on_disk: true` keeps everything on NVMe, using ~100 MB RAM.

### Verified-only trust model

The AI can analyze images (Gemma 4 vision), but ONLY presents results it can cross-reference against the vector DB or Kiwix encyclopedia. Unverified visual identification is never presented as fact. Verified results include a direct link to the Kiwix source article.

### AI health tracking with personal baseline

Each user gets a baseline health interview on first use. All future health assessments are relative to that baseline — a user with known vision issues isn't flagged for stable symptoms. Scores are 1-10, computed from rolling check-in data, always labeled "AI-estimated."

### 16 GB RAM

With Q5_K_M, baseline allocation is ~10-12 GB (model + mmproj + embed + services + OS), leaving ~4-6 GB of unallocated headroom for vision bursts, prompt/context growth, and avoiding swap pressure. Linux will use any idle portion as opportunistic page cache, but no RAM is reserved for it. On-disk vector storage keeps Qdrant minimal. If field testing shows pressure, reduce `CHAT_CTX_SIZE` to 4096. Upgrade to 32 GB modules to switch to Q8_K_XL for better quality.

## Model Configuration

### Gemma 4 E4B — pick quant for your hardware

| Quant | File | RAM Required | Use Case |
|-------|------|-------------|----------|
| Q3_K_M | `gemma-4-E4B-it-Q3_K_M.gguf` | 8 GB | Text-first / low-memory profile |
| **Q5_K_M** | **`gemma-4-E4B-it-Q5_K_M.gguf`** | **16 GB** | **Default — our RK1 is 16 GB** |
| Q8_K_XL | `gemma-4-E4B-it-UD-Q8_K_XL.gguf` | 32 GB+ | Maximum quality |

All quants from [unsloth/gemma-4-E4B-it-GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF).

Vision requires the multimodal projector: `mmproj-F16.gguf` (same repo).

### Embedding model

| Model | File | RAM | Purpose |
|-------|------|-----|---------|
| nomic-embed-text | `nomic-embed-text-v1.5.Q8_0.gguf` | ~270 MB | Document embeddings for RAG |

## Implementation Order

AI pipeline first, application last:

1. **Phase 1 — AI Foundation:** Docker infra, datasets, Python ingestion, RAG from CLI, vision, verified trust model
2. **Phase 2 — Data Layer:** Prisma + SQLite, auth, journal/check-in CRUD
3. **Phase 3 — AI + Data Integration:** Baseline interview, daily check-ins, per-user context, health scoring
4. **Phase 4 — Application:** Electrobun + React shell, all pages, i18n

## File Structure

```
/elfin/
├── src/
│   ├── backend/               # Bun HTTP server (TypeScript)
│   │   ├── server.ts
│   │   ├── auth.ts
│   │   ├── rag.ts
│   │   ├── journal.ts
│   │   ├── health.ts
│   │   ├── media.ts
│   │   └── kiwix.ts
│   ├── frontend/              # React 19 app (TypeScript)
│   │   ├── main.tsx
│   │   ├── router.tsx
│   │   ├── components/
│   │   ├── pages/
│   │   └── theme/
│   ├── ingestion/             # AI data pipeline (Python)
│   │   └── pipeline.py
│   └── shared/
│       └── types.ts
├── prisma/
│   └── schema.prisma
├── data/
│   ├── models/                # GGUF files
│   ├── qdrant/                # Vector storage
│   ├── photos/                # User photos
│   └── media/                 # Movies, music, books, games
├── datasets/
│   ├── raw/                   # PDFs for RAG
│   └── zim/                   # Kiwix ZIM files
├── docker-compose.yml
├── package.json               # Bun/TypeScript deps
├── requirements.txt           # Python AI deps
├── tsconfig.json
└── .env
```
