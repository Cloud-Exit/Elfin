# RK1 / Rockchip Edge Deployment

Deploy Elfin on an RK3588-based board (RK1, Rock 5B, Orange Pi 5, etc.) with NPU-accelerated inference via rk-llama.cpp.

## Hardware requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| SoC | RK3588 / RK3588S | RK3588 (full NPU) |
| RAM | 8 GB | 16 GB LPDDR4x |
| Storage | 32 GB (model + ZIMs) | 4 TB NVMe |
| Kernel | 5.10.x rockchip vendor BSP | 5.10.160-rockchip |
| OS | Ubuntu 22.04 / Armbian (vendor kernel) | Ubuntu 22.04 LTS |

Mainline Linux kernels (6.x) lack the rknpu driver. You must use the vendor/BSP kernel.

## Prerequisites on the RK1

### 1. Kernel and NPU device

Verify you have the vendor kernel with built-in rknpu driver:

```bash
uname -r
# Expected: 5.10.x-rockchip

dmesg | grep -i rknpu
# Expected: RKNPU fdab0000.npu: ... Initialized rknpu 0.9.x
```

The NPU is exposed as a DRM device at `/dev/dri/renderD129` (not `/dev/rknpu`).
Your user must be in the `render` group to access it:

```bash
sudo usermod -aG render $USER
# Log out and back in, or use: sg render -c "command"
```

Verify access:

```bash
groups | grep render
ls -la /dev/dri/renderD129
# Should show crw-rw----+ root render
```

### 2. Build toolchain

rk-llama.cpp compiles from source on the RK1. Install build dependencies:

```bash
sudo apt-get update
sudo apt-get install -y git cmake make g++
```

### 3. Docker and Docker Compose

Elfin uses Docker for embed, vector DB, and encyclopedia services:

```bash
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# Log out and back in
```

### 4. Bun runtime

```bash
curl -fsSL https://bun.com/install | bash
# Add to PATH: export BUN_INSTALL="$HOME/.bun"; export PATH="$BUN_INSTALL/bin:$PATH"
```

## Remote deployment from dev machine

The standard workflow syncs code from your dev machine to the RK1 via SSH with live file watching.

### Environment variables

| Variable | Required | Example |
|----------|----------|---------|
| `ELFIN_REMOTE_HOST` | yes | `rk1.local` or `10.10.10.165` |
| `ELFIN_REMOTE_HOST_USER` | yes | `stephen` |
| `ELFIN_REMOTE_PATH` | no | `/home/stephen/elfin` (default) |
| `TARGET` | no | `rockchip` (default for dev-remote) |
| `DEMO_MODE` | no | `true` (default, skips auth) |

### Deploy

```bash
# From your dev machine (requires SSH key auth to the RK1)
ELFIN_REMOTE_HOST=10.10.10.165 ELFIN_REMOTE_HOST_USER=stephen make dev-remote
```

This will:

1. Validate local runtime assets (models, ZIMs)
2. rsync project files to the RK1
3. Sync model and ZIM assets
4. Push `.env` configuration
5. Install bun dependencies on remote
6. Build frontend
7. Start Docker services (llama-embed, Qdrant, Kiwix)
8. Add user to `render` group if needed
9. Clone, build, and start rk-llama.cpp with RKNPU2 support
10. Wait for all services to be healthy
11. Run Prisma DB migrations
12. Start the Bun application server
13. Watch local files for changes and auto-redeploy

### What runs where

| Service | Runtime | Port |
|---------|---------|------|
| llama-server (chat) | rk-llama.cpp native (RKNPU2) | 8081 |
| llama-embed | Docker (llama.cpp CPU) | 8082 |
| Qdrant | Docker | 6333 |
| Kiwix | Docker | 8083 |
| Elfin app | Bun (native) | 8885 |

When `TARGET=rockchip`, the Docker llama-server container is removed (not just stopped) to prevent the `restart: unless-stopped` policy from reviving it.

## Runtime assets

Before deploying, download models and datasets on your dev machine:

```bash
make download-assets
```

Required files in `data/models/`:
- `gemma-4-E4B-it-Q5_K_M.gguf` (or any `gemma-4-E4B-it-*.gguf`)
- `nomic-embed-text-v1.5.Q8_0.gguf`

Required files in `data/datasets/zim/`:
- At least one `.zim` file (Wikipedia, WikiMed, etc.)

These are rsynced to the RK1 during bootstrap. The `data/` directory is excluded from code syncs but included via a separate asset sync step.

## rk-llama.cpp management

The `scripts/rk_llama_cpp.sh` script manages the RKNPU2-accelerated llama.cpp fork:

