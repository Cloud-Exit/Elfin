#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Source .env if present (systemd uses EnvironmentFile, manual runs need this)
if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

ACTION="${1:-help}"
DRY_RUN="${DRY_RUN:-0}"

ELFIN_DATA_PATH="${ELFIN_DATA_PATH:-$ROOT_DIR/data}"

RK_LLAMA_CPP_REPO="${RK_LLAMA_CPP_REPO:-https://github.com/invisiofficial/rk-llama.cpp.git}"
RK_LLAMA_CPP_BRANCH="${RK_LLAMA_CPP_BRANCH:-rknpu2}"
RK_LLAMA_CPP_DIR="${RK_LLAMA_CPP_DIR:-$ELFIN_DATA_PATH/toolchains/rk-llama.cpp}"
RK_LLAMA_CPP_BUILD_DIR="${RK_LLAMA_CPP_BUILD_DIR:-$RK_LLAMA_CPP_DIR/build}"
RK_LLAMA_CPP_JOBS="${RK_LLAMA_CPP_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"
CHAT_MODEL="${CHAT_MODEL:-gemma-4-E2B-it-IQ4_XS.gguf}"
RK_LLAMA_CPP_MODEL="${RK_LLAMA_CPP_MODEL:-$ELFIN_DATA_PATH/models/$CHAT_MODEL}"
RK_LLAMA_CPP_MMPROJ="${RK_LLAMA_CPP_MMPROJ:-$ELFIN_DATA_PATH/models/${CHAT_MMPROJ:-mmproj-F16.gguf}}"
RK_LLAMA_CPP_VISION="${RK_LLAMA_CPP_VISION:-1}"
RK_LLAMA_CPP_PORT="${RK_LLAMA_CPP_PORT:-8081}"
RK_LLAMA_CPP_HOST="${RK_LLAMA_CPP_HOST:-0.0.0.0}"
RK_LLAMA_CPP_CTX_SIZE="${RK_LLAMA_CPP_CTX_SIZE:-4096}"
RK_LLAMA_CPP_THREADS="${RK_LLAMA_CPP_THREADS:-${LLAMA_THREADS:-4}}"
RK_LLAMA_CPP_PROMPT="${RK_LLAMA_CPP_PROMPT:-Who are you?}"
RK_LLAMA_CPP_EXTRA_ARGS="${RK_LLAMA_CPP_EXTRA_ARGS:-}"
RK_LLAMA_CPP_REASONING_BUDGET="${RK_LLAMA_CPP_REASONING_BUDGET:--1}"
RK_LLAMA_CPP_CHAT_TEMPLATE="${RK_LLAMA_CPP_CHAT_TEMPLATE:-$ROOT_DIR/config/gemma4-no-think.jinja}"
RK_LLAMA_CPP_SPEC_TYPE="${RK_LLAMA_CPP_SPEC_TYPE:-none}"
RK_LLAMA_CPP_DRAFT_N="${RK_LLAMA_CPP_DRAFT_N:-0}"
RK_LLAMA_CPP_SERVER_EXTRA_ARGS="${RK_LLAMA_CPP_SERVER_EXTRA_ARGS:-}"
RK_LLAMA_CPP_NGL="${RK_LLAMA_CPP_NGL:-${LLAMA_NGL:-99}}"
RK_LLAMA_CPP_BENCH_EXTRA_ARGS="${RK_LLAMA_CPP_BENCH_EXTRA_ARGS:-}"

RKNPU_DEVICE="${RKNPU_DEVICE:-RK3588}"
RKNPU_HYBRID="${RKNPU_HYBRID:-}"
RKNPU_CORES="${RKNPU_CORES:-}"
RKNPU_DOMAINS="${RKNPU_DOMAINS:-}"

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] %q' "$1"
    shift
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
    return 0
  fi
  "$@"
}

