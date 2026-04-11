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
│  ┌────────────┐  ┌──────────┐  ┌──────────────────┐     │
│  │  Ollama     │  │ ChromaDB │  │  Kiwix-serve     │     │
│  │  - Gemma 4  │  │          │  │  - Wiki EN/ES    │     │
│  │    E4B      │  │          │  │  - WikiMed       │     │
│  │  - nomic-   │  │          │  │  - StackExchange │     │
│  │    embed    │  │          │  │                    │     │
│  └────────────┘  └──────────┘  └──────────────────┘     │
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
| **Ollama** | Container or binary | 11434 | ~3 GB (both models) | `./data/ollama/` |
| **ChromaDB** | Container or binary | 8000 | ~500 MB–1 GB | `./data/chromadb/` |
| **Kiwix-serve** | Binary | 8081 | ~100 MB + page cache | `./datasets/zim/` (RO) |
| **Tile Server** | TBD | 8082 | ~200 MB | `./datasets/osm/` (RO) |
| **Firefox** | Kiosk | — | ~500 MB | — |
| **OS + overhead** | Linux | — | ~1 GB | — |
| **Total** | | | **~5.5–6.5 GB** | |

Leaves ~9.5–10.5 GB for OS page cache, which Kiwix needs for efficient ZIM serving.

### 3.3 No Python in Production

- LlamaIndex runs **only at seed time** on the host machine for ingestion
- The Go binary (`faraday-server`) handles all runtime RAG orchestration:
  - Embeds the user query via Ollama's `/api/embeddings` endpoint
  - Queries ChromaDB's REST API for nearest neighbors
  - Builds the prompt with retrieved chunks + source metadata
  - Calls Ollama's `/api/generate` for the response
  - Merges Kiwix search results for unified search

---

## 4. `faraday-server` — Go Binary Specification

### 4.1 Responsibilities

| Endpoint Pattern | Function |
|-----------------|----------|
| `GET /` | Serve SPA (Arrow.js) |
| `POST /api/chat` | RAG orchestration: embed query → ChromaDB → build prompt → Ollama → stream response |
| `GET /api/search?q=` | Unified search: query both ChromaDB and Kiwix, merge results |
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
faraday-server embeds query via Ollama /api/embeddings
        │
        ▼
Query ChromaDB for top-k nearest chunks (k=5)
        │
        ▼
Build prompt:
  [system prompt (mode-dependent)]
  [retrieved chunks with source citations]
  [user query]
        │
        ▼
Stream response from Ollama /api/generate
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
- RAG: nomic-embed-text handles multilingual queries adequately for this use case
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
OllamaEmbedding (model="nomic-embed-text")
        │
        ▼
ChromaVectorStore (persist to ./data/chromadb/)
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
  ollama_base_url: http://localhost:11434
  chroma_persist_dir: ./data/chromadb
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
| Inference | Ollama (llama.cpp), CPU-only |

### 7.2 Embedding Model — nomic-embed-text

| Property | Value |
|----------|-------|
| Model | `nomic-embed-text` |
| Dimensions | 768 |
| Max Tokens | 8192 |
| Size | ~270 MB |

### 7.3 NPU — Not Used

CPU-only inference. RKNPU2 requires RKNN model conversion and is not supported by Ollama/llama.cpp. Not worth the engineering investment for this project.

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
| LLM + Embedding Models | ~3.3 GB |
| RAG PDFs + ChromaDB Vectors | ~3 GB |
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
│   ├── ollama/                 # Model weights
│   ├── chromadb/               # Vector embeddings
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
  ollama:
    image: ollama/ollama
    ports: ["11434:11434"]
    volumes: ["./data/ollama:/root/.ollama"]

  chromadb:
    image: chromadb/chroma
    ports: ["8000:8000"]
    volumes: ["./data/chromadb:/chroma/chroma"]

  kiwix:
    image: kiwix/kiwix-serve
    ports: ["8081:80"]
    command: /data/*.zim
    volumes: ["./datasets/zim:/data:ro"]
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
   - Copy `data/ollama/` (model weights)
   - Copy `data/chromadb/` (vector index)
   - Copy `datasets/zim/` (ZIM archives)
   - Copy `datasets/osm/` (planet file + pre-rendered tiles)
   - Copy `data/media/` (user content)
   - Install systemd services for Ollama, ChromaDB, Kiwix, tile server, faraday-server
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
   - Ollama (loads models into RAM) (~15-20s)
   - ChromaDB (~5s)
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
| ChromaDB corruption | RAG stops working | Encyclopedia tab (Kiwix) still works as fallback; raw PDFs still on disk |
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
| 5 | No Open WebUI | Custom Arrow.js SPA — simpler, lighter, purpose-built |
| 6 | No NPU | RKNN conversion not worth engineering cost; CPU inference is adequate |
| 7 | No automatic failover | Manual swap saves power and complexity |
| 8 | No update mechanism | Seeded once, never updated — doomsday assumption |
| 9 | Two AI modes | Reference (safe, cited) and General (flexible, warned) |
| 10 | Flat media directories | Simplicity over organization |
| 11 | Full planet OSM | Unknown deployment location |
| 12 | Arrow.js + Go | Minimal dependencies, debuggable in a pinch |