```bash
# On the RK1 (or via remote_sh from dev-remote)
bash scripts/rk_llama_cpp.sh verify    # Check NPU runtime, device, build, model
bash scripts/rk_llama_cpp.sh build     # Force rebuild from source
bash scripts/rk_llama_cpp.sh server    # Run in foreground (for debugging)
bash scripts/rk_llama_cpp.sh server-bg # Run in background (normal operation)
bash scripts/rk_llama_cpp.sh stop      # Stop background server
bash scripts/rk_llama_cpp.sh bench     # Run benchmark
bash scripts/rk_llama_cpp.sh paths     # Print resolved config
```

The binary is built once and cached at `data/toolchains/rk-llama.cpp/build/bin/llama-server`. Subsequent `server-bg` calls skip the build entirely. Force a rebuild with `bash scripts/rk_llama_cpp.sh build`.

## Verifying NPU offload

After starting the server, check the log for RKNPU buffers:

```bash
tail -100 data/logs/rk-llama-server.log | grep -E 'RKNPU|graph splits|buffer size'
```

Working NPU offload shows:

```
load_tensors:        RKNPU model buffer size =   447.50 MiB
sched_reserve:      RKNPU compute buffer size =    25.00 MiB
sched_reserve: graph splits = 65
```

CPU-only fallback shows:

```
alloc_compute_meta:        CPU compute buffer size =    94.52 MiB
alloc_compute_meta: graph splits = 1
```

### Common NPU issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `graph splits = 1`, no RKNPU buffer | User not in `render` group | `sudo usermod -aG render $USER`, re-login |
| `librknnrt.so not found` | RKNN runtime missing | Bundled in rk-llama.cpp source tree; rebuild |
| `/dev/rknpu not found` | Normal on newer kernels | NPU uses DRM at `/dev/dri/renderD129` instead |
| `can't request region for resource` | Normal dmesg warning | Harmless, does not prevent NPU operation |
| `failed to find power_model node` | Normal dmesg warning | Harmless, thermal management still works |
| Binary not linked to RKNN | cmake didn't find RKNN SDK | Run `bash scripts/rk_llama_cpp.sh build` and check cmake output |

## Performance tuning

### CPU thread pinning

The RK3588 has big.LITTLE cores (4x A76 at cores 4-7, 4x A55 at cores 0-3). Pin llama threads to the fast A76 cores:

```bash
# In .env or environment:
LLAMA_THREADS=4
LLAMA_CPU_MASK=0xF0    # Cores 4-7 (A76)
```

### Context size

Default is 4096 tokens. Increase for longer conversations at the cost of memory:

```bash
CHAT_CTX_SIZE=8192
```

### Thinking mode

Gemma 4 supports thinking (`<think>` tokens) which improves quality but is very slow on edge hardware. Disabled by default:

```bash
ELFIN_CHAT_REASONING_BUDGET=0      # Disabled (default, fast)
ELFIN_CHAT_REASONING_BUDGET=512    # Limited thinking (slower, better quality)
```

## Ingestion on the RK1

After deployment, ingest documents for RAG:

```bash
# On the RK1:
cd ~/elfin
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python src/ingestion/pipeline.py
```

Without ingestion, Qdrant returns 0 results and the AI answers from general knowledge only.

## Standalone deployment (no dev machine)

For a fully standalone RK1 without a dev machine:

```bash
# Clone on the RK1 directly
git clone https://github.com/Cloud-Exit/Elfin.git ~/elfin
cd ~/elfin

# Install prerequisites (see sections above)
# Download assets
make download-assets

# Start everything
TARGET=rockchip make dev-local
```

## Troubleshooting

### Server logs

```bash
tail -f ~/elfin/.elfin-server.log            # Bun app server
tail -f ~/elfin/data/logs/rk-llama-server.log # rk-llama.cpp inference
docker compose logs -f llama-embed           # Embedding model
docker compose logs -f qdrant                # Vector DB
docker compose logs -f kiwix                 # Encyclopedia
```

### Bun idle timeout

Bun's default idle timeout is 10 seconds, which kills SSE streams before the first token arrives on slow hardware. Elfin sets `idleTimeout: 255` (max). If you see `[Bun.serve]: request timed out after 10 seconds`, ensure the latest `server.ts` is deployed.

### Docker restart policy

When switching between Docker llama-server and native rk-llama.cpp, old containers with `restart: unless-stopped` can revive on reboot and steal port 8081. The deploy script uses `docker compose rm -sf llama-server` to prevent this. If the port is taken:

```bash
docker compose rm -sf llama-server
bash scripts/rk_llama_cpp.sh stop
bash scripts/rk_llama_cpp.sh server-bg
```
