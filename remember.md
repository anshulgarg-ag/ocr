# Project Notes & Learnings

## Models Downloaded Locally

All 3 models downloaded to `D:\projects\ocr\models\`:

| Model | Dir | Size |
|-------|-----|------|
| `datalab-to/chandra-ocr-2` | `models/chandra-ocr-2` | 9.9 GB |
| `BAAI/bge-m3` | `models/bge-m3` | 4.3 GB |
| `Qwen/Qwen2.5-7B-Instruct` | `models/Qwen2.5-7B-Instruct` | 19 GB |

**TODO — every new JarvisLabs instance:** upload models before starting services:
```bash
rsync -avz --progress D:/projects/ocr/models/ ubuntu@<NEW_IP>:~/models/
```
The `.env` on JarvisLabs already has `OCR_MODEL`, `EMBED_MODEL`, `GRAPH_MODEL` pointing to `/home/ubuntu/models/...` so services load from disk — no HuggingFace download on startup.

---

## JarvisLabs SSH Gotchas

- SSH user is `ubuntu`, not `user`
- Instance IP changes every time you create a new instance — update `.env` and `config/settings.py`
- When instance is replaced, run `ssh-keygen -R <OLD_IP>` to clear the stale host key
- All SSH must go through **Bash**, not PowerShell (PowerShell here-strings mangle commands)
- `pkill -f <name>` kills the SSH session itself because the pattern matches the session's own command. Fix: write a script file on the remote, then execute it

---

## Model Download Gotchas

- `snapshot_download` from `huggingface_hub` stalls on large safetensor shards — use `curl` instead
- Working curl command (supports resume with `-C -`):
  ```bash
  curl -L -C - -H "Authorization: Bearer $HF_TOKEN" \
      "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/resolve/main/model-00001-of-00004.safetensors" \
      -o model-00001-of-00004.safetensors
  ```
- Run all 4 Qwen shards in parallel (each ~3.5-3.8GB)
- HF_TOKEN is required — without it downloads stall at 0% due to rate limiting

---

## Service Startup Notes

- **Embed server (8002)** — BGE-M3 loads fast, health endpoint confirms ready
- **Chandra OCR (8001)** and **Graph/Qwen (8003)** — take longer, use `until curl -sf http://localhost:800X/health; do sleep 10; done` to wait
- First-run model load from disk: ~2 min. From HuggingFace: ~20 min (if not rate-limited)
- Services launched with: `nohup python3 <service>.py > /tmp/<name>.log 2>&1 &`

---

## Chandra OCR API (real package structure)

```python
from chandra.model import InferenceManager
from chandra.input import load_pdf_images, load_image
from chandra.model.schema import BatchInputItem

manager = InferenceManager(method="hf", model_name_or_path="/home/ubuntu/models/chandra-ocr-2")
images = load_pdf_images("file.pdf", page_range=[])  # PDF → list of PIL Images
batch = [BatchInputItem(image=img) for img in images]
results = manager.generate(batch)
markdown = "\n\n---\n\n".join(r.markdown for r in results if not r.error)
```

---

## Graph Server — vLLM Removed

vLLM causes `AssertionError: duplicate template name` in `torch._inductor` on this CUDA setup.
Graph server uses `transformers.AutoModelForCausalLM` directly instead:
```python
from transformers import AutoModelForCausalLM, AutoTokenizer
model = AutoModelForCausalLM.from_pretrained(path, torch_dtype=torch.float16, device_map="auto")
```
