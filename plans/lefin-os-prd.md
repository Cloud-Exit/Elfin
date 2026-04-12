# LefinOS — Product Requirements Document

**Project:** LefinOS (Air-Gapped Survival Intelligence Companion)
**Target Hardware:** Single RK3588 RK1 (16 GB RAM, 4 TB NVMe), 10.6" 1280x800 touchscreen
**Power:** 20,000 mAh battery (~74 Wh) + solar charger
**Version:** 6.0 — reviewed
**Date:** 2026-04-11
**Status:** APPROVED

---

## 1. Executive Summary

LefinOS is a doomsday-grade, offline-only survival companion. It is seeded once via SSH and never updated. It runs on a single RK1 with cold spare modules for redundancy.

It is not just an AI chatbot — it is a **complete offline digital life raft** with health tracking, journaling, entertainment, encyclopedias, and multimodal AI analysis. The AI actively monitors each user's wellbeing through daily check-ins and builds a longitudinal health profile.

**Core capabilities:**

1. **AI-powered health journal** — baseline interview, daily check-ins, AI-generated questions, health stat tracking (mental, physical, stamina), per-user profiles
2. **RAG-powered Q&A** — survival/medical manuals with mandatory source verification
3. **Multimodal analysis** — camera/photo analysis (e.g. "is this berry edible") with verified-only results cross-referenced against encyclopedia sources
4. **Offline encyclopedias** — Wikipedia EN/ES, WikiMed, StackExchange via Kiwix
5. **Entertainment** — movies, music, books, retro gaming (MSX2 + SNES)
6. **Tools** — notepad, calculator, photo gallery
7. **Multi-user** — profiles, offline auth, per-user data isolation
8. **Bilingual** — English and Spanish

---

## 2. Hardware & Power

| Resource | Spec |
|----------|------|
| SoC | RK3588 (4x A76 + 4x A55) |
| RAM | 16 GB LPDDR4x |
| Storage | 4 TB NVMe |
| Display | 10.6" 1280x800 touchscreen + camera |
| Power | 20,000 mAh (~74 Wh) + solar |
| Network | None (air-gapped) |

Single active node, cold spares with cloned NVMes. Manual failover. Seeded once, never updated.

---

## 3. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Desktop shell** | Electrobun | Bun-native, lighter than Electron, single runtime |
| **Frontend** | React 19 + React Router | Mature ecosystem, assistant-ui integration |
| **AI Chat UI** | assistant-ui | Production-grade streaming chat, tool calls, message history |
| **Backend** | Bun (TypeScript) | Same runtime as Electrobun, simple to debug and fix |
| **Database** | Prisma + SQLite | Type-safe ORM, zero-server DB, survives power loss |
| **Inference** | llama.cpp (llama-server) | Direct GGUF loading, OpenAI-compatible API, multimodal |
| **Embeddings** | llama.cpp (llama-embed) | Separate instance for nomic-embed-text |
| **Vector DB** | Qdrant (on-disk storage) | ~100 MB RAM, vectors on NVMe |
| **Encyclopedias** | Kiwix-serve | ZIM file serving |
| **Theme** | Pip-Boy / Fallout terminal | CRT scanlines, amber glow, monospace |

**Key principle:** TypeScript everywhere. One language. In an emergency, anyone who can read TypeScript can debug and fix the entire system.

---

## 4. Application Modules

### 4.1 AI Chat (assistant-ui)

Full-featured AI chat using assistant-ui integrated into the app:
- Streaming responses from llama-server via OpenAI-compatible API
- RAG pipeline: embed query → Qdrant → build prompt with source chunks → stream response
- Per-user conversation history stored in SQLite
- **Reference mode**: answers only from verified sources, shows citations
- **General mode**: base model knowledge with warning banner
- Multimodal: user can attach photos for analysis

**Verified-only trust model for images:**
- AI analyzes the image (Gemma 4 E4B vision mode)
- AI searches the vector DB and Kiwix for matching entries
- If a verified match is found: display result + direct link to Kiwix article
- If no match: "I cannot verify this identification against my reference materials"
- Never present unverified visual identification as fact

