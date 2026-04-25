from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.training.export import (
    DIRECT_GGUF_OUTTYPES,
    _convert_to_gguf,
    build_export_metadata,
    compute_artifact_digest,
    export_metadata_only,
    load_run_metadata,
    locate_adapter_dir,
    write_export_metadata,
)


def _make_run_dir(root: Path) -> Path:
    adapter = root / "adapter"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(json.dumps({"peft_type": "LORA"}))
    (root / "run_metadata.json").write_text(
        json.dumps(
            {
                "base_model": "google/gemma-4-E4B-it",
                "dataset_fingerprint": "cafef00d",
                "dataset_record_count": 100,
                "git_revision": "abc123",
            }
        )
    )
    return root


class RunMetadataTests(unittest.TestCase):
    def test_load_run_metadata_reads_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = _make_run_dir(Path(tmp))
            metadata = load_run_metadata(run_dir)
            self.assertEqual(metadata["base_model"], "google/gemma-4-E4B-it")

    def test_load_run_metadata_rejects_missing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "run_metadata.json").write_text(json.dumps({"foo": "bar"}))
            with self.assertRaises(ValueError):
                load_run_metadata(Path(tmp))

    def test_load_run_metadata_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_run_metadata(Path(tmp))


class AdapterDiscoveryTests(unittest.TestCase):
    def test_finds_adapter_under_adapter_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _make_run_dir(Path(tmp))
            self.assertEqual(locate_adapter_dir(run).name, "adapter")

    def test_finds_adapter_in_run_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "adapter_config.json").write_text("{}")
            self.assertEqual(locate_adapter_dir(run), run)

    def test_raises_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                locate_adapter_dir(Path(tmp))


class ExportMetadataTests(unittest.TestCase):
    def test_metadata_shape(self) -> None:
        metadata = build_export_metadata(
            run_metadata={
                "base_model": "google/gemma-4",
                "dataset_fingerprint": "deadbeef",
                "dataset_record_count": 42,
                "git_revision": "abc",
            },
            adapter_dir=Path("./out/adapter"),
            artifact_path=Path("./out/elfin.gguf"),
            artifact_digest="f" * 64,
            quantization="q4_k_m",
            exported_at=123.0,
        )
        self.assertEqual(metadata["base_model"], "google/gemma-4")
        self.assertEqual(metadata["artifact_path"], "out/elfin.gguf")
        self.assertEqual(metadata["artifact_sha256"], "f" * 64)
        self.assertEqual(metadata["quantization"], "q4_k_m")
        self.assertEqual(metadata["dataset_fingerprint"], "deadbeef")

    def test_write_metadata_places_sidecar_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "elfin.gguf"
            artifact.write_bytes(b"fake gguf")
            metadata = build_export_metadata(
                run_metadata={
                    "base_model": "m",
                    "dataset_fingerprint": "hash",
                    "dataset_record_count": 1,
                },
                adapter_dir=Path(tmp),
                artifact_path=artifact,
                artifact_digest="abc",
                quantization="q4_k_m",
                exported_at=0.0,
            )
            out = write_export_metadata(metadata, artifact)
            self.assertTrue(out.is_file())
            self.assertEqual(out.name, "elfin.gguf.metadata.json")

    def test_compute_artifact_digest_matches_hashlib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.bin"
            p.write_bytes(b"elfin")
            import hashlib
            self.assertEqual(
                compute_artifact_digest(p),
                hashlib.sha256(b"elfin").hexdigest(),
            )


class ExportMetadataOnlyTests(unittest.TestCase):
    def test_metadata_only_flow_writes_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = _make_run_dir(Path(tmp))
            artifact = Path(tmp) / "elfin.gguf"
            artifact.write_bytes(b"precooked")
            metadata = export_metadata_only(run, artifact, quantization="q4_k_m")
            sidecar = artifact.with_suffix(artifact.suffix + ".metadata.json")
            self.assertTrue(sidecar.is_file())
            self.assertEqual(metadata["base_model"], "google/gemma-4-E4B-it")
            self.assertEqual(metadata["dataset_fingerprint"], "cafef00d")


class ConvertToGGUFTests(unittest.TestCase):
    def test_direct_outtype_uses_converter_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            merged = root / "merged"
            merged.mkdir()
            converter = root / "convert_hf_to_gguf.py"
            converter.write_text("# stub")
            quantizer = root / "llama-quantize"
            quantizer.write_text("# stub")
            output = root / "model-f16.gguf"

            calls: list[list[str]] = []

            def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess:
                calls.append(cmd)
                output.write_bytes(b"fake gguf")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("src.training.export.subprocess.run", side_effect=fake_run):
                _convert_to_gguf(merged, output, "f16", converter, quantizer)

            self.assertIn("f16", DIRECT_GGUF_OUTTYPES)
            self.assertEqual(len(calls), 1)
            self.assertIn(str(converter), calls[0])
            self.assertIn("--outtype", calls[0])
            self.assertIn("f16", calls[0])

    def test_quantized_outtype_uses_bf16_then_quantizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            merged = root / "merged"
            merged.mkdir()
            converter = root / "convert_hf_to_gguf.py"
            converter.write_text("# stub")
            quantizer = root / "llama-quantize"
            quantizer.write_text("# stub")
            output = root / "model-q4_k_m.gguf"

            calls: list[list[str]] = []

            def fake_run(cmd: list[str], check: bool) -> subprocess.CompletedProcess:
                calls.append(cmd)
                if cmd and cmd[0] == str(quantizer):
                    output.write_bytes(b"quantized gguf")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("src.training.export.subprocess.run", side_effect=fake_run):
                _convert_to_gguf(merged, output, "q4_k_m", converter, quantizer)

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], unittest.mock.ANY)
            self.assertIn(str(converter), calls[0])
            self.assertIn("bf16", calls[0])
            self.assertEqual(calls[1][0], str(quantizer))
            self.assertEqual(calls[1][-1], "Q4_K_M")


if __name__ == "__main__":
    unittest.main()
