# Elfin Slice 6: Local Fine-Tuning Pipeline

This is the lightweight local fine-tuning path for Elfin.

It is intentionally small:
- local corpus only
- OpenRouter for synthetic dataset generation
- local Python entrypoints
- local LoRA/QLoRA-style training
- local export/eval
- no S3
- no remote shell orchestration

## Layout

- `src/training/dataset_builder.py`
  Builds a local passage manifest from `data/datasets/raw`.
- `src/training/generate_sft_dataset.py`
  Calls OpenRouter to generate synthetic SFT examples from that manifest.
- `src/training/validate_dataset.py`
  Validates schema, duplication, offline-first policy, and deterministic splits.
- `src/training/train.py`
  Runs local LoRA SFT or `--skip-train` config validation.
- `src/training/export.py`
  Merges/export adapters into a deployable GGUF artifact.
- `src/training/eval.py`
  Compares baseline vs tuned eval reports and decides promotion.

## Install Optional Training Deps

```bash
make setup-training
```

This installs `requirements-training.txt` into the local venv.

## Example Config

Use:

```bash
config/training/elfin-gemma4-local.example.json
```

This points at:
- base model: `./data/training/base-model/google-gemma-4-E4B-it`
- dataset splits: `./datasets/training/splits`
- output dir: `./artifacts/training/elfin-gemma4-local`

## Happy Path

1. Build the passage manifest from downloaded documents:

```bash
make finetune-dataset
```

2. Generate synthetic SFT examples from those passages:

```bash
OPENROUTER_API_KEY=<redacted> make finetune-generate
```

3. Validate the dataset and write deterministic splits:

```bash
make finetune-validate
```

4. Smoke-check the train config without running a training job:

```bash
make finetune-smoke
```

5. Run local training:

```bash
make finetune-train
```

6. Export a GGUF artifact:

```bash
make finetune-export
```

7. Compare baseline vs tuned eval reports:

```bash
make finetune-eval
```

## Notes

- `finetune-export` follows the lightweight `trainer-example` flow:
  HF merge -> BF16 GGUF -> `llama-quantize` for `q4_k_m` / similar outputs.
- `finetune-validate` treats unconditional referral language as a dataset policy failure for positive examples.
- Seed examples can live under `datasets/training/seed/`; synthetic examples can live under `datasets/training/synthetic/`.
