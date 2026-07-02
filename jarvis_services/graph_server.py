"""
Entity extraction service using Qwen2.5-7B-Instruct via HuggingFace transformers.
(Avoids vLLM to sidestep torch-inductor compatibility issues on this CUDA version.)
"""
import json
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from starlette.responses import Response

MODEL_NAME     = os.environ.get("GRAPH_MODEL", "Qwen/Qwen2.5-7B-Instruct")
CONFIDENCE_MIN = float(os.environ.get("ENTITY_CONFIDENCE_MIN", "0.6"))

_model     = None
_tokenizer = None

extract_requests = Counter("graph_extract_requests_total", "Extraction requests")
extract_entities = Counter("graph_entities_total",         "Entities extracted")
extract_duration = Histogram("graph_extract_duration_seconds", "Extraction latency",
                             buckets=[5, 10, 30, 60, 120, 300])


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _tokenizer
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    _model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    _model.eval()
    print(f"Qwen2.5-7B loaded via transformers")
    yield
    _model = None
    _tokenizer = None


app = FastAPI(title="GraphRAG Entity Extraction", lifespan=lifespan)


class ExtractRequest(BaseModel):
    text: str
    doc_id: str


class ExtractResponse(BaseModel):
    doc_id: str
    entities: list[dict]
    relations: list[dict]
    duration_ms: float


@app.get("/health")
async def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/extract", response_model=ExtractResponse)
async def extract(req: ExtractRequest):
    import asyncio
    t0 = time.monotonic()
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, _extract_sync, req.text, req.doc_id
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    elapsed = (time.monotonic() - t0) * 1000
    extract_requests.inc()
    extract_entities.inc(len(result["entities"]))
    extract_duration.observe(elapsed / 1000)
    return ExtractResponse(duration_ms=round(elapsed, 1), **result)


_PROMPT = """Extract named entities and relationships from the document text below.
Return ONLY a JSON object — no prose, no markdown fences.

Schema:
{
  "entities": [{"name": "string", "type": "PERSON|ORG|PRODUCT|DATE|LOCATION|METRIC|CONCEPT|OTHER", "confidence": 0.0-1.0}],
  "relations": [{"source": "name", "source_type": "type", "target": "name", "target_type": "type", "relation_type": "WORKS_FOR|PART_OF|RELATED_TO|PRODUCES|LOCATED_IN|OTHER", "confidence": 0.0-1.0}]
}

Document:
{text}

JSON:"""


def _extract_sync(text: str, doc_id: str) -> dict:
    import torch
    text_trunc = text[:8000]
    prompt = _PROMPT.format(text=text_trunc)

    inputs = _tokenizer(prompt, return_tensors="pt").to(_model.device)
    with torch.no_grad():
        output_ids = _model.generate(
            **inputs,
            max_new_tokens=2048,
            temperature=0.1,
            do_sample=True,
            pad_token_id=_tokenizer.eos_token_id,
        )
    raw = _tokenizer.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)

    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not json_match:
        return {"doc_id": doc_id, "entities": [], "relations": []}
    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        return {"doc_id": doc_id, "entities": [], "relations": []}

    entities = data.get("entities", [])
    relations = data.get("relations", [])
    sentences = re.split(r"[.!?]\s+", text_trunc)

    # Confidence + appearance filter
    entities = [
        e for e in entities
        if e.get("confidence", 1.0) >= CONFIDENCE_MIN
        and sum(1 for s in sentences if e.get("name", "").lower() in s.lower()) >= 2
    ]
    valid_names = {e["name"] for e in entities}
    relations = [
        r for r in relations
        if r.get("confidence", 1.0) >= CONFIDENCE_MIN
        and r.get("source") in valid_names
        and r.get("target") in valid_names
    ]
    return {"doc_id": doc_id, "entities": entities, "relations": relations}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
