# Faraday-OS — Product Requirements Document

**Project:** Faraday-OS (Air-Gapped Survival Intelligence Appliance)
**Target Hardware:** Single RK3588 RK1 (16 GB RAM, 4 TB NVMe), 10.6" 1280x800 touchscreen
**Power:** 20,000 mAh battery (~74 Wh) + solar charger
**Version:** 5.0 — reviewed
**Date:** 2026-04-10
**Status:** APPROVED after design review

---

## 1. Executive Summary

Faraday-OS is a doomsday-grade, offline-only intelligence appliance. It is seeded once via SSH from a host machine and never receives another update. It runs on a single RK1 compute module powered by a 20,000 mAh battery + solar charger, with cold spare modules and cloned NVMes for hardware redundancy.

The system provides:

1. **RAG-powered Q&A** over survival, medical, and technical manuals — with mandatory source citations and extracted illustrations
2. **Offline encyclopedias** (Wikipedia EN/ES, WikiMed, StackExchange) via Kiwix
3. **Offline mapping** (full planet OpenStreetMap)
4. **Entertainment** — movies, music, books, retro gaming (MSX2 + SNES)
5. **Bilingual interface** — English and Spanish, user-selectable

Design priorities: **power efficiency > simplicity > capability**. Every watt and byte of RAM must justify itself.

---

## 2. Hardware Constraints

### 2.1 Active Compute Node

| Resource | Specification |
|----------|--------------|
| SoC | Rockchip RK3588 (4x A76 + 4x A55) |
| RAM | 16 GB LPDDR4x |
| Storage | 4 TB NVMe |
| NPU | 6 TOPS RKNPU2 (unused — CPU-only inference) |
| Display | 10.6" 1280x800 touchscreen |
| Network | None in production (air-gapped) |

### 2.2 Power Budget

| State | Estimated Draw | Battery Life (74 Wh) |
|-------|---------------|---------------------|
| Active inference | ~15-20W | 3.5–5 hours |
| Idle (services running) | ~8-10W | 7–9 hours |
| Suspend-to-RAM | ~0.5W | ~6 days |

Solar input (~40-60W in good sun) can sustain active use during daylight. System should auto-suspend after configurable idle timeout.

### 2.3 Redundancy Model

- **Cage slots** for multiple RK1 modules — only one active at any time
- **Cold spares** — unpowered, identical NVMe clones from seed time
- **Failover is manual** — user swaps the dead module, boots the spare
- **No automatic failover** — saves power and complexity

### 2.4 Seeding & Lifecycle

- All software, models, datasets, and media loaded via SSH at provisioning time
- System is fully air-gapped after seeding — **zero network dependencies forever**
- No update mechanism. No USB updates. Seeded once, runs until hardware dies.
- Spare NVMes are cloned at seed time and never modified

---

## 3. System Architecture

### 3.1 Production Runtime — Single Node

