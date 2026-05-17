#!/usr/bin/env bash
#
# Sync /workspace to a remote RK1 (or any SSH host) and run `make dev` there.
# Watches local files and re-syncs on change, restarting the Bun backend.
#
# Required env:
#   ELFIN_REMOTE_HOST       SSH hostname (e.g. rk1.local, 192.168.1.42)
#   ELFIN_REMOTE_HOST_USER  SSH user
#
# Optional env:
#   ELFIN_REMOTE_PATH   remote project path (default: /home/<user>/elfin)
#   ELFIN_REMOTE_PORT   ssh port (default: 22)
#   TARGET              local (default) or rockchip
#   RK1_TARGET          legacy flag, ignored if HOST/USER set
#   LLAMA_IMAGE / LLAMA_NGL / LLAMA_THREADS / LLAMA_CPU_MASK
#                       passed through to remote docker compose
#   CHAT_MODEL / CHAT_MMPROJ / EMBED_MODEL / CHAT_CTX_SIZE
#                       passed through to remote docker compose

set -euo pipefail

: "${ELFIN_REMOTE_HOST:?ELFIN_REMOTE_HOST required (e.g. rk1.local)}"
: "${ELFIN_REMOTE_HOST_USER:?ELFIN_REMOTE_HOST_USER required (e.g. elfin)}"

REMOTE_PATH="${ELFIN_REMOTE_PATH:-/home/${ELFIN_REMOTE_HOST_USER}/elfin}"
SSH_PORT="${ELFIN_REMOTE_PORT:-22}"
SSH_TARGET="${ELFIN_REMOTE_HOST_USER}@${ELFIN_REMOTE_HOST}"

CTRL_SOCK="/tmp/elfin-ssh-${USER}-${ELFIN_REMOTE_HOST}-${SSH_PORT}.sock"
SSH_OPTS=(
  -p "${SSH_PORT}"
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=15
  -o ControlMaster=auto
  -o "ControlPath=${CTRL_SOCK}"
  -o ControlPersist=10m
)

TARGET="${TARGET:-rockchip}"

# Default Docker llama.cpp path: CPU image + 0 GPU layers for stability.
# TARGET=rockchip replaces docker llama-server with rk-llama.cpp RKNPU2.
LLAMA_IMAGE="${LLAMA_IMAGE:-ghcr.io/ggml-org/llama.cpp:server}"
LLAMA_NGL="${LLAMA_NGL:-0}"
LLAMA_THREADS="${LLAMA_THREADS:-4}"
LLAMA_CPU_MASK="${LLAMA_CPU_MASK:-0xF0}"
CHAT_MODEL="${CHAT_MODEL:-gemma-4-E4B-it-Q5_K_M.gguf}"
CHAT_MMPROJ="${CHAT_MMPROJ:-mmproj-F16.gguf}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text-v1.5.Q8_0.gguf}"
CHAT_CTX_SIZE="${CHAT_CTX_SIZE:-4096}"
ELFIN_PORT="${ELFIN_PORT:-8885}"

ELFIN_INFERENCE_ENDPOINT="${ELFIN_INFERENCE_ENDPOINT:-http://localhost:8081}"
ELFIN_EMBED_ENDPOINT="${ELFIN_EMBED_ENDPOINT:-http://localhost:8082}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
KIWIX_URL="${KIWIX_URL:-http://localhost:8083}"
DATABASE_URL="${DATABASE_URL:-file:./data/elfin.db}"
DEMO_MODE="${DEMO_MODE:-true}"

# If requested chat model is missing locally, fall back to any available Gemma 4 E4B GGUF.
if [ ! -f "./data/models/${CHAT_MODEL}" ]; then
  if compgen -G "./data/models/gemma-4-E4B-it-*.gguf" >/dev/null; then
    CHAT_MODEL="$(basename "$(ls ./data/models/gemma-4-E4B-it-*.gguf | head -n 1)")"
    echo "[local] requested chat model not found, using available model: ${CHAT_MODEL}"
  fi
fi

