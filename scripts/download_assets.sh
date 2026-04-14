#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

DRY_RUN="${DRY_RUN:-0}"
CHAT_MODEL="${CHAT_MODEL:-gemma-4-E4B-it-Q5_K_M.gguf}"
CHAT_MMPROJ="${CHAT_MMPROJ:-mmproj-F16.gguf}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text-v1.5.Q8_0.gguf}"
HF_CLI_BIN="${HF_CLI_BIN:-}"

CHAT_REPO="${CHAT_REPO:-unsloth/gemma-4-E4B-it-GGUF}"
EMBED_REPO="${EMBED_REPO:-nomic-ai/nomic-embed-text-v1.5-GGUF}"
TRAIN_BASE_REPO="${TRAIN_BASE_REPO:-google/gemma-4-E4B-it}"

MODELS_DIR="${MODELS_DIR:-$ROOT_DIR/data/models}"
TRAIN_BASE_DIR="${TRAIN_BASE_DIR:-$ROOT_DIR/data/training/base-model/google-gemma-4-E4B-it}"
ZIMS_DIR="${ZIMS_DIR:-$ROOT_DIR/data/datasets/zim}"
RAW_DOCS_DIR="${RAW_DOCS_DIR:-$ROOT_DIR/data/datasets/raw}"
KIWIX_ROOT_URL="${KIWIX_ROOT_URL:-https://download.kiwix.org/zim}"
KIWIX_LIBRARY_API="${KIWIX_LIBRARY_API:-https://library.kiwix.org/catalog/v2/entries}"
KIWIX_ZIM_LIST_FILE="${KIWIX_ZIM_LIST_FILE:-$ROOT_DIR/config/kiwix-zims.txt}"
RAW_DOCS_LIST_FILE="${RAW_DOCS_LIST_FILE:-$ROOT_DIR/config/raw-docs.tsv}"
ASSET_FALLBACK_BASE_URL="${ASSET_FALLBACK_BASE_URL:-https://elfin.cloud-exit.net/data}"

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

require_cli() {
  if [[ "$DRY_RUN" == "1" ]]; then
    HF_CLI_BIN="${HF_CLI_BIN:-huggingface-cli}"
    return 0
  fi

  if [[ -n "$HF_CLI_BIN" ]] && command -v "$HF_CLI_BIN" >/dev/null 2>&1; then
    return 0
  fi

  if command -v hf >/dev/null 2>&1; then
    HF_CLI_BIN="hf"
    return 0
  fi

  if command -v huggingface-cli >/dev/null 2>&1; then
    HF_CLI_BIN="huggingface-cli"
    return 0
  fi

  echo "Neither 'hf' nor 'huggingface-cli' found in PATH"
  echo "If needed, set HF_CLI_BIN explicitly."
  echo "Example: HF_CLI_BIN=hf make download-assets"
  echo "Or: HF_CLI_BIN=huggingface-cli make download-assets"
  echo "Install the Hugging Face CLI on the host, then re-run make download-assets"
  exit 1
}

hf_download() {
  if [[ -z "$HF_CLI_BIN" ]]; then
    echo "HF_CLI_BIN is not set"
    echo "Install it on the host, then re-run make download-assets"
    exit 1
  fi

  if [[ "$HF_CLI_BIN" == "hf" ]]; then
    run hf download "$@"
    return 0
  fi

  run huggingface-cli download "$@"
}

require_tools() {
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi

  if ! command -v wget >/dev/null 2>&1; then
    echo "wget not found in PATH"
    echo "Install it on the host, then re-run make download-assets"
    exit 1
  fi

  if ! command -v curl >/dev/null 2>&1; then
    echo "curl not found in PATH"
    echo "Install it on the host, then re-run make download-assets"
    exit 1
  fi
}

is_valid_pdf() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  [[ "$(head -c 5 "$path" 2>/dev/null)" == "%PDF-" ]]
}

is_valid_gguf() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  [[ "$(head -c 4 "$path" 2>/dev/null)" == "GGUF" ]]
}

