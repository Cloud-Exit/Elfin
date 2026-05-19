# Elfin OS: Your Offline Survival AI

Built for the [Gemma 4 Good Hackathon](https://www.kaggle.com/competitions/gemma-4-good-hackathon).

**Live demo: [elfin.sh](https://elfin.sh)**

Elfin OS is an offline survival AI system built specifically for scenarios where normal infrastructure has failed. When there is no internet, no cell signal, no cloud APIs, and limited access to emergency services, Elfin provides critical, life-saving guidance.

No cloud fallback. No hidden GPU. No fake local mode. The elfin.sh demo runs on the same low-power edge hardware shown in the demo (Turing RK1).

## Core Technology: Purpose-Built for the Edge

In a true emergency, a dropped signal shouldn't mean losing your lifeline. When remote servers go offline, Elfin stays awake. It is designed to weather the disconnect, anchoring resilient, off-grid intelligence directly in your hands when survival is on the line.

### Powered by Gemma 4 E2B

We selected this model for its perfect balance of size and capability. It is compact enough to run locally on highly power-efficient edge hardware, yet capable enough to translate complex medical and survival data into clear, actionable steps.

### True Local Hardware

Elfin runs on low-power single-board computers like the Turing RK1 and Rockchip RK3588. It can be powered entirely by battery or solar setups, making it ideal for field kits, off-grid homes, vehicles, boats, or cabins.

### Transparent Live Demo

The live demo at elfin.sh runs on this exact edge hardware, not a hidden cloud server pretending to be local. It proves that reliable, high-utility AI can thrive entirely off the grid.

## Grounded, Verifiable Knowledge

In a crisis, having the right information can be the difference between stabilizing a situation and making it worse. Elfin puts actionable knowledge directly into your hands.

**Practical Guidance**: Quickly get step-by-step instructions on how to clean a wound, purify drinking water, preserve food, or recognize critical medical danger signs.

**Offline Retrieval**: Elfin doesn't rely solely on the AI's internal memory. It uses a local vector database to search offline documents and Kiwix encyclopedias, including Wikipedia and WikiMed.

**Built on Trust**: Elfin retrieves the source material and provides clear citations with every answer, allowing the user to inspect exactly where the information came from.

## The Mission

The goal is simple: make AI genuinely useful when the internet goes dark. Elfin guarantees fast assistance, verifiable local sources, and complete user data privacy with absolutely zero cloud dependency. In a real emergency, that immediate access to trusted information can save lives.

## Technical Implementation

Elfin OS runs entirely on a Turing RK1 compute module powered by a Rockchip RK3588 SoC. The device has an 8-core ARM CPU, 16 GB LPDDR4X memory, NVMe storage, and a 10-inch HDMI touchscreen. Although the RK3588 includes a 6 TOPS RKNPU2 accelerator, Elfin currently runs CPU-only because Gemma 4 architecture support is not yet available for the NPU.

The local inference stack uses llama.cpp via the rk-llama.cpp fork. The deployed model is Google Gemma 4 E2B-it quantized with IQ4_XS, resulting in a 2.8 GB model file. Embeddings are generated locally using nomic-embed-text v1.5 quantized to Q8_0, with a 140 MB embedding model.

Retrieval is handled by Qdrant in on-disk mode, with 768-dimensional embeddings generated from locally ingested PDF and Markdown documents. Elfin also integrates Kiwix for offline Wikipedia ZIM article retrieval. Retrieved sources are cited inline in responses so users can inspect where guidance came from.

The backend is built with Bun, TypeScript, SQLite, and Prisma. The frontend is a React single-page application with a Pip-Boy-inspired terminal interface designed for use on the attached 10-inch touchscreen.

Measured performance on the RK1 device is approximately 19 tokens/second for prompt processing and 7 tokens/second for generation, using a 4096-token context window, 4 big-core CPU threads, and a single inference slot. All inference, embedding, search, and storage run on-device. Network access is optional and used only for remote management.

### Multimodal Image Support

The latest version of Elfin also supports image input. Users can attach photos from the field, such as wounds, plants, equipment, labels, maps, supplies, or damaged infrastructure, and Elfin can reason over the image together with its offline retrieval system. This is especially useful in emergency environments where users may not know the correct terminology for what they are seeing. Image support runs as part of the same local-first Elfin workflow and is designed to complement, not replace, cited survival and medical references.

Note: the submitted video focuses on the core offline edge/RAG workflow. The current Elfin build also includes image input support, shown in the screenshots.

## Architecture

```
Browser (React 19)
  |
Bun HTTP server (port 8885)
  |--- Prisma ORM ---> SQLite (elfin.db)
  |--- SSE streaming ---> llama-server (port 8081) -- Gemma 4 E2B IQ4_XS
  |--- embeddings ------> llama-embed  (port 8082) -- nomic-embed-text v1.5
  |--- vector search ----> Qdrant      (port 6333) -- on-disk vectors
  |--- encyclopedia -----> Kiwix       (port 8083) -- ZIM archives
```

On RK3588 hardware, the chat LLM runs natively via [rk-llama.cpp](https://github.com/invisiofficial/rk-llama.cpp). On x86, it runs in Docker.

## Hardware

| Component | Spec |
|-----------|------|
| SoC | Rockchip RK3588 (Turing RK1) |
| CPU | 4x Cortex-A76 @ 2.4 GHz + 4x Cortex-A55 @ 1.8 GHz |
| RAM | 16 GB LPDDR4X |
| Storage | NVMe SSD |
| Display | 10-inch HDMI touchscreen |
| NPU | 6 TOPS RKNPU2 (not used, Gemma 4 not yet supported) |

Also runs on any x86 machine with Docker for development (no NPU acceleration).

## Quick Start

### 1. Clone and install dependencies

```bash
git clone <repo-url> elfin && cd elfin
make setup
```

### 2. Download all assets

```bash
make download-assets
```

**Models** (from Hugging Face):

| File | Size | Source |
|------|------|--------|
| `gemma-4-E2B-it-IQ4_XS.gguf` | ~2.8 GB | `unsloth/gemma-4-E2B-it-GGUF` |
| `mmproj-F16.gguf` | ~500 MB | `unsloth/gemma-4-E2B-it-GGUF` |
| `nomic-embed-text-v1.5.Q8_0.gguf` | ~140 MB | `nomic-ai/nomic-embed-text-v1.5-GGUF` |

**Encyclopedias** (from Kiwix):

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

### 3. Initialize the database

```bash
make db-push
```

### 4. Ingest documents

```bash
make services          # start llama-embed, Qdrant, Kiwix
make ingest            # chunk PDFs, embed, index into Qdrant
```

### 5. Run

```bash
make dev
```

Open `http://localhost:8885`.

## Deploying to RK1

```bash
export ELFIN_REMOTE_HOST=rk1.local
export ELFIN_REMOTE_HOST_USER=ubuntu
make install-remote    # first-time install (systemd, deps, .env)
make dev               # dev mode with file watching
```

See `docs/rk1-edge-deployment.md` for kernel, Docker, and Bun setup on the RK1.

### Remote ingestion

```bash
make ingest-remote          # incremental
make ingest-remote-force    # re-embed everything
```

## Configuration

### Application

| Variable | Default | Description |
|----------|---------|-------------|
| `ELFIN_PORT` | `8885` | HTTP server port |
| `ELFIN_INFERENCE_ENDPOINT` | `http://localhost:8081` | LLM server URL |
| `ELFIN_EMBED_ENDPOINT` | `http://localhost:8082` | Embedding server URL |
| `QDRANT_URL` | `http://localhost:6333` | Vector DB URL |
| `KIWIX_URL` | `http://localhost:8083` | Encyclopedia server URL |
| `KIWIX_PUBLIC_URL` | (none) | Public Kiwix URL for iframe (e.g. `https://kiwix.elfin.sh`) |
| `ELFIN_SOURCE_DIR` | `./data/datasets/raw` | Source PDF directory |
| `DEMO_MODE` | `true` | Enable demo mode (ephemeral users, 24h sessions) |
| `DATABASE_URL` | `file:./data/elfin.db` | SQLite path |

### LLM

| Variable | Default | Description |
|----------|---------|-------------|
| `CHAT_MODEL` | `gemma-4-E2B-it-IQ4_XS.gguf` | Chat model filename |
| `EMBED_MODEL` | `nomic-embed-text-v1.5.Q8_0.gguf` | Embedding model filename |
| `CHAT_CTX_SIZE` | `4096` | Context window (tokens) |
| `LLAMA_NGL` | `0` | GPU layers (0 = CPU only) |
| `LLAMA_THREADS` | `6` | CPU threads for inference |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, React Router 7 |
| Backend | Bun (TypeScript) |
| Database | SQLite via Prisma ORM |
| LLM | Gemma 4 E2B IQ4_XS (~2.8 GB) via llama.cpp |
| Embeddings | nomic-embed-text v1.5 Q8_0 via llama.cpp |
| Vector DB | Qdrant (on-disk mode) |
| Encyclopedias | Kiwix (ZIM archives) |
| NPU inference | rk-llama.cpp (RKNPU2 backend) |
| Theme | Pip-Boy / Fallout terminal aesthetic |

## License

MIT
