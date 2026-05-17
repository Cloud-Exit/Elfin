# Elfin — Architecture Decisions

*May it be a light to you in dark places, when all other lights go out.*

**Full PRD:** [GitHub Issue #11](https://github.com/Cloud-Exit/Elfin/issues/11)

## Design Philosophy

**Lean. Offline. Indestructible.**

Elfin is a doomsday-grade, offline-only survival companion. Seeded once via SSH, never updated. Runs on a single RK3588 RK1 with cold spares for redundancy. It is not just an AI chatbot — it is a **complete offline digital life raft** with health tracking, journaling, entertainment, encyclopedias, and multimodal AI analysis.

**Core capabilities:**

1. **AI-powered health journal** — baseline interview, daily check-ins, AI-generated questions, health stat tracking (mental, physical, stamina), per-user profiles
2. **RAG-powered Q&A** — survival/medical manuals with mandatory source verification
3. **Multimodal analysis** — camera/photo analysis with verified-only results cross-referenced against encyclopedia sources
4. **Offline encyclopedias** — Wikipedia EN/ES, WikiMed, StackExchange via Kiwix
5. **Entertainment** — movies, music, books, retro gaming (MSX2 + SNES)
6. **Tools** — notepad, calculator, photo gallery
7. **Multi-user** — profiles, offline auth, per-user data isolation
8. **Bilingual** — English and Spanish

## Hardware & Power

| Resource | Spec |
|----------|------|
| SoC | RK3588 (4x A76 + 4x A55) |
| RAM | 16 GB LPDDR4x |
| Storage | 4 TB NVMe |
| Display | 10.6" 1280x800 touchscreen + camera |
| Power | 20,000 mAh (~74 Wh) + solar charger |
| Network | None (air-gapped) |

Single active node, cold spares with cloned NVMes. Manual failover. Seeded once, never updated. Runtime artifacts pinned to immutable digests/hashes.

## Stack

### Application Layer (TypeScript)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Desktop shell** | Electrobun | Bun-native, single runtime, lighter than Electron |
| **Frontend** | React 19 + React Router | Mature, assistant-ui integration, large ecosystem |
| **AI Chat UI** | assistant-ui | Streaming chat, tool calls, message history |
| **App Backend** | Bun (TypeScript) | HTTP server, auth, API routes, media serving |
| **Database** | Prisma + SQLite | Type-safe ORM, zero-server DB, survives power loss |
| **Theme** | Pip-Boy / Fallout terminal | CRT scanlines, amber glow, monospace |

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

The RK1 runtime currently uses the CPU llama.cpp GGUF path. `LLAMA_NGL` and the Vulkan image are GPU-layer controls, not RK3588 NPU support. Real NPU acceleration must be implemented as a separate RKLLM/RKNN backend with converted model artifacts and an OpenAI-compatible adapter.

### Qdrant over ChromaDB

ChromaDB stores vectors in RAM. On a 16 GB device running an 8 GB LLM, that's fatal. Qdrant with `on_disk: true` keeps everything on NVMe, using ~100 MB RAM.

### Verified-only trust model

The AI can analyze images (Gemma 4 vision), but ONLY presents results it can cross-reference against the vector DB or Kiwix encyclopedia. Unverified visual identification is never presented as fact. Verified results include a direct link to the Kiwix source article.

### AI health tracking with personal baseline

Each user gets a baseline health interview on first use. All future health assessments are relative to that baseline — a user with known vision issues isn't flagged for stable symptoms. Scores are 1-10, computed from rolling check-in data, always labeled "AI-estimated."

### 16 GB RAM budget

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

## AI Context Pipeline

When the AI responds in chat, it has access to (per authenticated user):

1. The user's health baseline
2. Recent journal entries (last 30 days)
3. Latest check-in scores and trends
4. User's notes
5. RAG sources from Qdrant (survival/medical manuals)
6. Kiwix encyclopedia (for verification)
7. Attached photos (multimodal analysis)

The system prompt is dynamically built per request with relevant user context from SQLite.

## Where to Find Work

PRDs and implementation slices are tracked as **GitHub issues** in this repository ([Cloud-Exit/Elfin](https://github.com/Cloud-Exit/Elfin)). Each slice is a self-contained, vertically-sliced piece of functionality with its own PRD, acceptance criteria, and tests.

- **Main PRD**: [Issue #11](https://github.com/Cloud-Exit/Elfin/issues/11)
- **Next slice**: Check the issue tracker for the highest-priority open slice.
- **Slice dependencies**: Each issue lists prerequisite slices. Only work on a slice when its dependencies are merged.
- **PRD location**: The PRD for each slice is linked from its GitHub issue.

## Implementation Plan (28 slices, AI pipeline first, app last)

### Phase 1 — AI Foundation (Slices 1-7)

Gate: do not advance to Phase 2 until Slices 1-7 are validated end-to-end on target-style hardware. "Validated" means real assets on disk, live inference/embedding/vector flows working, and queryable RAG behavior proven outside dry-run mode.

| # | Slice | What to validate |
|---|-------|-----------------|
| 1 | Docker Compose: llama-server + llama-embed + Qdrant + Kiwix (pinned digests) | All services start, health endpoints respond |
| 2 | Dataset procurement — download survival PDFs, WikiMed ZIM | Files on disk, readable |
| 3 | Ingestion pipeline — chunks PDFs → embeds via llama-embed → stores in Qdrant | Vectors in Qdrant, queryable |
| 4 | RAG orchestration (TypeScript, CLI) — embed query → Qdrant search → build prompt → llama-server → streamed answer with citations | Correct answers with source citations from terminal |
| 5 | Multimodal vision test — send image to llama-server with mmproj, get analysis | Image description returned correctly |
| 6 | Local Elfin fine-tuning pipeline — host-side SFT of Gemma-class model from local corpus + OpenRouter-generated data, eval-gated promotion (#27) | Candidate tuned model produced locally and promoted only if it passes the survival eval suite |
| 7 | Verified trust model — cross-reference AI visual ID against Qdrant + Kiwix | Only verified results flagged as verified |

### Phase 2 — Data Layer (Slices 8-10)

| # | Slice | What to validate |
|---|-------|-----------------|
| 8 | Prisma + SQLite schema — all models, migrations, seed admin user | `bunx prisma db push` works, admin user created |
| 9 | Auth system — login, sessions, bcrypt, admin forced password change | Login/logout works from curl |
| 10 | Journal + check-in data layer — CRUD endpoints, no AI yet | Entries stored and retrieved |

### Phase 3 — AI + Data Integration (Slices 11-14)

| # | Slice | What to validate |
|---|-------|-----------------|
| 11 | AI baseline interview — scripted multi-step health intake via API | Baseline stored in User.baseline JSON |
| 12 | AI daily check-in — generates questions from baseline + journal, scores responses | Check-in stored with scores |
| 13 | AI chat with per-user context — system prompt includes baseline, journal, notes | AI answers reference user's personal context |
| 14 | Health stat computation — rolling scores, trend detection, decline warnings | Scores computed correctly from check-in history |

### Phase 4 — Application (Slices 15-22)

| # | Slice | What to validate |
|---|-------|-----------------|
| 15 | Electrobun + React 19 + Router shell + Pip-Boy theme | App launches, all routes navigate, theme renders |
| 16 | Login page + auth integration | Login/logout works in app |
| 17 | AI Chat page (assistant-ui) | Streaming chat with RAG sources in app |
| 18 | Dashboard + health stats | Stat bars, trends, check-in prompt in app |
| 19 | Journal page | CRUD, search, AI summaries in app |
| 20 | Notepad, Calculator, Settings | All three functional in app |
| 21 | Encyclopedia (Kiwix), Entertainment, Games, Gallery | All media/reference tabs working |
| 22 | Bilingual EN/ES | Full i18n |

### Phase 4B — Supplemental PRD: Auto-Translate Voice Journal (#29) (Slices 23-28)

Dependency-bound to main roadmap. Do not start before journal data layer, journal page, and settings land.

| # | Slice | What to validate |
|---|-------|-----------------|
| 23 | Voice journal data model + processing records | Voice journal jobs persist with explicit status, transcript/translation metadata, per-user isolation |
| 24 | Imported audio upload + pending voice job | User can attach audio, validation works, pending voice job created |
| 25 | Offline speech-to-text for voice journal | Imported audio transcribes offline into stored original transcript |
| 26 | Offline translation + final journal write | Transcribed voice note translates offline and saves as journal entry with original + translated text |
| 27 | Imported-audio voice journal UI | Journal UI supports upload, processing states, transcript review, confirm-save flow |
| 28 | Live microphone capture + voice journal defaults | User can record from microphone, process through same pipeline, use per-user language/retention defaults |

## Data Model

Full Prisma schema in the PRD ([Issue #11](https://github.com/Cloud-Exit/Elfin/issues/11)). Models: `User`, `JournalEntry`, `CheckIn`, `Note`, `Photo`, `ChatMessage`. All per-user via `userId` foreign key.

## File Structure

```
/elfin/
├── src/
│   ├── main/                  # Electrobun main process
│   │   ├── index.ts           # App entry, spawns backend
│   │   └── preload.ts         # IPC bridge
│   ├── backend/               # Bun HTTP server
│   │   ├── server.ts          # HTTP routes
│   │   ├── auth.ts            # Login, sessions, bcrypt
│   │   ├── rag.ts             # RAG orchestration
│   │   ├── journal.ts         # Journal + check-in logic
│   │   ├── health.ts          # Health stat computation
│   │   ├── media.ts           # Media directory listing
│   │   └── kiwix.ts           # Kiwix proxy
│   ├── frontend/              # React 19 app
│   │   ├── main.tsx           # React entry
│   │   ├── router.tsx         # React Router config
│   │   ├── components/        # Shared UI components
│   │   ├── pages/             # Route pages
│   │   │   ├── Login.tsx
│   │   │   ├── Dashboard.tsx  # Health overview + check-in
│   │   │   ├── Chat.tsx       # assistant-ui integration
│   │   │   ├── Journal.tsx
│   │   │   ├── Notes.tsx
│   │   │   ├── Encyclopedia.tsx
│   │   │   ├── Entertainment.tsx
│   │   │   ├── Gallery.tsx
│   │   │   ├── Calculator.tsx
│   │   │   └── Settings.tsx   # User profile, password
│   │   └── theme/             # Pip-Boy CSS
│   └── shared/                # Shared types
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
├── docker-compose.yml         # llama-server, qdrant, kiwix
├── package.json
├── tsconfig.json
├── .env
└── plans/
```
