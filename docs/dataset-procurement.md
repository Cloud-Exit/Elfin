# Dataset Procurement

## Purpose

Slice 2 seeds offline source material for Elfin:
- raw PDFs in `datasets/raw/` for RAG ingestion
- ZIM archives in `datasets/zim/` for Kiwix encyclopedia verification

## Command

```bash
HF_CLI_BIN=hf make download-assets
```

This downloads:
- runtime GGUF files into `data/models/`
- fine-tune base model snapshot into `data/training/base-model/`
- raw survival/medical/preparedness PDFs into `datasets/raw/`
- Kiwix ZIM archives into `datasets/zim/`

## Source Catalogs

- Raw documents: [config/raw-docs.tsv](/workspace/config/raw-docs.tsv)
- Kiwix ZIMs: [config/kiwix-zims.txt](/workspace/config/kiwix-zims.txt)

## Inventory

Build local inventory after downloads:

```bash
make dataset-inventory
```

This writes:
- [data/datasets/inventory.json](/workspace/data/datasets/inventory.json)
- [data/datasets/inventory.md](/workspace/data/datasets/inventory.md)

## Air-Gapped Seed Flow

1. Run `make download-assets` on connected seed machine.
2. Verify local inventory with `make dataset-inventory`.
3. Copy these directories to target media:
   - `data/models/`
   - `data/training/base-model/`
   - `datasets/raw/`
   - `datasets/zim/`
4. On target device, run:
   - `make verify-slice1-assets`
   - `make ingest-validate`
   - `make dataset-inventory`

## Notes

- ZIM downloads are large. Ensure free disk before download.
- `wikipedia_en_all|nopic` and `stackoverflow.com_en_all` are especially large.
- Some Hugging Face model downloads may require authenticated access and accepted license terms.