```
┌─────────────────────────────────────────────────────────┐
│                   Single RK1 Node                        │
│                                                           │
│  ┌──────────────────────────────────────────────────┐    │
│  │  faraday-server (Go binary)                       │    │
│  │  ┌──────────────────────────────────────────┐     │    │
│  │  │  Static SPA (Arrow.js)                    │     │    │
│  │  │  - Ask AI (Reference / General mode)      │     │    │
│  │  │  - Encyclopedia (Kiwix proxy)             │     │    │
│  │  │  - Maps (tile server proxy)               │     │    │
│  │  │  - Movies / Music / Books / Games         │     │    │
│  │  └──────────────────────────────────────────┘     │    │
│  │                                                    │    │
│  │  RAG orchestration (ChromaDB query → prompt build) │    │
│  │  Unified search (RAG + Kiwix merge)                │    │
│  │  Media directory listing API                       │    │
│  │  Reverse proxy to all backend services             │    │
│  └──────────────────────────────────────────────────┘    │
│                                                           │
│  ┌──────────────┐  ┌────────┐  ┌──────────────────┐     │
│  │ llama-server  │  │ Qdrant │  │  Kiwix-serve     │     │
│  │ (Gemma 4 E4B) │  │(on-disk│  │  - Wiki EN/ES    │     │
│  │               │  │storage)│  │  - WikiMed       │     │
│  │ llama-embed   │  │        │  │  - StackExchange │     │
│  │ (nomic-embed) │  │        │  │                    │     │
│  └──────────────┘  └────────┘  └──────────────────┘     │
│                                                           │
│  ┌──────────────────┐                                    │
│  │  Tile Server      │                                    │
│  │  (full planet OSM)│                                    │
│  └──────────────────┘                                    │
│                                                           │
│  Firefox (kiosk mode) → http://localhost:8080             │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Service Definitions

| Service | Runtime | Port | RAM Budget | Persistent Data |
|---------|---------|------|-----------|----------------|
| **faraday-server** | Go binary | 8080 | ~50 MB | SPA assets, config |
| **llama-server** | llama.cpp (chat) | 8081 | ~2.5 GB (Gemma 4 E4B Q4_K_M) | `./data/models/` |
| **llama-embed** | llama.cpp (embed) | 8082 | ~270 MB (nomic-embed-text) | `./data/models/` |
| **Qdrant** | Container or binary | 6333 | ~100 MB (on-disk storage) | `./data/qdrant/` |
| **Kiwix-serve** | Binary | 8083 | ~100 MB + page cache | `./datasets/zim/` (RO) |
| **Tile Server** | TBD | 8084 | ~200 MB | `./datasets/osm/` (RO) |
| **Open WebUI** | Container (optional) | 3000 | ~300 MB | `./data/open-webui/` |
| **Firefox** | Kiosk | — | ~500 MB | — |
| **OS + overhead** | Linux | — | ~1 GB | — |
| **Total** | | | **~5–5.5 GB** | |

Leaves ~9.5–10.5 GB for OS page cache, which Kiwix needs for efficient ZIM serving.

### 3.3 No Python in Production

- LlamaIndex runs **only at seed time** on the host machine for ingestion
- The Go binary (`faraday-server`) handles all runtime RAG orchestration:
  - Embeds the user query via llama-embed's OpenAI-compatible `/v1/embeddings` endpoint
  - Queries Qdrant's REST API for nearest neighbors
  - Builds the prompt with retrieved chunks + source metadata
  - Calls llama-server's OpenAI-compatible `/v1/chat/completions` with streaming
  - Merges Kiwix search results for unified search
- **Open WebUI integration:** llama-server exposes an OpenAI-compatible API — Open WebUI connects automatically with zero configuration

---

## 4. `faraday-server` — Go Binary Specification

### 4.1 Responsibilities

| Endpoint Pattern | Function |
|-----------------|----------|
| `GET /` | Serve SPA (Arrow.js) |
| `POST /api/chat` | RAG orchestration: embed query → Qdrant → build prompt → llama-server → stream response |
| `GET /api/search?q=` | Unified search: query both Qdrant and Kiwix, merge results |
| `GET /api/mode` / `PUT /api/mode` | Get/set AI mode (reference / general) |
| `GET /api/lang` / `PUT /api/lang` | Get/set language (en / es) |
| `GET /wiki/*` | Reverse proxy to Kiwix-serve |
| `GET /maps/*` | Reverse proxy to tile server |
| `GET /api/media/:type` | JSON directory listing (movies, music, books, games) |
| `GET /media/*` | Static file serving for media content |

### 4.2 RAG Pipeline (Runtime)

```
User query ("How do I purify water?")
        │
        ▼
faraday-server embeds query via llama-embed /v1/embeddings
        │
        ▼
Query Qdrant for top-k nearest chunks (k=5)
        │
        ▼
Build prompt:
  [system prompt (mode-dependent)]
  [retrieved chunks with source citations]
  [user query]
        │
        ▼
Stream response from llama-server /v1/chat/completions (SSE)
        │
        ▼
Return to SPA: { answer, sources[ {text, document, page, image?} ] }
```

### 4.3 AI Modes

**Reference Mode** (default):
- System prompt enforces answering ONLY from retrieved source material
- Every answer includes source citations (document name, page/section)
- Retrieved source chunks displayed alongside the LLM summary
- Extracted manual illustrations shown when available
- If no relevant sources found: "I don't have information on that in my reference materials. Try the Encyclopedia tab."

**General Mode** (user-toggled):
- Persistent UI banner: "General mode — answers may be inaccurate. Verify critical information in the Encyclopedia."
- RAG-first: still queries ChromaDB, uses sources if available
- Falls back to base model knowledge when no sources match
- Citations shown when source material was used

### 4.4 Bilingual Support

- UI text: static translations in the SPA (en/es JSON files)
- System prompts: separate en/es versions
- RAG: nomic-embed-text via llama-embed handles multilingual queries adequately for this use case
- Kiwix: separate Wikipedia EN and ES ZIM files, language toggle switches which is queried
- User selects language once; persisted in localStorage

---

## 5. Frontend — Arrow.js SPA

### 5.1 Technology

- **Arrow.js** — minimal reactive UI framework
- **Player.js** — video and audio playback
- **Nostalgist** — browser-based RetroArch (MSX2 + SNES cores)
- No build step preferred — vanilla JS modules, or minimal bundler
- Designed for 1280x800 resolution, touch-friendly

### 5.2 Navigation

```
┌─────────────────────────────────────┐
│  [AI]  [Encyclopedia]  [Maps]       │
│  [Movies] [Music] [Books] [Games]   │
│  [EN/ES toggle]    [Ref/Gen toggle] │
├─────────────────────────────────────┤
│                                     │
│         Content Area                │
│                                     │
└─────────────────────────────────────┘
```

### 5.3 Tab Specifications

**Ask AI:**
- Search bar at top
- Streaming response display
- Source chunks displayed below response (non-collapsible in Reference Mode)
- Manual illustrations shown inline when available
- Mode toggle (Reference / General) clearly visible

**Encyclopedia:**
- Proxied Kiwix interface
- Full-text search across all ZIM files
- Language toggle switches between EN/ES Wikipedia

**Maps:**
- Full planet OSM rendered via tile server
- Pan, zoom, search by place name
- Offline — all tiles served locally

**Movies:**
- Flat list from `/api/media/movies`
- Click to play via Player.js (480p MP4)
- Simple filename-based listing, no metadata

**Music:**
- Flat list from `/api/media/music`
- Click to play via Player.js
- Basic transport controls (play/pause/skip)

**Books:**
- Flat list from `/api/media/books`
- EPUB: rendered in-browser (epub.js or similar)
- PDF: rendered via browser native or pdf.js

**Games:**
- Two sections: MSX2 and SNES
- Click to launch via Nostalgist with appropriate core
- `fMSX` core for MSX2, `snes9x` core for SNES

---

## 6. Data Ingestion Pipeline (Seed Time Only)

### 6.1 Runs on Host Machine, Not on RK1

The ingestion pipeline is a Python script using LlamaIndex that runs on the provisioning host. It produces a ChromaDB database that is copied to the RK1's NVMe.

### 6.2 Pipeline

```
datasets/raw/*.pdf,*.md,*.txt
        │
        ▼
SimpleDirectoryReader (with image extraction)
        │
        ▼
SentenceSplitter (chunk_size=1024, chunk_overlap=200)
        │
        ▼
OpenAI-compatible embeddings via llama-embed /v1/embeddings
        │
        ▼
QdrantVectorStore (on-disk storage, ./data/qdrant/)
```

### 6.3 Image Extraction

- PDF illustrations extracted during parsing
- Stored as base64 metadata alongside their surrounding text chunks in ChromaDB
- At query time, `faraday-server` returns matching images with source chunks
- SPA renders them inline below the AI response

### 6.4 Configuration

```yaml
ingestion:
  source_dir: ./datasets/raw
  chunk_size: 1024
  chunk_overlap: 200
  embedding_model: nomic-embed-text
  embed_url: http://localhost:8082
  qdrant_url: http://localhost:6333
  batch_size: 50
  extract_images: true
```

### 6.5 Idempotency

- Documents tracked by SHA256 hash
- Re-running skips already-indexed documents
- Full re-index available via flag (`--force`)

---

## 7. Model Selection

### 7.1 Generative LLM — Gemma 4 E4B

| Property | Value |
|----------|-------|
| Model | `unsloth/gemma-4-E4B-it-GGUF` |
| Parameters | ~4B (Per-Layer Embeddings) |
| Context Window | 128K tokens |
| Quantization | Q4_K_M (~2.5 GB) |
| GGUF Source | `huggingface.co/unsloth/gemma-4-E4B-it-GGUF` |
| Inference | llama.cpp (`llama-server`), CPU-only, OpenAI-compatible API |

### 7.2 Embedding Model — nomic-embed-text

| Property | Value |
|----------|-------|
| Model | `nomic-embed-text` |
| Dimensions | 768 |
| Max Tokens | 8192 |
| Size | ~270 MB |

### 7.3 NPU — Not Used

CPU-only inference. RKNPU2 requires RKNN model conversion and is not supported by llama.cpp. Not worth the engineering investment for this project.

### 7.4 Model Configuration

Models are configurable via `.env` file:
- `CHAT_MODEL` — GGUF filename for chat (default: `gemma-4-e4b-it-Q4_K_M.gguf`)
- `EMBED_MODEL` — GGUF filename for embeddings (default: `nomic-embed-text-v1.5.Q8_0.gguf`)

All GGUF files are placed in `data/models/` and mounted read-only into the llama-server containers.

---

## 8. Dataset Manifest

### 8.1 Dynamic RAG Datasets (Ingested into ChromaDB)

| Dataset | Format | Size | Source |
|---------|--------|------|--------|
| US Army Survival Manual (FM 3-05.70) | PDF | ~15 MB | archive.org |
| SF Medical Handbook (ST 31-91B) | PDF | ~25 MB | archive.org |
| Where There Is No Doctor | PDF | ~30 MB | hesperian.org |
| RK3588 TRM & Turing Pi Docs | PDF/MD | ~50 MB | github.com/rockchip-linux |

### 8.2 Static Archives (Kiwix ZIM)

| Dataset | Size |
|---------|------|
| Wikipedia English (All Maxi) | ~100 GB |
| Wikipedia Spanish (All Maxi) | ~40 GB |
| WikiMed (Medical Encyclopedia) | ~5 GB |
| StackExchange (Hardware/Unix) | ~10 GB |

### 8.3 Geospatial

| Dataset | Size |
|---------|------|
| OpenStreetMap Full Planet (.osm.pbf) | ~70 GB |

### 8.4 Media (User-Provided at Seed Time)

| Category | Location | Formats |
|----------|----------|---------|
| Movies | `/data/media/movies/` | .mp4 (480p) |
| Music | `/data/media/music/` | .mp3, .flac, .ogg |
| Books | `/data/media/books/` | .epub, .pdf |
| Games (SNES) | `/data/media/games/snes/` | .sfc, .smc |
| Games (MSX2) | `/data/media/games/msx2/` | .rom |

### 8.5 Storage Budget (4 TB NVMe)

| Category | Size |
|----------|------|
| ZIM Archives | ~155 GB |
| OSM Data | ~70 GB |
| LLM + Embedding Models (GGUF) | ~3.3 GB |
| RAG PDFs + Qdrant Vectors | ~3 GB |
| OS + Containers + faraday-server | ~5 GB |
| Media (user content) | Variable |
| **Subtotal (system)** | **~236 GB** |
| **Free for media** | **~3.7 TB** |

---

## 9. Directory Structure

```
/faraday-os/
├── faraday-server              # Go binary
├── config.yaml                 # Server configuration
├── static/                     # SPA assets (Arrow.js, Player.js, Nostalgist)
│   ├── index.html
│   ├── app.js
│   ├── i18n/
│   │   ├── en.json
│   │   └── es.json
│   └── lib/                    # Arrow.js, Player.js, Nostalgist bundles
├── data/
│   ├── models/                 # GGUF model files (chat + embed)
│   ├── qdrant/                 # Qdrant on-disk vector storage
│   ├── open-webui/             # Open WebUI data (optional)
│   └── media/
│       ├── movies/             # Flat: *.mp4
│       ├── music/              # Flat: *.mp3, *.flac, *.ogg
│       ├── books/              # Flat: *.epub, *.pdf
│       └── games/
│           ├── snes/           # *.sfc, *.smc
│           └── msx2/           # *.rom
├── datasets/
│   ├── raw/                    # Source PDFs/MDs (kept for reference)
│   ├── zim/                    # Kiwix ZIM archives
│   └── osm/                    # OpenStreetMap planet file + tiles
└── logs/                       # faraday-server logs
```

---

## 10. Development Environment

### 10.1 Local Dev Stack (Docker Compose)

For development on x86_64 or Apple Silicon:

```yaml
services:
  llama-server:
    image: ghcr.io/ggml-org/llama.cpp:server
    ports: ["8081:8081"]
    volumes: ["./data/models:/models:ro"]
    command: -m /models/${CHAT_MODEL} --port 8081 --host 0.0.0.0 -c 8192

  llama-embed:
    image: ghcr.io/ggml-org/llama.cpp:server
    ports: ["8082:8082"]
    volumes: ["./data/models:/models:ro"]
    command: -m /models/${EMBED_MODEL} --port 8082 --host 0.0.0.0 --embedding

  qdrant:
    image: qdrant/qdrant
    ports: ["6333:6333"]
    volumes: ["./data/qdrant:/qdrant/storage"]

  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    ports: ["3000:8080"]
    environment:
      OPENAI_API_BASE_URLS: http://llama-server:8081/v1
      OPENAI_API_KEYS: not-needed
```

`faraday-server` runs natively on the host during development (`go run .`).

### 10.2 Reduced Dev Dataset

- WikiMed ZIM only (~5 GB) instead of full Wikipedia
- 1-2 sample PDFs for RAG testing
- No OSM data in dev (mock tile responses)

### 10.3 Makefile

```makefile
make dev            # Run faraday-server + all backend services
make ingest         # Run Python ingestion pipeline
make test           # Go tests + ingestion integration tests
make build-arm64    # Cross-compile faraday-server for ARM64
make seed           # SSH full deployment to target RK1
make clone-nvme     # Create NVMe clone for spare modules
```

---

## 11. Seeding & Deployment

### 11.1 Seed Process (One-Time, via SSH from Host)

1. Cross-compile `faraday-server` for ARM64
2. Run ingestion pipeline on host (produces ChromaDB data)
3. SSH to RK1:
   - Copy `faraday-server` binary + SPA assets
   - Copy `data/models/` (GGUF model files)
   - Copy `data/qdrant/` (vector index)
   - Copy `datasets/zim/` (ZIM archives)
   - Copy `datasets/osm/` (planet file + pre-rendered tiles)
   - Copy `data/media/` (user content)
   - Install systemd services for llama-server, llama-embed, Qdrant, Kiwix, tile server, faraday-server
   - Configure Firefox kiosk mode to open `http://localhost:8080` on boot
4. Verify: reboot RK1, confirm all services start, test each tab

### 11.2 NVMe Cloning (for Spares)

After successful seed + verification:
- `dd` or filesystem-level clone the active NVMe to each spare
- Verify each spare boots identically
- Store spares unpowered in the cage

---

## 12. Boot Sequence (Production)

1. Power on → Linux boots (~10s)
2. systemd starts services in order:
   - llama-server (loads Gemma 4 E4B into RAM) (~15-20s)
   - llama-embed (loads nomic-embed-text) (~5s)
   - Qdrant (~5s)
   - Kiwix-serve (~5s)
   - Tile server (~5s)
   - faraday-server (~1s)
3. Firefox launches in kiosk mode → `http://localhost:8080` (~5s)
4. **User sees the Faraday-OS interface within ~45 seconds of power-on**

---

## 13. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LLM hallucination in Reference Mode | Dangerous misinformation for survival/medical | Mandatory source chunk display; strict system prompt; model cannot answer without retrieved context |
| NVMe failure | Total system loss | Cold spare modules with cloned NVMes |
| Battery exhaustion at night | System dies | Suspend-to-RAM after idle timeout; user education on power management |
| Solar panel damage | No recharge | Battery budgeting — limit use to essential queries |
| Gemma 4B insufficient quality | Poor RAG answers | Tight chunking strategy; high-quality source documents; model is convenience layer over raw sources |
| Qdrant storage corruption | RAG stops working | Encyclopedia tab (Kiwix) still works as fallback; raw PDFs still on disk |
| RK3588 thermal throttling | Slow inference | Passive cooling design; inference is bursty not sustained |

---

## 14. Success Criteria

1. **Boot to UI:** Power-on to usable interface in under 60 seconds
2. **RAG accuracy:** Reference Mode answers cite correct manual, section, and page for survival/medical queries
3. **Source display:** Every Reference Mode answer shows the raw source text — user never has to trust the LLM alone
4. **Encyclopedia works:** Wikipedia EN, ES, and WikiMed searchable and browsable via Kiwix
5. **Maps work:** Full planet OSM navigable with pan/zoom/search
6. **Media works:** Movies play in Player.js, music plays, books render, SNES and MSX2 games launch in Nostalgist
7. **Power efficiency:** System draws under 20W during active inference, under 10W idle
8. **Failover:** Swapping to a spare module and booting produces an identical working system
9. **Dev parity:** `make dev` on a host machine runs the full stack locally for development
10. **Bilingual:** Full UI and AI interaction in both English and Spanish

---

## 15. Resolved Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Single active node, cold spares | Power budget (74 Wh) cannot sustain multi-node |
| 2 | 16 GB RAM | Required for LLM + services + page cache |
| 3 | No image generation | Manual illustrations extracted from source PDFs are more accurate and free |
| 4 | No Python in production | Go binary handles RAG orchestration; Python only at seed time |
| 5 | Open WebUI available as optional secondary interface | Auto-connects to llama-server's OpenAI-compatible API — zero config |
| 6 | No NPU | RKNN conversion not worth engineering cost; CPU inference is adequate |
| 7 | No automatic failover | Manual swap saves power and complexity |
| 8 | No update mechanism | Seeded once, never updated — doomsday assumption |
| 9 | Two AI modes | Reference (safe, cited) and General (flexible, warned) |
| 10 | Flat media directories | Simplicity over organization |
| 11 | Full planet OSM | Unknown deployment location |
| 12 | Arrow.js + Go + llama.cpp + Qdrant | Minimal dependencies, debuggable in a pinch, OpenAI-compatible API |