### 4.2 Journal + Health Tracking

The core differentiator. Each user has a health journal with AI-driven analysis.

**Baseline interview (first use):**
- AI asks comprehensive questions: pre-existing conditions, medications, allergies, fitness level, mental health history, vision, chronic pain, dietary needs
- Responses stored as the user's health baseline
- All future assessments are relative to this baseline

**Daily check-in:**
- App prompts user for check-in (skippable)
- AI generates questions based on:
  - Previous journal entries and trends
  - Historical check-in data
  - The user's specific baseline (e.g. if user has known vision issues, don't flag stable symptoms)
  - Recent events from journal (e.g. "Yesterday you mentioned a fall — how is your mobility today?")
- User responds to questions
- AI categorizes, summarizes, and scores the check-in

**Health stats (1-10 scale, relative to baseline):**
- Mental health (mood, focus, stress, sleep quality)
- Physical health (pain, mobility, illness symptoms, injuries)
- Stamina (energy level, physical capacity, endurance)
- Additional categories as detected by AI (e.g. nutrition, hydration)

**Scoring rules:**
- 1-10 scale where 5 = normal baseline for that user
- Scores computed relative to personal baseline
- Sharp symptoms = major demerits (e.g. double vision in a user with normal baseline vision)
- Same symptom in a user with pre-existing vision issues = weighted differently
- Rolling average with recent entries weighted more heavily
- Sharp declines trigger prominent warnings

**Dashboard:**
- Per-user status display showing current scores
- Trend graphs over time
- AI-generated summary of current status
- All scores labeled "AI-estimated"
- Raw journal data always accessible

### 4.3 Notepad

Simple per-user notes:
- Create, edit, delete notes
- Title + rich-text content
- Full-text search
- AI has read access to notes for context in chat

### 4.4 Calculator

Built-in calculator. Basic arithmetic + scientific functions. No external dependencies.

### 4.5 Encyclopedia (Kiwix)

- Kiwix-serve proxied through the backend
- Wikipedia EN/ES, WikiMed, StackExchange
- Full-text search
- Language toggle (EN/ES)
- Used as verification source for AI visual identification

### 4.6 Entertainment

**Movies:** Flat directory listing, Player.js playback (480p MP4)
**Music:** Flat directory listing, Player.js playback
**Books:** Flat directory listing, EPUB rendering (epub.js), PDF rendering
**Games:** Nostalgist with fMSX (MSX2) + snes9x (SNES) cores

### 4.7 Photo Gallery

- Camera capture (device camera)
- Sideloaded photos from filesystem
- Per-user galleries stored in SQLite metadata + filesystem
- AI can access all user photos for analysis
- Photos can be sent to AI chat for identification/analysis

---

## 5. User Management

- Offline-only authentication, no external auth providers
- Default account: `admin` / `admin` (password change required on first login)
- Admin can create additional users
- Passwords stored as bcrypt hashes in SQLite
- Session management via secure tokens
- Per-user data isolation: journal, notes, photos, chat history, health stats

---

## 6. Data Model (Prisma + SQLite)

