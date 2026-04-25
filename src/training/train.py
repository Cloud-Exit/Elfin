"""
Local LoRA/QLoRA entrypoint for Elfin behavior fine-tuning.

Modeled on trainer-example/scripts/run_training.py but stripped of remote shell
orchestration, cloud upload, and cluster assumptions. Runs directly against the
host machine. Training itself is optional at import time: if the transformers +
peft stack is available, run_sft() will drive a real SFT loop; if not, all the
support functions (config loading, dataset hashing, run metadata, adapter dir
layout) still work for validation and testing.

No remote runners, no S3, no cluster code. Single-config surface.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_KEYS: tuple[str, ...] = (
    "base_model",
    "dataset_dir",
    "output_dir",
)


@dataclass
class LoRAConfig:
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: tuple[str, ...] = (
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    )


@dataclass
class TrainConfig:
    base_model: str
    dataset_dir: str
    output_dir: str
    splits: tuple[str, ...] = ("train",)
    max_seq_length: int = 2048
    learning_rate: float = 2e-4
    num_train_epochs: float = 2.0
    per_device_batch_size: int = 2
    gradient_accumulation_steps: int = 8
    warmup_ratio: float = 0.05
    weight_decay: float = 0.0
    seed: int = 7
    lora: LoRAConfig = field(default_factory=LoRAConfig)

    def to_dict(self) -> dict:
        return asdict(self)


def load_config(path: Path) -> TrainConfig:
    text = path.read_text()
    data = _parse_config_text(text, path.suffix)
    missing = [k for k in REQUIRED_CONFIG_KEYS if k not in data]
    if missing:
        raise ValueError(f"config is missing required keys: {missing}")

    lora_data = data.get("lora") or {}
    if not isinstance(lora_data, dict):
        raise ValueError("config 'lora' must be an object")
    allowed_lora = {"r", "alpha", "dropout", "target_modules"}
    bad_lora = [k for k in lora_data if k not in allowed_lora]
    if bad_lora:
        raise ValueError(f"unknown lora keys: {bad_lora}")
    if "target_modules" in lora_data and not isinstance(lora_data["target_modules"], (list, tuple)):
        raise ValueError("lora.target_modules must be a list")
    lora = LoRAConfig(
        r=int(lora_data.get("r", 16)),
        alpha=int(lora_data.get("alpha", 32)),
        dropout=float(lora_data.get("dropout", 0.05)),
        target_modules=tuple(lora_data.get("target_modules", LoRAConfig().target_modules)),
    )

    ignored = set(data) - {
        "base_model",
        "dataset_dir",
        "output_dir",
        "splits",
        "max_seq_length",
        "learning_rate",
        "num_train_epochs",
        "per_device_batch_size",
        "gradient_accumulation_steps",
        "warmup_ratio",
        "weight_decay",
        "seed",
        "lora",
    }
    if ignored:
        raise ValueError(f"unknown config keys: {sorted(ignored)}")

    splits = tuple(data.get("splits") or ("train",))
    if not all(isinstance(s, str) and s for s in splits):
        raise ValueError("splits must be list[str]")

    return TrainConfig(
        base_model=str(data["base_model"]),
        dataset_dir=str(data["dataset_dir"]),
        output_dir=str(data["output_dir"]),
        splits=splits,
        max_seq_length=int(data.get("max_seq_length", 2048)),
        learning_rate=float(data.get("learning_rate", 2e-4)),
        num_train_epochs=float(data.get("num_train_epochs", 2.0)),
        per_device_batch_size=int(data.get("per_device_batch_size", 2)),
        gradient_accumulation_steps=int(data.get("gradient_accumulation_steps", 8)),
        warmup_ratio=float(data.get("warmup_ratio", 0.05)),
        weight_decay=float(data.get("weight_decay", 0.0)),
        seed=int(data.get("seed", 7)),
        lora=lora,
    )


def _parse_config_text(text: str, suffix: str) -> dict:
    suffix = suffix.lower()
    if suffix in {".json"}:
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError("yaml config requires PyYAML; use .json instead") from exc
        return yaml.safe_load(text) or {}
    raise ValueError(f"unsupported config suffix: {suffix}")


def load_dataset_records(dataset_dir: Path, splits: tuple[str, ...]) -> list[dict]:
    records: list[dict] = []
    for split in splits:
        path = dataset_dir / f"{split}.jsonl"
        if not path.is_file():
            raise FileNotFoundError(f"missing split file: {path}")
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if not records:
        raise RuntimeError(f"no training records found in {dataset_dir} for splits {splits}")
    return records


def dataset_fingerprint(records: list[dict]) -> str:
    digest = hashlib.sha256()
    for record in records:
        payload = json.dumps(record, sort_keys=True).encode("utf-8")
        digest.update(payload)
        digest.update(b"\0")
    return digest.hexdigest()


def git_sha(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None
    sha = result.stdout.strip()
    return sha or None


def build_run_metadata(
    config: TrainConfig,
    dataset_hash: str,
    record_count: int,
    git_revision: str | None,
    started_at: float,
    finished_at: float | None = None,
) -> dict:
    metadata = {
        "base_model": config.base_model,
        "dataset_dir": config.dataset_dir,
        "splits": list(config.splits),
        "dataset_record_count": record_count,
        "dataset_fingerprint": dataset_hash,
        "seed": config.seed,
        "learning_rate": config.learning_rate,
        "num_train_epochs": config.num_train_epochs,
        "per_device_batch_size": config.per_device_batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "warmup_ratio": config.warmup_ratio,
        "weight_decay": config.weight_decay,
        "max_seq_length": config.max_seq_length,
        "lora": asdict(config.lora),
        "git_revision": git_revision,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    return metadata


def write_run_metadata(metadata: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "run_metadata.json"
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True))
    return path


def _override_output_dir(config: TrainConfig, output_dir: str) -> TrainConfig:
    data = config.to_dict()
    lora_data = data.pop("lora")
    data["output_dir"] = output_dir
    return TrainConfig(**data, lora=LoRAConfig(**lora_data))


def format_example(record: dict) -> str:
    parts: list[str] = []
    for message in record.get("messages", []):
        role = message.get("role", "user")
        content = message.get("content", "").strip()
        parts.append(f"<|{role}|>\n{content}")
    parts.append("<|end|>")
    return "\n".join(parts)


def run_sft(
    config: TrainConfig,
    records: list[dict],
    output_dir: Path,
) -> dict:
    try:
        import torch  # type: ignore
        from datasets import Dataset  # type: ignore
        from peft import LoraConfig as PeftLoraConfig, get_peft_model  # type: ignore
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments  # type: ignore
        from trl import SFTTrainer  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "local SFT requires transformers + peft + trl + datasets; install them or use --skip-train"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(config.base_model, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        config.base_model,
        torch_dtype=torch.bfloat16,
    )
    peft_config = PeftLoraConfig(
        r=config.lora.r,
        lora_alpha=config.lora.alpha,
        lora_dropout=config.lora.dropout,
        target_modules=list(config.lora.target_modules),
        task_type="CAUSAL_LM",
        bias="none",
    )
    model = get_peft_model(model, peft_config)

    formatted = [{"text": format_example(record)} for record in records]
    dataset = Dataset.from_list(formatted)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=config.per_device_batch_size,
        gradient_accumulation_steps=config.gradient_accumulation_steps,
        num_train_epochs=config.num_train_epochs,
        learning_rate=config.learning_rate,
        warmup_ratio=config.warmup_ratio,
        weight_decay=config.weight_decay,
        seed=config.seed,
        logging_steps=10,
        save_strategy="no",
        report_to=[],
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        args=training_args,
        train_dataset=dataset,
        max_seq_length=config.max_seq_length,
        dataset_text_field="text",
    )
    trainer.train()
    adapter_dir = output_dir / "adapter"
    trainer.model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    return {"adapter_dir": str(adapter_dir)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local LoRA SFT for Elfin")
    parser.add_argument("--config", required=True, help="Path to JSON or YAML training config")
    parser.add_argument("--output-dir", default=None, help="Override config.output_dir")
    parser.add_argument("--skip-train", action="store_true", help="Validate config/dataset only; do not train")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    try:
        config = load_config(config_path)
    except Exception as exc:
        print(f"[error] invalid config {config_path}: {exc}", file=sys.stderr)
        return 2

    if args.output_dir:
        config = _override_output_dir(config, args.output_dir)

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        records = load_dataset_records(Path(config.dataset_dir), config.splits)
    except Exception as exc:
        print(f"[error] could not load dataset: {exc}", file=sys.stderr)
        return 2
    dataset_hash = dataset_fingerprint(records)
    started_at = time.time()
    revision = git_sha(Path(".").resolve())

    if args.skip_train:
        metadata = build_run_metadata(
            config,
            dataset_hash=dataset_hash,
            record_count=len(records),
            git_revision=revision,
            started_at=started_at,
            finished_at=started_at,
        )
        metadata["skipped"] = True
        path = write_run_metadata(metadata, output_dir)
        print(f"[skip-train] wrote {path}")
        return 0

    try:
        result = run_sft(config, records, output_dir)
    except Exception as exc:
        print(f"[error] training failed: {exc}", file=sys.stderr)
        return 1

    finished_at = time.time()
    metadata = build_run_metadata(
        config,
        dataset_hash=dataset_hash,
        record_count=len(records),
        git_revision=revision,
        started_at=started_at,
        finished_at=finished_at,
    )
    metadata["adapter_dir"] = result["adapter_dir"]
    path = write_run_metadata(metadata, output_dir)
    print(f"[train] wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
