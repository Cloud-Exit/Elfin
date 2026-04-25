from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.training.train import (
    LoRAConfig,
    TrainConfig,
    build_run_metadata,
    dataset_fingerprint,
    format_example,
    load_config,
    load_dataset_records,
    main,
    write_run_metadata,
)


def _write_config(path: Path, overrides: dict | None = None) -> None:
    config = {
        "base_model": "google/gemma-4-E4B-it",
        "dataset_dir": "./datasets/training/splits",
        "output_dir": "./artifacts/elfin-tune",
        "splits": ["train"],
        "num_train_epochs": 2.0,
        "learning_rate": 0.0002,
        "seed": 7,
        "lora": {"r": 16, "alpha": 32, "dropout": 0.05},
    }
    if overrides:
        config.update(overrides)
    path.write_text(json.dumps(config))


class LoadConfigTests(unittest.TestCase):
    def test_parses_json_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            _write_config(path)
            config = load_config(path)
            self.assertIsInstance(config, TrainConfig)
            self.assertEqual(config.base_model, "google/gemma-4-E4B-it")
            self.assertEqual(config.lora.r, 16)
            self.assertEqual(config.splits, ("train",))

    def test_rejects_missing_required_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(json.dumps({"base_model": "x"}))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_rejects_unknown_top_level_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            _write_config(path, {"s3_bucket": "nope"})
            with self.assertRaises(ValueError):
                load_config(path)

    def test_rejects_unknown_lora_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            _write_config(path, {"lora": {"r": 16, "surprise": True}})
            with self.assertRaises(ValueError):
                load_config(path)

    def test_repo_example_config_loads(self) -> None:
        config = load_config(Path("/workspace/config/training/elfin-gemma4-local.example.json"))
        self.assertEqual(config.base_model, "./data/training/base-model/google-gemma-4-E4B-it")
        self.assertEqual(config.dataset_dir, "./datasets/training/splits")


class DatasetHelperTests(unittest.TestCase):
    def test_load_dataset_records_reads_split_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ds_dir = Path(tmp)
            (ds_dir / "train.jsonl").write_text(
                json.dumps({"id": "a", "messages": []}) + "\n" + json.dumps({"id": "b", "messages": []}) + "\n"
            )
            records = load_dataset_records(ds_dir, ("train",))
            self.assertEqual(len(records), 2)

    def test_load_dataset_records_raises_for_missing_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_dataset_records(Path(tmp), ("train",))

    def test_fingerprint_is_deterministic_and_order_sensitive(self) -> None:
        a = [{"id": "x"}, {"id": "y"}]
        b = [{"id": "x"}, {"id": "y"}]
        c = [{"id": "y"}, {"id": "x"}]
        self.assertEqual(dataset_fingerprint(a), dataset_fingerprint(b))
        self.assertNotEqual(dataset_fingerprint(a), dataset_fingerprint(c))


class FormatExampleTests(unittest.TestCase):
    def test_renders_role_tagged_turns(self) -> None:
        record = {
            "messages": [
                {"role": "system", "content": "You are Elfin."},
                {"role": "user", "content": "Hi."},
                {"role": "assistant", "content": "Hello."},
            ]
        }
        text = format_example(record)
        self.assertIn("<|system|>", text)
        self.assertIn("<|user|>", text)
        self.assertIn("<|assistant|>", text)
        self.assertTrue(text.endswith("<|end|>"))


class RunMetadataTests(unittest.TestCase):
    def test_metadata_captures_config_and_dataset(self) -> None:
        cfg = TrainConfig(
            base_model="google/gemma-4",
            dataset_dir="./datasets/training/splits",
            output_dir="./artifacts",
        )
        metadata = build_run_metadata(
            cfg,
            dataset_hash="deadbeef",
            record_count=42,
            git_revision="abc123",
            started_at=1000.0,
            finished_at=1200.0,
        )
        self.assertEqual(metadata["base_model"], cfg.base_model)
        self.assertEqual(metadata["dataset_record_count"], 42)
        self.assertEqual(metadata["dataset_fingerprint"], "deadbeef")
        self.assertEqual(metadata["git_revision"], "abc123")
        self.assertEqual(metadata["lora"]["r"], LoRAConfig().r)

    def test_write_run_metadata_writes_stable_json(self) -> None:
        cfg = TrainConfig(
            base_model="google/gemma-4",
            dataset_dir="./datasets/training/splits",
            output_dir="./artifacts",
        )
        metadata = build_run_metadata(cfg, "hash", 1, None, 0.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_run_metadata(metadata, Path(tmp))
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded["base_model"], cfg.base_model)


class MainSkipTrainTests(unittest.TestCase):
    def test_skip_train_writes_metadata_without_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            dataset_dir = tmp_path / "splits"
            dataset_dir.mkdir()
            (dataset_dir / "train.jsonl").write_text(
                json.dumps(
                    {
                        "id": "a",
                        "messages": [
                            {"role": "user", "content": "Hi"},
                            {"role": "assistant", "content": "Hello field."},
                        ],
                    }
                )
                + "\n"
            )
            cfg_path = tmp_path / "cfg.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "base_model": "stub",
                        "dataset_dir": str(dataset_dir),
                        "output_dir": str(tmp_path / "out"),
                    }
                )
            )

            code = main(["--config", str(cfg_path), "--skip-train"])
            self.assertEqual(code, 0)
            metadata_path = tmp_path / "out" / "run_metadata.json"
            self.assertTrue(metadata_path.is_file())
            metadata = json.loads(metadata_path.read_text())
            self.assertTrue(metadata["skipped"])
            self.assertEqual(metadata["dataset_record_count"], 1)


if __name__ == "__main__":
    unittest.main()