# Env file Bun auto-loads on the remote (overrides repo .env).
# Written each bootstrap; rsync excludes it so host changes don't clobber it.
ENV_FILE_LOCAL=$(mktemp)
trap "rm -f ${ENV_FILE_LOCAL}" EXIT
cat > "${ENV_FILE_LOCAL}" <<EOF
TARGET=${TARGET}
LLAMA_IMAGE=${LLAMA_IMAGE}
LLAMA_NGL=${LLAMA_NGL}
LLAMA_THREADS=${LLAMA_THREADS}
LLAMA_CPU_MASK=${LLAMA_CPU_MASK}
CHAT_MODEL=${CHAT_MODEL}
CHAT_MMPROJ=${CHAT_MMPROJ}
EMBED_MODEL=${EMBED_MODEL}
CHAT_CTX_SIZE=${CHAT_CTX_SIZE}
ELFIN_PORT=${ELFIN_PORT}
ELFIN_INFERENCE_ENDPOINT=${ELFIN_INFERENCE_ENDPOINT}
ELFIN_EMBED_ENDPOINT=${ELFIN_EMBED_ENDPOINT}
QDRANT_URL=${QDRANT_URL}
KIWIX_URL=${KIWIX_URL}
DATABASE_URL=${DATABASE_URL}
DEMO_MODE=${DEMO_MODE}
EOF

EXCLUDES=(
  --exclude=.git/
  --exclude=node_modules/
  --exclude=.venv/
  --exclude=__pycache__/
  --exclude=data/
  --exclude=datasets/
  --exclude=static/dist/
  --exclude=artifacts/
  --exclude='*.pyc'
  --exclude=.DS_Store
  --exclude=.elfin-server.pid
  --exclude=.elfin-server.log
  --exclude=.env.local
  --exclude=.env
)

ssh_run() {
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "$@"
}

ensure_remote_ownership() {
  # If prior docker runs used sudo, bind-mount dirs may be root-owned.
  # Normalize ownership so rsync can write without permission errors.
  ssh_run "
    set -e
    if command -v sudo >/dev/null 2>&1; then
      sudo mkdir -p ${REMOTE_PATH}/data/models ${REMOTE_PATH}/data/datasets/zim ${REMOTE_PATH}/data/qdrant
      sudo chown -R ${ELFIN_REMOTE_HOST_USER}:${ELFIN_REMOTE_HOST_USER} ${REMOTE_PATH}
    else
      mkdir -p ${REMOTE_PATH}/data/models ${REMOTE_PATH}/data/datasets/zim ${REMOTE_PATH}/data/qdrant
    fi
  "
}

remote_sh() {
  # Stream the command over stdin to avoid nested quote breakage.
  # This handles embedded single quotes safely (e.g. echo '...').
  printf '%s\n' "$*" | ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" \
    "export BUN_INSTALL=\"\$HOME/.bun\"; export PATH=\"\$BUN_INSTALL/bin:\$PATH\"; bash -se"
}

sync_files() {
  rsync -az --delete \
    --no-owner --no-group \
    -e "ssh ${SSH_OPTS[*]}" \
    "${EXCLUDES[@]}" \
    ./ "${SSH_TARGET}:${REMOTE_PATH}/"
}

sync_runtime_assets() {
  echo "[rk1] syncing runtime assets..."
  ssh_run "mkdir -p ${REMOTE_PATH}/data/models ${REMOTE_PATH}/data/datasets/zim ${REMOTE_PATH}/data/datasets/raw"
  rsync -az --delete --no-owner --no-group -e "ssh ${SSH_OPTS[*]}" ./data/models/ "${SSH_TARGET}:${REMOTE_PATH}/data/models/"
  rsync -az --delete --no-owner --no-group -e "ssh ${SSH_OPTS[*]}" ./data/datasets/zim/ "${SSH_TARGET}:${REMOTE_PATH}/data/datasets/zim/"
  rsync -az --delete --no-owner --no-group -e "ssh ${SSH_OPTS[*]}" ./data/datasets/raw/ "${SSH_TARGET}:${REMOTE_PATH}/data/datasets/raw/"
}

