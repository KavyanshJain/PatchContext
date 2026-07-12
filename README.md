# PatchContext

PatchContext answers repository design-history questions with a GraphRAG pipeline over commits, pull requests, issues, and their cross-references. It uses local embeddings and a local NLI check; Groq is only used for final generation.

## Run locally

1. Copy `.env.example` to `.env` and provide `GITHUB_TOKEN`, `GROQ_API_KEY`, and `GROQ_MODEL`.
2. `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`
3. `npm --prefix frontend install`
4. In one terminal: `.venv/bin/uvicorn app.main:app --app-dir backend --reload --port 8000`
5. In another: `npm --prefix frontend run dev`

Open `http://localhost:3000`, submit a public GitHub URL, then wait for its job to complete before asking a question.

## Architecture

- `backend/app/ingestion.py`: persistent in-process job manager, git clone, GitHub REST cache, graph and index creation.
- `backend/app/retrieval.py`: FAISS + BM25 retrieval, MMR, and graph-neighbor expansion.
- `backend/app/guardrails.py`: relevance gate, constrained generation, citation validation, similarity check, and NLI entailment.
- `data/<owner>__<repo>/`: clone, cached GitHub entities, job state, graph, chunks, FAISS index, and BM25 corpus.

## Evaluation

`evaluation/benchmark.json` is a 50-question benchmark template. After ingesting its repository, run `python evaluation/run_ragas.py --repo owner__repo`. RAGAS uses the configured Groq model and may consume its free-tier quota.

## Deployment and cost

Build the Next.js app and serve it from the same EC2 machine as FastAPI (with a reverse proxy such as Caddy). This keeps FAISS/graph files local and avoids a broker or managed vector database. EC2 free eligibility is account-specific and time-limited; Groq free quotas can change. The local embedding/NLI models are free but require memory and disk on first download.
