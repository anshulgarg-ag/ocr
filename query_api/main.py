from fastapi import FastAPI
from query_api.routes import search, graph_search, hybrid

app = FastAPI(title="OCR Pipeline Query API", version="0.1.0")

app.include_router(search.router, tags=["vector-search"])
app.include_router(graph_search.router, prefix="/graph", tags=["graph-search"])
app.include_router(hybrid.router, tags=["hybrid"])


@app.get("/health")
async def health():
    return {"status": "ok"}
