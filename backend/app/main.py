from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import data_root
from .guardrails import entailment_ok, generate, similarity_ok, strip_think, valid_citations
from .ingestion import JobManager, parse_url
from .retrieval import retrieve
from .schemas import Citation, IngestRequest, JobResponse, QueryRequest, QueryResponse, RepoResponse
from .storage import list_repos, read_json, repo_dir, write_json

jobs = JobManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    # Reset any jobs that were left mid-run when the process was last killed.
    for job_path in root.glob("*/job.json"):
        state = read_json(job_path)
        if state and state.get("status") in ("running", "queued", "paused"):
            state["status"] = "failed"
            state["detail"] = "Server restarted while job was in progress."
            write_json(job_path, state)
    yield


app = FastAPI(title="PatchContext", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[__import__("os").getenv("FRONTEND_ORIGIN", "http://localhost:3000")], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/repos/ingest", response_model=JobResponse)
async def ingest(request: IngestRequest):
    try:
        parse_url(str(request.url))
        return await jobs.submit(str(request.url), request.depth, request.max_items)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/repos", response_model=list[RepoResponse])
def repos():
    return list_repos()


@app.get("/repos/{key}/status", response_model=JobResponse)
def status(key: str):
    state = jobs.status(key)
    if not state:
        raise HTTPException(404, "Repository has not been submitted.")
    return state


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    base = repo_dir(request.repo_key)
    if not (base / "vectors.faiss").exists():
        raise HTTPException(409, "Repository is not indexed yet.")
    sources, confidence = retrieve(base, request.question)
    if confidence < 0.30 or not sources:
        return QueryResponse(answer="I can’t find enough relevant repository evidence to answer that question.", refused=True, reason="retrieval_confidence")
    try:
        answer = await generate(request.question, sources, request.temperature)
    except Exception as exc:
        raise HTTPException(502, f"Generation failed: {exc}") from exc
    if not valid_citations(answer, sources):
        return QueryResponse(answer="I can’t verify the generated citations against this repository’s retrieved evidence.", refused=True, reason="citation_check")
    if not similarity_ok(answer, sources):
        return QueryResponse(answer="I can’t verify that answer is sufficiently grounded in the retrieved evidence.", refused=True, reason="similarity_check")
    if not entailment_ok(answer, sources):
        return QueryResponse(answer="I can’t verify that the cited repository sources entail that answer.", refused=True, reason="nli_check")
    clean = strip_think(answer)
    citations = [Citation(id=item["id"], label=item["label"], url=item["url"], kind=item["kind"]) for item in sources if f"[{item['label']}]" in clean]
    return QueryResponse(answer=clean, citations=citations)
