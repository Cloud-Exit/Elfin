# Elfin

Offline survival companion for RK3588 hardware. RAG-powered AI chat with medical/preparedness documents, offline encyclopedias, notepad, and health tracking. Designed for air-gapped disaster scenarios where there is no internet, no phone network, and no outside help.

Built for the [Gemma 4 Good Hackathon](https://www.kaggle.com/competitions/gemma-4-good-hackathon).

## What it does

- **AI Chat** with retrieval-augmented generation: asks a question, retrieves relevant chunks from ingested survival/medical PDFs and Kiwix encyclopedia articles, generates step-by-step instructions with source citations
- **Encyclopedia**: embedded offline Wikipedia, WikiMed, and StackExchange via Kiwix
- **Notepad**: simple note-taking
- **Dashboard**: service health, indexed document count, quick actions

The AI is tuned for instruction-style responses: numbered action steps with specific details (amounts, timing, materials), warning signs, and cited sources. No disclaimers, no "call 911."

## Architecture

```
Browser (React 19)
  |
Bun HTTP server (port 8885)
  |--- Prisma ORM ---> SQLite (data/elfin.db)
  |--- SSE streaming ---> llama-server (port 8081) -- Gemma 4 E2B IQ4_XS
  |--- embeddings ------> llama-embed  (port 8082) -- nomic-embed-text v1.5
  |--- vector search ----> Qdrant      (port 6333) -- on-disk vectors
  |--- encyclopedia -----> Kiwix       (port 8083) -- ZIM archives
```

On RK3588 hardware, the chat LLM runs natively via [rk-llama.cpp](https://github.com/invisiofficial/rk-llama.cpp) with RKNPU2 acceleration. On x86, it runs in Docker.

## Hardware

Designed for RK3588 SBCs (Turing RK1, Rock 5B, Orange Pi 5).

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| SoC | RK3588 / RK3588S | RK3588 (full NPU) |
| RAM | 8 GB | 16 GB LPDDR4x |
| Storage | 32 GB | 4 TB NVMe |
| Kernel | 5.10.x vendor BSP | 5.10.160-rockchip |
| OS | Ubuntu 22.04 / Armbian | Ubuntu 22.04 LTS |

Mainline 6.x kernels lack the rknpu driver. Use the vendor/BSP kernel.

Also runs on any x86 machine with Docker for development (no NPU acceleration).

## Prerequisites

**Dev machine** (any OS):
- [Bun](https://bun.sh/) >= 1.0
- Python 3.10+
- Docker and Docker Compose v2
- `wget`, `curl`
- [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/main/en/guides/cli) (`hf` or `huggingface-cli`) for model downloads
- `fswatch` (macOS) or `inotifywait` (Linux) for remote file watching

**RK1 target** (if deploying to hardware):
- Docker, Bun, git, cmake, make, g++ (see `docs/rk1-edge-deployment.md`)
- User in `render` and `docker` groups

## Quick start

### 1. Clone and install dependencies

```bash
git clone <repo-url> elfin && cd elfin
make setup
```

This creates a Python venv and installs both Python and Bun dependencies.

### 2. Download all assets

```bash
make download-assets
```

This downloads everything needed to run Elfin:

**Models** (from Hugging Face):
| File | Size | Source |
|------|------|--------|
| `gemma-4-E2B-it-IQ4_XS.gguf` | ~2.8 GB | `unsloth/gemma-4-E4B-it-GGUF` |
| `mmproj-F16.gguf` | ~500 MB | `unsloth/gemma-4-E4B-it-GGUF` |
| `nomic-embed-text-v1.5.Q8_0.gguf` | ~140 MB | `nomic-ai/nomic-embed-text-v1.5-GGUF` |

**Encyclopedias** (from Kiwix, multi-GB each):
| Archive | Content |
|---------|---------|
| `wikipedia_en_all` (nopic) | English Wikipedia |
| `wikipedia_es_all` (nopic) | Spanish Wikipedia |
| `wikipedia_en_medicine` (nopic) | WikiMed medical subset |
| `stackoverflow.com_en_all` | StackOverflow English |

**Survival/medical PDFs** (from CDC, WHO, FEMA, TCCC, EPA):
| Category | Documents |
|----------|-----------|
| Preparedness | FEMA IS-240B, Ready.gov checklists |
| Medical | WHO psychological first aid, TCCC trauma care (burns, fractures, crush syndrome, sepsis, analgesia), CDC wound care, heat illness |
| Water/Sanitation | CDC water safety, EPA disinfection, CDC diarrheal disease prevention |

All assets go into `data/`. If Hugging Face or Kiwix downloads fail, the script retries from `https://elfin.cloud-exit.net/data/`.

To preview what will be downloaded without fetching anything:

```bash
make download-assets-dry-run
```

### 3. Initialize the database

```bash
make db-push
```

### 4. Ingest documents into the vector database

```bash
make services          # start llama-embed, Qdrant, Kiwix
make ingest            # chunk PDFs, embed, index into Qdrant
```

### 5. Run

```bash
make dev
```

Open `http://localhost:8885` in a browser.

## Deploying to RK1

The standard workflow syncs code from your dev machine to the RK1 via SSH with live file watching. Changes on your dev machine automatically rsync and restart the app on the RK1.

### First-time RK1 setup

See `docs/rk1-edge-deployment.md` for kernel, NPU, Docker, and Bun setup on the RK1.

### Deploy

```bash
export ELFIN_REMOTE_HOST=rk1.local        # or IP address
export ELFIN_REMOTE_HOST_USER=stephen
make dev
```

When `ELFIN_REMOTE_HOST` is set, `make dev` automatically:

1. Validates local assets (models, ZIMs, PDFs)
2. Rsyncs the project to the RK1
3. Syncs `data/models/`, `data/datasets/zim/`, `data/datasets/raw/`
4. Pushes `.env` configuration
5. Installs Bun and Docker on the RK1 (if needed)
6. Builds rk-llama.cpp from source (if `TARGET=rockchip`)
7. Starts Docker services (embed, Qdrant, Kiwix)
8. Starts rk-llama.cpp native server (if `TARGET=rockchip`)
9. Runs Prisma migrations
10. Starts the Bun app server
11. Streams logs to your terminal
12. Watches local files and re-syncs on changes

### Remote ingestion

To ingest documents directly on the RK1:

```bash
make ingest-remote          # incremental
make ingest-remote-force    # re-embed everything
```

### Environment variables for remote deploy

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ELFIN_REMOTE_HOST` | yes | | SSH hostname or IP |
| `ELFIN_REMOTE_HOST_USER` | yes | | SSH user |
| `ELFIN_REMOTE_PATH` | no | `/home/$USER/elfin` | Project path on RK1 |
| `ELFIN_REMOTE_PORT` | no | 22 | SSH port |
| `TARGET` | no | `rockchip` | `local` or `rockchip` |
| `DEMO_MODE` | no | `true` | Skip auth |

## RK3588 NPU inference

On RK3588 hardware, the chat model runs natively using [rk-llama.cpp](https://github.com/invisiofficial/rk-llama.cpp) (RKNPU2 backend) instead of Docker.

Manage the native server:

```bash
bash scripts/rk_llama_cpp.sh clone       # clone the fork
bash scripts/rk_llama_cpp.sh build       # build for RKNPU2
bash scripts/rk_llama_cpp.sh verify      # check runtime, device, model
bash scripts/rk_llama_cpp.sh server      # run foreground
bash scripts/rk_llama_cpp.sh server-bg   # run background
bash scripts/rk_llama_cpp.sh stop        # stop background server
bash scripts/rk_llama_cpp.sh bench       # benchmark
```

The server runs with:
- Gemma 4 custom chat template (thinking disabled via `config/gemma4-no-think.jinja`)
- `--reasoning-budget -1` (fully disables thinking tokens)
- N-gram speculative decoding (`--spec-type ngram-simple --draft 8`)

Typical performance on RK3588: ~11.6 tokens/sec generation, ~62s for a full response.

## Configuration

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `ELFIN_PORT` | `8885` | HTTP server port |
| `ELFIN_INFERENCE_ENDPOINT` | `http://localhost:8081` | LLM server URL |
| `ELFIN_EMBED_ENDPOINT` | `http://localhost:8082` | Embedding server URL |
| `QDRANT_URL` | `http://localhost:6333` | Vector DB URL |
| `KIWIX_URL` | `http://localhost:8083` | Encyclopedia server URL |
| `ELFIN_SOURCE_DIR` | `./data/datasets/raw` | Source PDF directory |
| `DEMO_MODE` | `true` | Skip auth (creates ephemeral demo users) |
| `DATABASE_URL` | `file:./data/elfin.db` | SQLite path |

### LLM tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `CHAT_MODEL` | `gemma-4-E2B-it-IQ4_XS.gguf` | Chat model filename |
| `EMBED_MODEL` | `nomic-embed-text-v1.5.Q8_0.gguf` | Embedding model filename |
| `CHAT_CTX_SIZE` | `4096` | Chat context window (tokens) |
| `ELFIN_CHAT_MAX_TOKENS` | `384` | Max response tokens |
| `ELFIN_CHAT_REASONING_BUDGET` | `-1` | Thinking tokens (-1 = disabled) |
| `LLAMA_NGL` | `0` | GPU layers (0 = CPU only) |
| `LLAMA_THREADS` | `4` | CPU threads for LLM |
| `LLAMA_CPU_MASK` | `0xF0` | CPU pinning (A76 cores on RK3588) |

## Project structure

```
src/
  backend/
    server.ts              # HTTP entry, static serving, Kiwix proxy
    chatService.ts         # LLM orchestration, RAG retrieval, Kiwix search
    checkinService.ts      # Health check-in AI
    routes/                # API route handlers
    utils/                 # Pagination, Zod schemas
  frontend/
    pages/
      Chat.tsx             # Chat UI with SSE streaming, citations, source viewer
      Dashboard.tsx        # Service health, stats, quick actions
      Encyclopedia.tsx     # Embedded Kiwix iframe
      Notes.tsx            # Notepad
    components/            # Shell, PageHeader, Sidebar
  shared/
    types.ts               # Shared types, nav items
  ingestion/
    pipeline.py            # PDF chunking, embedding, Qdrant indexing
  training/                # Fine-tuning pipeline (LoRA SFT)
  cli/                     # Interactive chat and vision CLI tools
  infra/                   # Verification and smoke test scripts
prisma/
  schema.prisma            # User, JournalEntry, CheckIn, Note, Photo, ChatSession, ChatMessage
config/
  gemma4-no-think.jinja    # Chat template (disables Gemma 4 thinking)
  kiwix-zims.txt           # ZIM archives to download
  raw-docs.tsv             # Survival/medical PDFs to download
scripts/
  dev_remote.sh            # RK1 remote deploy with file watcher
  rk_llama_cpp.sh          # rk-llama.cpp build/run manager
  download_assets.sh       # Asset download orchestrator
data/                      # (gitignored) runtime data
  models/                  # GGUF files
  datasets/raw/            # Source PDFs
  datasets/zim/            # Kiwix ZIM archives
  qdrant/                  # Vector DB storage
  elfin.db                 # SQLite database
docker-compose.yml         # llama-server, llama-embed, Qdrant, Kiwix
Makefile                   # Build automation (run `make help` for all targets)
```

## Make targets

Run `make help` for the full list. Key targets:

| Target | Description |
|--------|-------------|
| `make setup` | Create venv, install Python + Bun deps |
| `make download-assets` | Download models, ZIMs, PDFs |
| `make dev` | Build + start all services + run server |
| `make dev-remote` | Deploy to RK1 with file watching |
| `make services` | Start Docker services only |
| `make build` | Build frontend (minified) |
| `make ingest` | Run ingestion pipeline |
| `make ingest-force` | Re-ingest all documents |
| `make ingest-remote` | Ingest on RK1 via SSH |
| `make typecheck` | TypeScript type-check |
| `make test` | Run test suite |
| `make db-push` | Push Prisma schema to SQLite |
| `make db-seed` | Seed admin user |
| `make chat` | Interactive CLI chat (terminal) |
| `make verify-gemma4` | Verify LLM server health |
| `make smoke-gemma4` | Chat smoke test |

## Fine-tuning pipeline

Elfin includes a LoRA SFT pipeline for fine-tuning the base Gemma 4 model on survival-domain data.

```bash
make download-assets              # includes base model snapshot
make setup-training               # install torch, transformers, peft, trl
make finetune-dataset             # build passage manifest from PDFs
make finetune-generate            # synthesize SFT dataset via OpenRouter
make finetune-validate            # validate dataset, emit train/val/test splits
make finetune-train               # run LoRA SFT
make finetune-export              # merge adapter, export GGUF
make finetune-eval                # compare baseline vs tuned, gate promotion
```

## Tech stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, React Router 7 |
| Backend | Bun (TypeScript) |
| Database | SQLite via Prisma ORM |
| LLM | Gemma 4 E2B IQ4_XS (~2.8 GB) via llama.cpp |
| Embeddings | nomic-embed-text v1.5 Q8_0 via llama.cpp |
| Vector DB | Qdrant (on-disk, ~100 MB RAM) |
| Encyclopedias | Kiwix (ZIM archives) |
| Validation | Zod 4, TypeScript strict mode |
| NPU inference | rk-llama.cpp (RKNPU2 backend) |
| Theme | Pip-Boy / Fallout terminal aesthetic |

## License

Proprietary. Cloud Exit B.V. 2026.