verify_remote_runtime_assets() {
  remote_sh "
    set -euo pipefail
    test -f ${REMOTE_PATH}/data/models/${CHAT_MODEL} || {
      echo '[rk1] missing remote chat model:' ${REMOTE_PATH}/data/models/${CHAT_MODEL}
      ls -lah ${REMOTE_PATH}/data/models || true
      exit 1
    }
    test -f ${REMOTE_PATH}/data/models/${EMBED_MODEL} || {
      echo '[rk1] missing remote embed model:' ${REMOTE_PATH}/data/models/${EMBED_MODEL}
      ls -lah ${REMOTE_PATH}/data/models || true
      exit 1
    }
    ls ${REMOTE_PATH}/data/datasets/zim/*.zim >/dev/null 2>&1 || {
      echo '[rk1] missing remote ZIM assets in' ${REMOTE_PATH}/data/datasets/zim
      ls -lah ${REMOTE_PATH}/data/datasets/zim || true
      exit 1
    }
  "
}

validate_runtime_assets() {
  local missing=0

  if [ ! -f "./data/models/${CHAT_MODEL}" ]; then
    echo "[local] missing required chat model: ./data/models/${CHAT_MODEL}"
    missing=1
  fi

  if [ ! -f "./data/models/${EMBED_MODEL}" ]; then
    echo "[local] missing required embed model: ./data/models/${EMBED_MODEL}"
    missing=1
  fi

  if ! compgen -G "./data/datasets/zim/*.zim" >/dev/null; then
    echo "[local] missing required ZIM assets: ./data/datasets/zim/*.zim"
    missing=1
  fi

  if [ "${missing}" -ne 0 ]; then
    echo "[local] runtime assets are missing. Run: make download-assets"
    exit 1
  fi
}

push_env() {
  # Bun reads .env and .env.local; docker compose only reads .env.
  # Write to .env so both pick it up.
  scp -q "${SSH_OPTS[@]/-p/-P}" "${ENV_FILE_LOCAL}" "${SSH_TARGET}:${REMOTE_PATH}/.env"
}

restart_server() {
  echo "[rk1] (re)starting bun server..."
  push_env
  remote_sh "
    cd ${REMOTE_PATH} && \
    if [ -f .elfin-server.pid ]; then kill \$(cat .elfin-server.pid) 2>/dev/null || true; fi && \
    pkill -f \"bun run src/backend/server.ts\" 2>/dev/null || true && \
    sleep 0.3 && \
    nohup bun run src/backend/server.ts > .elfin-server.log 2>&1 & \
    echo \$! > .elfin-server.pid
  " || echo "[rk1] WARN: server restart failed; check .elfin-server.log on remote"
}

build_frontend_remote() {
  remote_sh "cd ${REMOTE_PATH} && bun build src/frontend/main.tsx --outdir static/dist --minify >/dev/null"
}

remote_wait_http() {
  local url="$1"
  local label="$2"

  for _ in $(seq 1 60); do
    if remote_sh "curl -sf ${url} > /dev/null 2>&1"; then
      return 0
    fi
    printf '.'
    sleep 1
  done
  echo
  echo "[rk1] timed out waiting for ${label}: ${url}"
  if [ "${TARGET}" = "rockchip" ] && [ "${label}" = "llama-server" ]; then
    remote_sh "tail -200 ${REMOTE_PATH}/data/logs/rk-llama-server.log 2>/dev/null || true" || true
  fi
  exit 1
}

bootstrap() {
  echo "[rk1] target: ${SSH_TARGET}:${REMOTE_PATH}"
  ssh_run "mkdir -p ${REMOTE_PATH}"
  ensure_remote_ownership
  validate_runtime_assets
  echo "[rk1] initial sync..."
  sync_files
  sync_runtime_assets
  verify_remote_runtime_assets

  echo "[rk1] pushing .env..."
  push_env

  echo "[rk1] checking remote toolchain..."
  remote_sh "
    set -euo pipefail
    if ! command -v bun >/dev/null 2>&1; then
      echo '[rk1] bun not found; installing...'
      if ! command -v curl >/dev/null 2>&1; then
        echo 'curl is required to install bun on remote'
        exit 1
      fi
      if ! command -v unzip >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
          if command -v sudo >/dev/null 2>&1; then
            sudo apt-get update
            sudo apt-get install -y unzip
          elif [ \"\$(id -u)\" = '0' ]; then
            apt-get update
            apt-get install -y unzip
          else
            echo 'unzip is required for bun install, but no sudo/root is available'
            exit 1
          fi
        else
          echo 'unzip is required for bun install (no supported package manager detected)'
          exit 1
        fi
      fi
      curl -fsSL https://bun.com/install | bash
    fi
    command -v bun >/dev/null 2>&1 || { echo 'bun installation failed on remote'; exit 1; }
    bun --version
    if ! command -v docker >/dev/null 2>&1; then
      echo '[rk1] docker not found; installing...'
      if command -v apt-get >/dev/null 2>&1; then
        if command -v sudo >/dev/null 2>&1; then
          SUDO='sudo'
        elif [ \"\$(id -u)\" = '0' ]; then
          SUDO=''
        else
          echo 'docker install requires sudo/root on remote'
          exit 1
        fi
        \$SUDO apt-get update
        \$SUDO apt-get install -y docker.io
        if command -v systemctl >/dev/null 2>&1; then
          \$SUDO systemctl enable --now docker || true
        fi
      else
        echo 'docker not installed and no supported package manager found'
        exit 1
      fi
    fi
    if docker compose version >/dev/null 2>&1; then
      :
    elif command -v docker-compose >/dev/null 2>&1; then
      :
    elif command -v apt-get >/dev/null 2>&1; then
      if command -v sudo >/dev/null 2>&1; then
        SUDO='sudo'
      elif [ \"\$(id -u)\" = '0' ]; then
        SUDO=''
      else
        echo 'docker compose install requires sudo/root on remote'
        exit 1
      fi
      \$SUDO apt-get update
      \$SUDO apt-get install -y docker-compose-v2 || \
      \$SUDO apt-get install -y docker-compose-plugin || \
      \$SUDO apt-get install -y docker-compose
    else
      echo 'docker compose not available and no supported package manager found'
      exit 1
    fi
    if [ '${TARGET}' = 'rockchip' ]; then
      echo '[rk1] checking rk-llama.cpp build toolchain...'
      missing=''
      for tool in git cmake make g++; do
        command -v \$tool >/dev/null 2>&1 || missing=\"\$missing \$tool\"
      done
      if [ -n \"\$missing\" ]; then
        if command -v apt-get >/dev/null 2>&1; then
          if command -v sudo >/dev/null 2>&1; then
            SUDO='sudo'
          elif [ \"\$(id -u)\" = '0' ]; then
            SUDO=''
          else
            echo 'rk-llama.cpp build tools missing and sudo/root is unavailable:' \$missing
            exit 1
          fi
          \$SUDO apt-get update
          \$SUDO apt-get install -y git cmake make g++
        else
          echo 'rk-llama.cpp build tools missing and no supported package manager found:' \$missing
          exit 1
        fi
      fi
    fi
  "

  echo "[rk1] bun install..."
  remote_sh "cd ${REMOTE_PATH} && bun install"

  echo "[rk1] build frontend..."
  build_frontend_remote

  echo "[rk1] docker compose up..."
  remote_sh "
    cd ${REMOTE_PATH}
    services='llama-server llama-embed qdrant kiwix'
    if [ '${TARGET}' = 'rockchip' ]; then
      services='llama-embed qdrant kiwix'
    fi
    if docker info >/dev/null 2>&1; then
      if docker compose version >/dev/null 2>&1; then
        if [ '${TARGET}' = 'rockchip' ]; then docker compose rm -sf llama-server >/dev/null 2>&1 || true; fi
        docker compose up -d \$services
      elif command -v docker-compose >/dev/null 2>&1; then
        if [ '${TARGET}' = 'rockchip' ]; then docker-compose rm -sf llama-server >/dev/null 2>&1 || true; fi
        docker-compose up -d \$services
      else
        echo 'docker compose not available on remote'
        exit 1
      fi
    elif command -v sudo >/dev/null 2>&1; then
      if sudo docker compose version >/dev/null 2>&1; then
        if [ '${TARGET}' = 'rockchip' ]; then sudo docker compose rm -sf llama-server >/dev/null 2>&1 || true; fi
        sudo docker compose up -d \$services
      elif command -v docker-compose >/dev/null 2>&1; then
        if [ '${TARGET}' = 'rockchip' ]; then sudo docker-compose rm -sf llama-server >/dev/null 2>&1 || true; fi
        sudo docker-compose up -d \$services
      else
        echo 'docker compose not available on remote (even via sudo)'
        exit 1
      fi
    else
      echo 'docker daemon not accessible for current user and sudo is unavailable'
      exit 1
    fi
  "

  if [ "${TARGET}" = "rockchip" ]; then
    echo "[rk1] ensuring render group for NPU access..."
    ssh_run "
      if ! id -nG ${ELFIN_REMOTE_HOST_USER} | grep -qw render; then
        if command -v sudo >/dev/null 2>&1; then
          sudo usermod -aG render ${ELFIN_REMOTE_HOST_USER}
          echo '[rk1] added ${ELFIN_REMOTE_HOST_USER} to render group'
        else
          echo '[rk1] WARNING: user not in render group and no sudo available. NPU may not work.'
        fi
      fi
    "
    echo "[rk1] starting rk-llama.cpp llama-server..."
    remote_sh "cd ${REMOTE_PATH} && sg render -c 'bash scripts/rk_llama_cpp.sh server-bg'"
  fi

  echo "[rk1] waiting for services..."
  remote_wait_http "http://localhost:8081/health" "llama-server"
  remote_wait_http "http://localhost:8082/health" "llama-embed"
  remote_wait_http "http://localhost:6333/healthz" "Qdrant"
  echo

  if [ -f prisma/schema.prisma ]; then
    echo "[rk1] prisma db push..."
    remote_sh "cd ${REMOTE_PATH} && bunx prisma db push --accept-data-loss" || true
  fi

  echo "[rk1] checking Qdrant ingestion status..."
  local qdrant_count
  qdrant_count="$(remote_sh "curl -sf http://localhost:6333/collections/elfin_docs 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get(\"result\",{}).get(\"points_count\",0))' 2>/dev/null || echo 0")"
  qdrant_count="$(echo "$qdrant_count" | tr -d '[:space:]')"
  if [ "${qdrant_count:-0}" = "0" ] || [ "${qdrant_count:-0}" = "" ]; then
    echo "[rk1] Qdrant collection empty or missing. Running ingestion pipeline..."
    remote_sh "
      cd ${REMOTE_PATH}
      if [ ! -x .venv/bin/pip ]; then
        rm -rf .venv
        python3 -m venv .venv 2>/dev/null || {
          echo '[rk1] installing python3-venv...'
          if command -v sudo >/dev/null 2>&1; then
            sudo apt-get update -qq && sudo apt-get install -y -qq python3-venv
          fi
          rm -rf .venv && python3 -m venv .venv
        }
      fi
      .venv/bin/pip install -q -r requirements.txt
      .venv/bin/python src/ingestion/pipeline.py
    "
  else
    echo "[rk1] Qdrant has ${qdrant_count} vectors, skipping ingestion."
  fi

  restart_server
}

stream_logs() {
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "tail -F ${REMOTE_PATH}/.elfin-server.log" &
  LOG_PID=$!
}

cleanup() {
  echo
  echo "[local] shutting down..."
  if [ -n "${LOG_PID:-}" ]; then kill "${LOG_PID}" 2>/dev/null || true; fi
  remote_sh "
    cd ${REMOTE_PATH} 2>/dev/null && \
    if [ '${TARGET}' = 'rockchip' ]; then bash scripts/rk_llama_cpp.sh stop 2>/dev/null || true; fi && \
    if [ -f .elfin-server.pid ]; then kill \$(cat .elfin-server.pid) 2>/dev/null || true; rm -f .elfin-server.pid; fi
  " || true
  ssh -O exit "${SSH_OPTS[@]}" "${SSH_TARGET}" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM EXIT

bootstrap
stream_logs

echo "[local] watching for code changes (Ctrl-C to stop)..."

WATCH_PATHS=(src prisma config Makefile docker-compose.yml package.json bun.lock tsconfig.json)
WATCH_EXISTS=()
for p in "${WATCH_PATHS[@]}"; do
  [ -e "$p" ] && WATCH_EXISTS+=("$p")
done

if command -v fswatch >/dev/null 2>&1; then
  fswatch -o --event Created --event Updated --event Removed --event Renamed \
    "${WATCH_EXISTS[@]}" \
    | while read -r _; do
        echo "[sync] change detected"
        sync_files
        build_frontend_remote
        restart_server
      done
elif command -v inotifywait >/dev/null 2>&1; then
  while true; do
    inotifywait -qq -r -e modify,create,delete,move "${WATCH_EXISTS[@]}" || true
    echo "[sync] change detected"
    sync_files
    build_frontend_remote
    restart_server
  done
else
  echo "ERROR: install 'fswatch' (mac: brew install fswatch) or 'inotify-tools' (linux: apt install inotify-tools)"
  echo "Server is running on remote; press Ctrl-C to stop."
  wait
fi