is_valid_zim() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  [[ "$(head -c 4 "$path" 2>/dev/null)" == $'ZIM\004' ]]
}

is_valid_model_snapshot() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  [[ -s "$dir/config.json" ]] || return 1
  [[ -s "$dir/tokenizer.json" || -s "$dir/tokenizer.model" ]] || return 1
  find "$dir" -maxdepth 1 \( -name "*.safetensors" -o -name "*.safetensors.index.json" \) -type f -size +0c -print -quit >/dev/null
}

download_from_fallback() {
  local relative_path="$1"
  local target="$2"
  local label="$3"
  local url="${ASSET_FALLBACK_BASE_URL%/}/$relative_path"

  echo "Retrying from Elfin asset fallback: $label"
  echo "Fallback URL: $url"
  curl --fail --location --progress-bar \
    --user-agent "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36" \
    "$url" -o "$target"
  echo
}

download_file() {
  local repo="$1"
  local filename="$2"
  local local_dir="$3"
  local target

  mkdir -p "$local_dir"
  target="$local_dir/$filename"
  if [[ -s "$target" ]]; then
    if ! is_valid_gguf "$target"; then
      echo "Existing model file is not a valid GGUF, re-downloading: $target"
      rm -f "$target"
    else
      echo "Skipping existing model file: $target"
      return 0
    fi
  fi
  if ! hf_download "$repo" "$filename" --local-dir "$local_dir"; then
    rm -f "$target"
    download_from_fallback "models/$filename" "$target" "$filename"
  fi
  if ! is_valid_gguf "$target"; then
    echo "Downloaded file is not a valid GGUF from primary source: $target"
    rm -f "$target"
    download_from_fallback "models/$filename" "$target" "$filename"
    if ! is_valid_gguf "$target"; then
      echo "Downloaded file is not a valid GGUF: $target"
      rm -f "$target"
      exit 1
    fi
  fi
}

