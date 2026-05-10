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

LLAMA_IMAGE="${LLAMA_IMAGE:-ghcr.io/ggml-org/llama.cpp:server-vulkan}"
LLAMA_NGL="${LLAMA_NGL:-99}"
LLAMA_THREADS="${LLAMA_THREADS:-4}"
LLAMA_CPU_MASK="${LLAMA_CPU_MASK:-0xF0}"
CHAT_MODEL="${CHAT_MODEL:-gemma-4-E4B-it-Q4_K_M.gguf}"
CHAT_MMPROJ="${CHAT_MMPROJ:-mmproj-F16.gguf}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text-v1.5.Q8_0.gguf}"
CHAT_CTX_SIZE="${CHAT_CTX_SIZE:-4096}"
ELFIN_PORT="${ELFIN_PORT:-8885}"

ELFIN_INFERENCE_ENDPOINT="${ELFIN_INFERENCE_ENDPOINT:-http://localhost:8081}"
ELFIN_EMBED_ENDPOINT="${ELFIN_EMBED_ENDPOINT:-http://localhost:8082}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
KIWIX_URL="${KIWIX_URL:-http://localhost:8083}"

# Env file Bun auto-loads on the remote (overrides repo .env).
# Written each bootstrap; rsync excludes it so host changes don't clobber it.
ENV_FILE_LOCAL=$(mktemp)
trap "rm -f ${ENV_FILE_LOCAL}" EXIT
cat > "${ENV_FILE_LOCAL}" <<EOF
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

remote_sh() {
  ssh "${SSH_OPTS[@]}" "${SSH_TARGET}" "bash -lc '$*'"
}

sync_files() {
  rsync -az --delete \
    -e "ssh ${SSH_OPTS[*]}" \
    "${EXCLUDES[@]}" \
    ./ "${SSH_TARGET}:${REMOTE_PATH}/"
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

bootstrap() {
  echo "[rk1] target: ${SSH_TARGET}:${REMOTE_PATH}"
  ssh_run "mkdir -p ${REMOTE_PATH}"
  echo "[rk1] initial sync..."
  sync_files

  echo "[rk1] pushing .env..."
  push_env

  echo "[rk1] checking remote toolchain..."
  remote_sh "command -v bun >/dev/null || { echo 'bun not installed on remote'; exit 1; }"
  remote_sh "command -v docker >/dev/null || { echo 'docker not installed on remote'; exit 1; }"

  echo "[rk1] bun install..."
  remote_sh "cd ${REMOTE_PATH} && bun install"

  echo "[rk1] build frontend..."
  build_frontend_remote

  echo "[rk1] docker compose up..."
  remote_sh "cd ${REMOTE_PATH} && docker compose up -d llama-server llama-embed qdrant kiwix"

  echo "[rk1] waiting for services..."
  for url in \
    "http://localhost:8081/health" \
    "http://localhost:8082/health" \
    "http://localhost:6333/healthz"
  do
    for _ in $(seq 1 60); do
      if remote_sh "curl -sf ${url} > /dev/null 2>&1"; then break; fi
      printf '.'
      sleep 1
    done
  done
  echo

  if [ -f prisma/schema.prisma ]; then
    echo "[rk1] prisma db push..."
    remote_sh "cd ${REMOTE_PATH} && bunx prisma db push --accept-data-loss" || true
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
