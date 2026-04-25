"""
Merge a trained LoRA adapter into a deployable artifact for Elfin's local
inference path (llama.cpp / GGUF). Writes a metadata file alongside the
artifact so the deployment step can track base model, adapter commit, and
dataset fingerprint.

Local-only: no S3 upload, no remote push, no cloud registry.

The real merge is optional: if transformers + peft are present, run_merge()
performs the merge; otherwise the support functions (metadata shape, input
validation, adapter discovery) still work for testing and config validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


REQUIRED_ADAPTER_FILES: tuple[str, ...] = ("adapter_config.json",)
REQUIRED_RUN_METADATA_KEYS: tuple[str, ...] = (
    "base_model",
    "dataset_fingerprint",
    "dataset_record_count",
)
DIRECT_GGUF_OUTTYPES: tuple[str, ...] = ("f16", "bf16", "q8_0")


def locate_adapter_dir(run_dir: Path) -> Path:
    candidates = [run_dir / "adapter", run_dir]
    for candidate in candidates:
        if (candidate / "adapter_config.json").is_file():
            return candidate
    raise FileNotFoundError(f"no adapter_config.json found under {run_dir}")


def load_run_metadata(run_dir: Path) -> dict:
    path = run_dir / "run_metadata.json"
    if not path.is_file():
        raise FileNotFoundError(f"run_metadata.json missing under {run_dir}")
    metadata = json.loads(path.read_text())
    missing = [key for key in REQUIRED_RUN_METADATA_KEYS if key not in metadata]
    if missing:
        raise ValueError(f"run_metadata.json missing keys: {missing}")
    return metadata


def compute_artifact_digest(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"artifact not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_export_metadata(
    *,
    run_metadata: dict,
    adapter_dir: Path,
    artifact_path: Path,
    artifact_digest: str,
    quantization: str,
    exported_at: float,
) -> dict:
    return {
        "base_model": run_metadata["base_model"],
        "adapter_dir": str(adapter_dir),
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_digest,
        "quantization": quantization,
        "dataset_fingerprint": run_metadata["dataset_fingerprint"],
        "dataset_record_count": run_metadata.get("dataset_record_count"),
        "git_revision": run_metadata.get("git_revision"),
        "exported_at": exported_at,
    }


def write_export_metadata(metadata: dict, artifact_path: Path) -> Path:
    out_path = artifact_path.with_suffix(artifact_path.suffix + ".metadata.json")
    out_path.write_text(json.dumps(metadata, indent=2, sort_keys=True))
    return out_path


def _merge_with_peft(base_model: str, adapter_dir: Path, merged_dir: Path) -> None:
    try:
        import torch  # type: ignore
        from peft import PeftModel  # type: ignore
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "merge requires transformers + peft; install them or provide a prebuilt artifact"
        ) from exc
    tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(base_model, torch_dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(model, str(adapter_dir))
    merged = model.merge_and_unload()
    merged_dir.mkdir(parents=True, exist_ok=True)
    merged.save_pretrained(str(merged_dir))
    tokenizer.save_pretrained(str(merged_dir))


def _convert_to_gguf(
    merged_dir: Path,
    output_path: Path,
    quantization: str,
    converter: Path,
    quantizer: Path,
) -> None:
    if not converter.is_file():
        raise FileNotFoundError(f"llama.cpp converter not found: {converter}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    quantization = quantization.lower()
    if quantization in DIRECT_GGUF_OUTTYPES:
        cmd = [
            sys.executable,
            str(converter),
            str(merged_dir),
            "--outfile",
            str(output_path),
            "--outtype",
            quantization,
        ]
        subprocess.run(cmd, check=True)
        return

    if not quantizer.is_file():
        raise FileNotFoundError(f"llama.cpp quantizer not found: {quantizer}")

    with tempfile.TemporaryDirectory() as tmp:
        bf16_path = Path(tmp) / "model-bf16.gguf"
        convert_cmd = [
            sys.executable,
            str(converter),
            str(merged_dir),
            "--outfile",
            str(bf16_path),
            "--outtype",
            "bf16",
        ]
        quantize_cmd = [
            str(quantizer),
            str(bf16_path),
            str(output_path),
            quantization.upper(),
        ]
        subprocess.run(convert_cmd, check=True)
        subprocess.run(quantize_cmd, check=True)


def run_merge(
    run_dir: Path,
    output_path: Path,
    *,
    quantization: str,
    converter: Path,
    quantizer: Path,
    keep_merged: bool = False,
) -> dict:
    run_metadata = load_run_metadata(run_dir)
    adapter_dir = locate_adapter_dir(run_dir)
    merged_dir = run_dir / "merged-bf16"
    _merge_with_peft(run_metadata["base_model"], adapter_dir, merged_dir)
    try:
        _convert_to_gguf(merged_dir, output_path, quantization, converter, quantizer)
    finally:
        if not keep_merged and merged_dir.is_dir():
            shutil.rmtree(merged_dir, ignore_errors=True)

    artifact_digest = compute_artifact_digest(output_path)
    metadata = build_export_metadata(
        run_metadata=run_metadata,
        adapter_dir=adapter_dir,
        artifact_path=output_path,
        artifact_digest=artifact_digest,
        quantization=quantization,
        exported_at=time.time(),
    )
    write_export_metadata(metadata, output_path)
    return metadata


def export_metadata_only(
    run_dir: Path,
    artifact_path: Path,
    *,
    quantization: str,
) -> dict:
    """Produce export metadata for an already-built artifact (no merge)."""
    run_metadata = load_run_metadata(run_dir)
    adapter_dir = locate_adapter_dir(run_dir)
    artifact_digest = compute_artifact_digest(artifact_path)
    metadata = build_export_metadata(
        run_metadata=run_metadata,
        adapter_dir=adapter_dir,
        artifact_path=artifact_path,
        artifact_digest=artifact_digest,
        quantization=quantization,
        exported_at=time.time(),
    )
    write_export_metadata(metadata, artifact_path)
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge + export Elfin fine-tune artifact")
    parser.add_argument("--run-dir", required=True, help="Training run output directory")
    parser.add_argument("--output", required=True, help="Path to write the exported artifact (e.g. .gguf)")
    parser.add_argument("--quantization", default="q4_k_m", help="Quantization outtype for GGUF conversion")
    parser.add_argument(
        "--converter",
        default="trainer-example/llama.cpp/convert_hf_to_gguf.py",
        help="Path to llama.cpp converter script",
    )
    parser.add_argument(
        "--quantizer",
        default="trainer-example/llama.cpp/build/bin/llama-quantize",
        help="Path to llama.cpp quantizer binary for q4_k_m/q5_k_m/etc",
    )
    parser.add_argument("--keep-merged", action="store_true")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Skip merge/convert; just produce metadata for an existing artifact",
    )
    args = parser.parse_args(argv)

    run_dir = Path(args.run_dir)
    output_path = Path(args.output)

    try:
        if args.metadata_only:
            metadata = export_metadata_only(run_dir, output_path, quantization=args.quantization)
        else:
            metadata = run_merge(
                run_dir,
                output_path,
                quantization=args.quantization,
                converter=Path(args.converter),
                quantizer=Path(args.quantizer),
                keep_merged=args.keep_merged,
            )
    except Exception as exc:
        print(f"[error] export failed: {exc}", file=sys.stderr)
        return 1

    print(f"exported {metadata['artifact_path']} ({metadata['quantization']}) sha256={metadata['artifact_sha256'][:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