download_snapshot() {
  local repo="$1"
  local local_dir="$2"

  mkdir -p "$local_dir"
  if is_valid_model_snapshot "$local_dir"; then
    echo "Skipping existing model snapshot dir: $local_dir"
    return 0
  fi
  rm -f "$local_dir"/* 2>/dev/null || true
  hf_download "$repo" --local-dir "$local_dir"
  if ! is_valid_model_snapshot "$local_dir"; then
    echo "Downloaded snapshot is incomplete or invalid: $local_dir"
    exit 1
  fi
}

load_zim_specs() {
  if [[ ! -f "$KIWIX_ZIM_LIST_FILE" ]]; then
    echo "missing ZIM list file: $KIWIX_ZIM_LIST_FILE"
    exit 1
  fi

  ZIM_SPECS=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    ZIM_SPECS+=("$line")
  done < "$KIWIX_ZIM_LIST_FILE"

  if [[ "${#ZIM_SPECS[@]}" -eq 0 ]]; then
    echo "no ZIM specs configured in $KIWIX_ZIM_LIST_FILE"
    exit 1
  fi
}

load_raw_doc_specs() {
  if [[ ! -f "$RAW_DOCS_LIST_FILE" ]]; then
    echo "missing raw docs list file: $RAW_DOCS_LIST_FILE"
    exit 1
  fi

  RAW_DOC_SPECS=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line//[[:space:]]/}" ]] && continue
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    RAW_DOC_SPECS+=("$line")
  done < "$RAW_DOCS_LIST_FILE"

  if [[ "${#RAW_DOC_SPECS[@]}" -eq 0 ]]; then
    echo "no raw docs configured in $RAW_DOCS_LIST_FILE"
    exit 1
  fi
}

fetch_text() {
  local url="$1"
  curl --fail --silent --show-error --location "$url"
}

resolve_kiwix_url() {
  local spec="$1"
  local name flavour api_url

  name="${spec%%|*}"
  flavour=""
  if [[ "$spec" == *"|"* ]]; then
    flavour="${spec#*|}"
  fi
  flavour="${flavour:-}"
  api_url="$KIWIX_LIBRARY_API?name=$name&count=-1"

  python3 - "$api_url" "$name" "$flavour" <<'PY'
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

api_url, wanted_name, wanted_flavour = sys.argv[1:4]
ns = {"atom": "http://www.w3.org/2005/Atom"}

with urllib.request.urlopen(api_url, timeout=30) as response:
    payload = response.read()

root = ET.fromstring(payload)
matches = []
for entry in root.findall("atom:entry", ns):
    name = (entry.findtext("atom:name", default="", namespaces=ns) or "").strip()
    flavour = (entry.findtext("atom:flavour", default="", namespaces=ns) or "").strip()
    if name != wanted_name:
        continue
    if wanted_flavour and flavour != wanted_flavour:
        continue

    for link in entry.findall("atom:link", ns):
        if link.get("type") != "application/x-zim":
            continue
        href = link.get("href", "").strip()
        if href:
            matches.append(href)

if not matches:
    sys.stderr.write(
        f"could not resolve Kiwix ZIM for name='{wanted_name}' flavour='{wanted_flavour}'\n"
    )
    sys.exit(1)

def version_key(url: str):
    match = re.search(r"_(\d{4}-\d{2})\.zim(?:\.meta4)?$", url)
    if match:
        return match.group(1)
    return ""

best = sorted(matches, key=version_key)[-1]
if best.endswith(".meta4"):
    best = best[:-6]
print(best)
PY
}

download_zim() {
  local spec="$1"
  local url filename target

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] resolve Kiwix ZIM via OPDS: $spec"
    echo "[dry-run] wget --continue --show-progress --progress=bar:force:noscroll <resolved-url> -O $ZIMS_DIR/<resolved-filename>"
    return 0
  fi

  url="$(resolve_kiwix_url "$spec")"
  filename="$(basename "$url")"
  target="$ZIMS_DIR/$filename"

  mkdir -p "$ZIMS_DIR"
  if [[ -s "$target" ]]; then
    if ! is_valid_zim "$target"; then
      echo "Existing ZIM is not valid, re-downloading: $target"
      rm -f "$target"
    else
      echo "Skipping existing ZIM: $target"
      return 0
    fi
  fi
  echo "Downloading ZIM: $filename"
  if ! wget --continue --show-progress --progress=bar:force:noscroll "$url" -O "$target"; then
    rm -f "$target"
    download_from_fallback "datasets/zim/$filename" "$target" "$filename"
  fi
  if ! is_valid_zim "$target"; then
    echo "Downloaded file is not a valid ZIM from primary source: $target"
    rm -f "$target"
    download_from_fallback "datasets/zim/$filename" "$target" "$filename"
    if ! is_valid_zim "$target"; then
      echo "Downloaded file is not a valid ZIM: $target"
      rm -f "$target"
      exit 1
    fi
  fi
}

download_raw_doc() {
  local spec="$1"
  local category filename url source target

  category="$(printf '%s' "$spec" | cut -f1)"
  filename="$(printf '%s' "$spec" | cut -f2)"
  url="$(printf '%s' "$spec" | cut -f3)"
  source="$(printf '%s' "$spec" | cut -f4)"
  if [[ -z "$filename" || -z "$url" ]]; then
    echo "invalid raw doc spec: $spec"
    exit 1
  fi

  target="$RAW_DOCS_DIR/$filename"
  mkdir -p "$RAW_DOCS_DIR"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] wget --continue --show-progress --progress=bar:force:noscroll '$url' -O '$target'"
    return 0
  fi

  if [[ -s "$target" ]]; then
    if [[ "${filename##*.}" == "pdf" ]] && ! is_valid_pdf "$target"; then
      echo "Existing raw doc is not a valid PDF, re-downloading: $target"
      rm -f "$target"
    else
      echo "Skipping existing raw doc: $target"
      return 0
    fi
  fi

  echo "Downloading raw doc: $filename ($source)"
  if wget --continue --show-progress --progress=bar:force:noscroll "$url" -O "$target"; then
    if [[ "${filename##*.}" != "pdf" ]] || is_valid_pdf "$target"; then
      return 0
    fi
    echo "wget returned a non-PDF payload, retrying with curl browser user-agent: $filename"
    rm -f "$target"
    if curl --fail --location --progress-bar \
      --user-agent "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36" \
      "$url" -o "$target"; then
      echo
      if is_valid_pdf "$target"; then
        return 0
      fi
    fi
    echo "Downloaded file is not a valid PDF: $target"
    rm -f "$target"
    download_from_fallback "datasets/raw/$filename" "$target" "$filename"
    if [[ "${filename##*.}" != "pdf" ]] || is_valid_pdf "$target"; then
      return 0
    fi
    echo "Downloaded file is not a valid PDF: $target"
    rm -f "$target"
    exit 1
  fi

  if [[ "$url" == https://training.fema.gov/* ]]; then
    echo "Retrying with --no-check-certificate for FEMA training host: $filename"
    wget --no-check-certificate --continue --show-progress --progress=bar:force:noscroll "$url" -O "$target"
    if [[ "${filename##*.}" != "pdf" ]] || is_valid_pdf "$target"; then
      return 0
    fi
    echo "Downloaded file is not a valid PDF: $target"
    rm -f "$target"
    return 0
  fi

  if [[ "${filename##*.}" == "pdf" ]]; then
    echo "wget failed, retrying with curl browser user-agent: $filename"
    if curl --fail --location --progress-bar \
      --user-agent "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36" \
      "$url" -o "$target"; then
      echo
      if is_valid_pdf "$target"; then
        return 0
      fi
      echo "Downloaded file is not a valid PDF: $target"
      rm -f "$target"
    fi
  fi

  download_from_fallback "datasets/raw/$filename" "$target" "$filename"
  if [[ "${filename##*.}" != "pdf" ]] || is_valid_pdf "$target"; then
    return 0
  fi
  echo "Downloaded file is not a valid PDF: $target"
  rm -f "$target"

  exit 1
}

main() {
  require_cli
  require_tools
  load_zim_specs
  load_raw_doc_specs

  echo "Downloading Elfin assets"
  echo "Runtime GGUF repo: $CHAT_REPO"
  echo "Embedding GGUF repo: $EMBED_REPO"
  echo "Training base repo: $TRAIN_BASE_REPO"
  echo "Kiwix library API: $KIWIX_LIBRARY_API"
  echo "Kiwix ZIM root: $KIWIX_ROOT_URL"
  echo "Fallback asset base: $ASSET_FALLBACK_BASE_URL"
  echo "Kiwix ZIM list: $KIWIX_ZIM_LIST_FILE"
  echo "Raw docs list: $RAW_DOCS_LIST_FILE"

  download_file "$CHAT_REPO" "$CHAT_MODEL" "$MODELS_DIR"
  download_file "$CHAT_REPO" "$CHAT_MMPROJ" "$MODELS_DIR"
  download_file "$EMBED_REPO" "$EMBED_MODEL" "$MODELS_DIR"
  download_snapshot "$TRAIN_BASE_REPO" "$TRAIN_BASE_DIR"

  for spec in "${RAW_DOC_SPECS[@]}"; do
    download_raw_doc "$spec"
  done

  for spec in "${ZIM_SPECS[@]}"; do
    download_zim "$spec"
  done

  if [[ "$DRY_RUN" != "1" ]]; then
    "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/src/infra/build_dataset_inventory.py" || python3 "$ROOT_DIR/src/infra/build_dataset_inventory.py"
  fi

  echo "Done."
  echo "Runtime assets: $MODELS_DIR"
  echo "Training base model: $TRAIN_BASE_DIR"
  echo "Raw documents: $RAW_DOCS_DIR"
  echo "Kiwix ZIM assets: $ZIMS_DIR"
}

main "$@"