usage() {
  cat <<EOF
Usage: bash scripts/rk_llama_cpp.sh <command>

Commands:
  clone       Clone or update invisiofficial/rk-llama.cpp
  build       Configure and build the RKNPU2 llama.cpp fork
  verify      Check RKNPU2 runtime, device, build status, and model
  server      Run OpenAI-compatible llama-server with the configured GGUF
  server-bg   Start llama-server in the background
  stop        Stop background llama-server started by this script
  chat        Run llama-cli with a one-shot prompt
  bench       Run llama-bench against the configured GGUF
  paths       Print resolved paths and environment

Key env:
  RK_LLAMA_CPP_MODEL=$RK_LLAMA_CPP_MODEL
  RK_LLAMA_CPP_MMPROJ=$RK_LLAMA_CPP_MMPROJ
  RKNPU_DEVICE=$RKNPU_DEVICE
  RKNPU_HYBRID=$RKNPU_HYBRID
  RKNPU_CORES=$RKNPU_CORES
  RKNPU_DOMAINS=$RKNPU_DOMAINS

Notes:
  - This is experimental and should run on the RK3588 host, not inside ExitBox.
  - The backend reads normal GGUF files and requantizes layers for the NPU.
  - Avoid concurrent NPU processes; the upstream README warns custom domains can kernel panic.
EOF
}

require_cmd() {
  local cmd="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "$cmd not found in PATH"
    exit 1
  fi
}

ensure_checkout() {
  require_cmd git
  mkdir -p "$(dirname "$RK_LLAMA_CPP_DIR")"

  if [[ -d "$RK_LLAMA_CPP_DIR/.git" ]]; then
    echo "Using existing rk-llama.cpp checkout: $RK_LLAMA_CPP_DIR"
    run git -C "$RK_LLAMA_CPP_DIR" fetch --prune origin
    run git -C "$RK_LLAMA_CPP_DIR" checkout "$RK_LLAMA_CPP_BRANCH"
    run git -C "$RK_LLAMA_CPP_DIR" pull --ff-only origin "$RK_LLAMA_CPP_BRANCH"
    return 0
  fi

  echo "Cloning rk-llama.cpp"
  echo "Repo:   $RK_LLAMA_CPP_REPO"
  echo "Branch: $RK_LLAMA_CPP_BRANCH"
  echo "Dir:    $RK_LLAMA_CPP_DIR"
  run git clone --branch "$RK_LLAMA_CPP_BRANCH" "$RK_LLAMA_CPP_REPO" "$RK_LLAMA_CPP_DIR"
}

check_rknpu2_runtime() {
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi

  local found=0
  local bundled_lib="$RK_LLAMA_CPP_DIR/ggml/src/ggml-rknpu2/libs/librknnrt.so"
  for lib in "$bundled_lib" /usr/lib/librknnrt.so /usr/lib/aarch64-linux-gnu/librknnrt.so /usr/local/lib/librknnrt.so; do
    if [[ -f "$lib" ]]; then
      found=1
      echo "RKNPU2 runtime found: $lib"
      break
    fi
  done

  if [[ "$found" -eq 0 ]]; then
    if [[ -d "$RK_LLAMA_CPP_BUILD_DIR/bin" ]] && ldd "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" 2>/dev/null | grep -q 'librknnrt\.so.*=>'; then
      found=1
      local resolved
      resolved="$(ldd "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" 2>/dev/null | grep 'librknnrt\.so' | awk '{print $3}')"
      echo "RKNPU2 runtime found (via binary linkage): $resolved"
    fi
  fi

  if [[ "$found" -eq 0 ]]; then
    echo "WARNING: librknnrt.so not found (checked system paths, build tree, and binary linkage)."
    echo "Install the RKNN runtime from: https://github.com/airockchip/rknn-toolkit2"
    echo "Falling back to CPU-only inference."
    echo ""
  fi

  if [[ -e /dev/rknpu ]]; then
    echo "NPU device: /dev/rknpu (legacy)"
  elif [[ -e /dev/dri/renderD129 ]]; then
    echo "NPU device: /dev/dri/renderD129 (DRM)"
  elif [[ -e /dev/dri/renderD128 ]]; then
    echo "NPU device: /dev/dri/renderD128 (DRM)"
  else
    echo "WARNING: No NPU device found (/dev/rknpu, /dev/dri/renderD12*)."
    echo "Vendor/BSP kernel required for NPU support (mainline kernel lacks rknpu)."
  fi
}

RKNN_LIB_DIR=""

