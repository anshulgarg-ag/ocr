"""
Download all JarvisLabs service models to local ./models/ directory.
Run once on your local machine, then rsync/scp the folder to JarvisLabs.

Usage:
    pip install huggingface_hub
    python download_models.py
    # optional: python download_models.py --token hf_xxxx

Disk space required: ~28GB
"""
import argparse
import os
from pathlib import Path

from huggingface_hub import snapshot_download

MODELS = [
    {
        "repo_id": "datalab-to/chandra-ocr-2",
        "local_dir": "models/chandra-ocr-2",
        "description": "Chandra OCR 4B VLM (~10GB)",
    },
    {
        "repo_id": "BAAI/bge-m3",
        "local_dir": "models/bge-m3",
        "description": "BGE-M3 dense+sparse embeddings (~2.3GB)",
    },
    {
        "repo_id": "Qwen/Qwen2.5-7B-Instruct",
        "local_dir": "models/Qwen2.5-7B-Instruct",
        "description": "Qwen2.5 7B entity extraction (~15GB)",
    },
]

# Enable hf_transfer for fast parallel multi-part downloads (critical for large shards)
import os as _os
_os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

BASE_DIR = Path(__file__).parent


def download(token: str | None = None):
    for m in MODELS:
        dest = BASE_DIR / m["local_dir"]
        dest.mkdir(parents=True, exist_ok=True)
        print(f"\n{'='*60}")
        print(f"Downloading: {m['repo_id']}")
        print(f"  {m['description']}")
        print(f"  -> {dest}")
        print(f"{'='*60}")
        snapshot_download(
            repo_id=m["repo_id"],
            local_dir=str(dest),
            token=token,
            ignore_patterns=["*.pt", "original/*"],  # skip redundant pytorch shards if safetensors exist
        )
        print(f"Done: {m['repo_id']}")

    print("\nAll models downloaded.")
    print("Upload to JarvisLabs with:")
    print("  rsync -avz --progress models/ ubuntu@<IP>:~/models/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN"), help="HuggingFace token (or set HF_TOKEN env var)")
    args = parser.parse_args()

    if not args.token:
        print("Warning: no HF_TOKEN set — downloads may be rate-limited.")
        print("Get a free token at https://huggingface.co/settings/tokens\n")

    download(args.token)