```prisma
model User {
  id           String   @id @default(cuid())
  username     String   @unique
  passwordHash String
  role         String   @default("user") // "admin" | "user"
  createdAt    DateTime @default(now())
  baseline     Json?    // Health baseline interview data

  journalEntries JournalEntry[]
  checkIns       CheckIn[]
  notes          Note[]
  photos         Photo[]
  chatMessages   ChatMessage[]
}

model JournalEntry {
  id           String   @id @default(cuid())
  userId       String
  user         User     @relation(fields: [userId], references: [id])
  content      String   // User's journal text
  date         DateTime @default(now())
  aiSummary    String?  // AI-generated summary
  aiCategories Json?    // AI categorization
  createdAt    DateTime @default(now())
}

model CheckIn {
  id            String   @id @default(cuid())
  userId        String
  user          User     @relation(fields: [userId], references: [id])
  date          DateTime @default(now())
  questions     Json     // AI-generated questions
  responses     Json     // User responses
  aiSummary     String?  // AI analysis
  mentalScore   Float?   // 1-10
  physicalScore Float?   // 1-10
  staminaScore  Float?   // 1-10
  categories    Json?    // Additional AI-detected categories
  createdAt     DateTime @default(now())
}

model Note {
  id        String   @id @default(cuid())
  userId    String
  user      User     @relation(fields: [userId], references: [id])
  title     String
  content   String
  updatedAt DateTime @updatedAt
  createdAt DateTime @default(now())
}

model Photo {
  id        String   @id @default(cuid())
  userId    String
  user      User     @relation(fields: [userId], references: [id])
  filename  String
  path      String
  caption   String?
  takenAt   DateTime?
  createdAt DateTime @default(now())
}

model ChatMessage {
  id        String   @id @default(cuid())
  userId    String
  user      User     @relation(fields: [userId], references: [id])
  role      String   // "user" | "assistant"
  content   String
  sources   Json?    // RAG sources
  images    Json?    // Attached image paths
  createdAt DateTime @default(now())
}
```

---

## 7. AI Context Pipeline

When the AI responds in chat, it has access to (per authenticated user):
1. The user's health baseline
2. Recent journal entries (last 30 days)
3. Latest check-in scores and trends
4. User's notes
5. RAG sources from Qdrant (survival/medical manuals)
6. Kiwix encyclopedia (for verification)
7. Attached photos (multimodal analysis)

The system prompt is dynamically built per request with relevant user context from SQLite.

---

## 8. Inference Configuration

### 8.1 Chat Model — Gemma 4 E4B

| Property | Value |
|----------|-------|
| Model | `unsloth/gemma-4-E4B-it-GGUF` (configurable) |
| Quantization | Q4_K_M (~2.5 GB) |
| Inference | llama-server, CPU-only, OpenAI-compatible API |
| Multimodal | Vision enabled via `--mmproj` flag |

### 8.2 Embedding Model — nomic-embed-text

| Property | Value |
|----------|-------|
| Model | nomic-embed-text GGUF |
| Inference | llama-server with `--embedding` flag |

### 8.3 Vision (Image Analysis)

llama-server supports Gemma 4 vision with appropriate mmproj file. Image queries sent as base64 in the OpenAI-compatible messages API.

---

## 9. Directory Structure

```
/lefin-os/
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
│   ├── zim/                   # Kiwix ZIM files
│   └── osm/                   # OpenStreetMap
├── docker-compose.yml         # llama-server, qdrant, kiwix
├── package.json
├── tsconfig.json
├── .env
└── plans/
```

---

## 10. Revised Implementation Slices

| # | Slice | Blocked By |
|---|-------|-----------|
| 1 | Electrobun + React 19 + Router shell + Pip-Boy theme | None |
| 2 | Bun backend + Prisma + SQLite + auth (users, login, sessions) | 1 |
| 3 | AI Chat with assistant-ui + RAG (Qdrant + llama-server) | 2 |
| 4 | Journal CRUD + daily entries + search | 2 |
| 5 | Baseline health interview (AI-driven onboarding per user) | 3, 4 |
| 6 | Daily check-in flow (AI questions, scoring, categorization) | 5 |
| 7 | Health dashboard (stats, trends, warnings) | 6 |
| 8 | Multimodal image analysis + verified-only trust model | 3 |
| 9 | Notepad (CRUD, search, AI context access) | 2 |
| 10 | Encyclopedia (Kiwix proxy + search) | 1 |
| 11 | Entertainment (movies, music, books) | 1 |
| 12 | Games (Nostalgist, MSX2 + SNES) | 1 |
| 13 | Photo gallery (camera, sideload, AI access) | 2, 8 |
| 14 | Calculator | 1 |
| 15 | Bilingual EN/ES | All above |