install_rknn_runtime() {
  local bundled_dir="$RK_LLAMA_CPP_DIR/ggml/src/ggml-rknpu2/libs"
  local bundled_lib="$bundled_dir/librknnrt.so"

  if ldconfig -p 2>/dev/null | grep -q 'librknnrt\.so'; then
    echo "librknnrt.so found in system library path"
    return 0
  fi

  if [[ ! -f "$bundled_lib" ]]; then
    echo "WARNING: librknnrt.so not found in repo or system. NPU offload unavailable."
    return 0
  fi

  echo "Installing bundled librknnrt.so to /usr/lib/..."
  if sudo cp "$bundled_lib" /usr/lib/librknnrt.so 2>/dev/null && sudo ldconfig 2>/dev/null; then
    echo "librknnrt.so installed to /usr/lib/"
    return 0
  fi

  echo "sudo failed, using bundled lib via LD_LIBRARY_PATH"
  RKNN_LIB_DIR="$bundled_dir"
  export LD_LIBRARY_PATH="${bundled_dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

ensure_build() {
  if [[ "$DRY_RUN" != "1" ]] && [[ -x "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" ]]; then
    return 0
  fi

  require_cmd cmake
  require_cmd make
  ensure_checkout
  install_rknn_runtime
  check_rknpu2_runtime

  mkdir -p "$RK_LLAMA_CPP_BUILD_DIR"
  local -a cmake_args=(
    -S "$RK_LLAMA_CPP_DIR"
    -B "$RK_LLAMA_CPP_BUILD_DIR"
    -DLLAMA_RKNPU2=ON
  )
  if [[ -n "$RKNN_LIB_DIR" ]]; then
    cmake_args+=(-DCMAKE_LIBRARY_PATH="$RKNN_LIB_DIR")
    cmake_args+=(-DCMAKE_BUILD_RPATH="$RKNN_LIB_DIR")
    cmake_args+=(-DCMAKE_INSTALL_RPATH="$RKNN_LIB_DIR")
  fi
  run cmake "${cmake_args[@]}"
  run cmake --build "$RK_LLAMA_CPP_BUILD_DIR" --parallel "$RK_LLAMA_CPP_JOBS"

  if [[ "$DRY_RUN" != "1" ]] && [[ -f "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" ]]; then
    echo "Build complete: $RK_LLAMA_CPP_BUILD_DIR/bin/llama-server"
  fi
}

assert_model() {
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  if [[ ! -s "$RK_LLAMA_CPP_MODEL" ]]; then
    echo "Missing model: $RK_LLAMA_CPP_MODEL"
    echo "Set RK_LLAMA_CPP_MODEL=/path/to/model.gguf or download assets first."
    exit 1
  fi
}

pid_file() {
  printf '%s\n' "$ELFIN_DATA_PATH/logs/rk-llama-server.pid"
}

log_file() {
  printf '%s\n' "$ELFIN_DATA_PATH/logs/rk-llama-server.log"
}

stop_server() {
  local pid_path
  pid_path="$(pid_file)"

  if [[ -f "$pid_path" ]]; then
    if kill "$(cat "$pid_path")" 2>/dev/null; then
      echo "Stopped rk-llama.cpp server: $(cat "$pid_path")"
    fi
    rm -f "$pid_path"
  fi

  pkill -f "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" 2>/dev/null || true
}

print_paths() {
  cat <<EOF
RK_LLAMA_CPP_REPO=$RK_LLAMA_CPP_REPO
RK_LLAMA_CPP_BRANCH=$RK_LLAMA_CPP_BRANCH
RK_LLAMA_CPP_DIR=$RK_LLAMA_CPP_DIR
RK_LLAMA_CPP_BUILD_DIR=$RK_LLAMA_CPP_BUILD_DIR
RK_LLAMA_CPP_MODEL=$RK_LLAMA_CPP_MODEL
RK_LLAMA_CPP_MMPROJ=$RK_LLAMA_CPP_MMPROJ
RK_LLAMA_CPP_PORT=$RK_LLAMA_CPP_PORT
RK_LLAMA_CPP_CTX_SIZE=$RK_LLAMA_CPP_CTX_SIZE
RK_LLAMA_CPP_THREADS=$RK_LLAMA_CPP_THREADS
RKNPU_DEVICE=$RKNPU_DEVICE
RKNPU_HYBRID=$RKNPU_HYBRID
RKNPU_CORES=$RKNPU_CORES
RKNPU_DOMAINS=$RKNPU_DOMAINS
EOF
}

run_with_rknpu_env() {
  local -a env_args
  env_args=()
  [[ -n "$RKNPU_DEVICE" ]] && env_args+=("RKNPU_DEVICE=$RKNPU_DEVICE")
  [[ -n "$RKNPU_HYBRID" ]] && env_args+=("RKNPU_HYBRID=$RKNPU_HYBRID")
  [[ -n "$RKNPU_CORES" ]] && env_args+=("RKNPU_CORES=$RKNPU_CORES")
  [[ -n "$RKNPU_DOMAINS" ]] && env_args+=("RKNPU_DOMAINS=$RKNPU_DOMAINS")

  local bundled_dir="$RK_LLAMA_CPP_DIR/ggml/src/ggml-rknpu2/libs"
  if [[ -d "$bundled_dir" ]]; then
    env_args+=("LD_LIBRARY_PATH=${bundled_dir}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}")
  fi

  ulimit -n 65536 2>/dev/null || true
  run env "${env_args[@]}" "$@"
}

server() {
  local -a args
  ensure_build
  assert_model

  args=(
    "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server"
    -m "$RK_LLAMA_CPP_MODEL"
    --host "$RK_LLAMA_CPP_HOST"
    --port "$RK_LLAMA_CPP_PORT"
    -c "$RK_LLAMA_CPP_CTX_SIZE"
    --threads "$RK_LLAMA_CPP_THREADS"
    --reasoning-budget "$RK_LLAMA_CPP_REASONING_BUDGET"
    -np 1
    --jinja
    --chat-template-file "$RK_LLAMA_CPP_CHAT_TEMPLATE"
  )

  if [[ "$RK_LLAMA_CPP_SPEC_TYPE" != "none" ]] && [[ -n "$RK_LLAMA_CPP_SPEC_TYPE" ]]; then
    args+=(--spec-type "$RK_LLAMA_CPP_SPEC_TYPE" --draft "$RK_LLAMA_CPP_DRAFT_N")
  fi

  if [[ "$RK_LLAMA_CPP_VISION" == "1" ]] && [[ -s "$RK_LLAMA_CPP_MMPROJ" ]]; then
    echo "Vision enabled with mmproj: $RK_LLAMA_CPP_MMPROJ"
    args+=(--mmproj "$RK_LLAMA_CPP_MMPROJ")
  elif [[ "$RK_LLAMA_CPP_VISION" == "1" ]]; then
    echo "WARNING: RK_LLAMA_CPP_VISION=1 but mmproj missing: $RK_LLAMA_CPP_MMPROJ"
  fi

  # shellcheck disable=SC2206
  args+=($RK_LLAMA_CPP_SERVER_EXTRA_ARGS)
  run_with_rknpu_env "${args[@]}"
}

server_bg() {
  local -a args
  local pid_path
  local log_path

  ensure_build
  assert_model
  mkdir -p "$ELFIN_DATA_PATH/logs"
  pid_path="$(pid_file)"
  log_path="$(log_file)"

  stop_server

  args=(
    "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server"
    -m "$RK_LLAMA_CPP_MODEL"
    --host "$RK_LLAMA_CPP_HOST"
    --port "$RK_LLAMA_CPP_PORT"
    -c "$RK_LLAMA_CPP_CTX_SIZE"
    --threads "$RK_LLAMA_CPP_THREADS"
    --reasoning-budget "$RK_LLAMA_CPP_REASONING_BUDGET"
    -np 1
    --jinja
    --chat-template-file "$RK_LLAMA_CPP_CHAT_TEMPLATE"
  )

  if [[ "$RK_LLAMA_CPP_SPEC_TYPE" != "none" ]] && [[ -n "$RK_LLAMA_CPP_SPEC_TYPE" ]]; then
    args+=(--spec-type "$RK_LLAMA_CPP_SPEC_TYPE" --draft "$RK_LLAMA_CPP_DRAFT_N")
  fi

  if [[ "$RK_LLAMA_CPP_VISION" == "1" ]] && [[ -s "$RK_LLAMA_CPP_MMPROJ" ]]; then
    echo "Vision enabled with mmproj: $RK_LLAMA_CPP_MMPROJ"
    args+=(--mmproj "$RK_LLAMA_CPP_MMPROJ")
  elif [[ "$RK_LLAMA_CPP_VISION" == "1" ]]; then
    echo "WARNING: RK_LLAMA_CPP_VISION=1 but mmproj missing: $RK_LLAMA_CPP_MMPROJ"
  fi

  # shellcheck disable=SC2206
  args+=($RK_LLAMA_CPP_SERVER_EXTRA_ARGS)

  if [[ "$DRY_RUN" == "1" ]]; then
    run_with_rknpu_env "${args[@]}"
    return 0
  fi

  echo "Starting rk-llama.cpp server on ${RK_LLAMA_CPP_HOST}:${RK_LLAMA_CPP_PORT}"
  echo "Log: $log_path"
  (
    run_with_rknpu_env "${args[@]}"
  ) >"$log_path" 2>&1 &
  echo "$!" > "$pid_path"
}

chat() {
  local -a args
  ensure_build
  assert_model

  args=(
    "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-cli"
    -m "$RK_LLAMA_CPP_MODEL"
    -c "$RK_LLAMA_CPP_CTX_SIZE"
    --threads "$RK_LLAMA_CPP_THREADS"
    -p "$RK_LLAMA_CPP_PROMPT"
  )

  if [[ -s "$RK_LLAMA_CPP_MMPROJ" ]]; then
    args+=(--mmproj "$RK_LLAMA_CPP_MMPROJ")
  fi

  # shellcheck disable=SC2206
  args+=($RK_LLAMA_CPP_EXTRA_ARGS)
  run_with_rknpu_env "${args[@]}"
}

bench() {
  local -a args
  ensure_build
  assert_model

  args=(
    "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-bench"
    -m "$RK_LLAMA_CPP_MODEL"
    -t "$RK_LLAMA_CPP_THREADS"
  )

  # shellcheck disable=SC2206
  args+=($RK_LLAMA_CPP_BENCH_EXTRA_ARGS)
  run_with_rknpu_env "${args[@]}"
}

verify() {
  echo "=== RKNPU2 Runtime Check ==="
  check_rknpu2_runtime

  echo ""
  echo "=== NPU Device ==="
  if [[ -e /dev/rknpu ]]; then
    echo "Found: /dev/rknpu (legacy)"
    ls -la /dev/rknpu
  fi
  if [[ -d /dev/dri ]]; then
    echo "DRM devices:"
    ls -la /dev/dri/
    if dmesg 2>/dev/null | grep -qi 'rknpu.*initialized'; then
      echo "RKNPU DRM driver: LOADED (confirmed via dmesg)"
    fi
  fi
  if [[ ! -e /dev/rknpu ]] && [[ ! -e /dev/dri/renderD128 ]]; then
    echo "WARNING: No NPU device found"
  fi

  echo ""
  echo "=== Build Status ==="
  if [[ -f "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" ]]; then
    echo "Binary: $RK_LLAMA_CPP_BUILD_DIR/bin/llama-server"
    if ldd "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" 2>/dev/null | grep -q rknn; then
      echo "RKNN linked: YES"
    else
      echo "RKNN linked: NO (CPU-only build)"
    fi
    echo ""
    echo "=== Linked libraries ==="
    ldd "$RK_LLAMA_CPP_BUILD_DIR/bin/llama-server" 2>/dev/null || echo "(ldd failed)"
  else
    echo "Binary not found. Run: bash scripts/rk_llama_cpp.sh build"
  fi

  echo ""
  echo "=== Model ==="
  if [[ -s "$RK_LLAMA_CPP_MODEL" ]]; then
    echo "Found: $RK_LLAMA_CPP_MODEL ($(du -h "$RK_LLAMA_CPP_MODEL" | cut -f1))"
  else
    echo "NOT found: $RK_LLAMA_CPP_MODEL"
  fi
}

case "$ACTION" in
  clone)
    ensure_checkout
    ;;
  build)
    ensure_build
    ;;
  verify)
    verify
    ;;
  server)
    server
    ;;
  server-bg)
    server_bg
    ;;
  stop)
    stop_server
    ;;
  chat)
    chat
    ;;
  bench)
    bench
    ;;
  paths)
    print_paths
    ;;
  help | -h | --help)
    usage
    ;;
  *)
    echo "Unknown rk-llama.cpp command: $ACTION"
    usage
    exit 1
    ;;
esac
