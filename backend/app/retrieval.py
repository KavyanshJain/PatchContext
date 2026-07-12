import json
import pickle
from functools import lru_cache
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer


@lru_cache
def encoder() -> SentenceTransformer:
    return SentenceTransformer(__import__("os").getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))


def tokens(value: str) -> list[str]:
    return value.lower().replace("_", " ").replace("/", " ").split()


def build_index(base: Path, chunks: list[dict[str, Any]]) -> None:
    texts = [chunk["text"] for chunk in chunks]
    vectors = encoder().encode(texts, normalize_embeddings=True, show_progress_bar=False).astype("float32")
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(base / "vectors.faiss"))
    np.save(base / "vectors.npy", vectors)
    (base / "bm25.json").write_text(json.dumps([tokens(text) for text in texts]), encoding="utf-8")


def mmr(query: np.ndarray, vectors: np.ndarray, candidates: list[int], limit: int = 6, diversity: float = 0.7) -> list[int]:
    selected: list[int] = []
    while candidates and len(selected) < limit:
        def score(index: int) -> float:
            relevance = float(np.dot(query, vectors[index]))
            redundancy = max((float(np.dot(vectors[index], vectors[chosen])) for chosen in selected), default=0.0)
            return diversity * relevance - (1 - diversity) * redundancy
        best = max(candidates, key=score)
        selected.append(best)
        candidates.remove(best)
    return selected


def retrieve(base: Path, question: str, limit: int = 6) -> tuple[list[dict[str, Any]], float]:
    chunks = json.loads((base / "chunks.json").read_text(encoding="utf-8"))
    if not chunks:
        return [], 0.0
    vector_index = faiss.read_index(str(base / "vectors.faiss"))
    vectors = np.load(base / "vectors.npy")
    bm25 = BM25Okapi(json.loads((base / "bm25.json").read_text(encoding="utf-8")))
    query = encoder().encode([question], normalize_embeddings=True, show_progress_bar=False).astype("float32")[0]
    dense_scores, dense_ids = vector_index.search(query.reshape(1, -1), min(20, len(chunks)))
    sparse = bm25.get_scores(tokens(question))
    sparse = sparse / max(float(np.max(sparse)), 1.0)
    aggregate: dict[int, float] = {int(index): float(score) for index, score in zip(dense_ids[0], dense_scores[0]) if index >= 0}
    for index in np.argsort(sparse)[-20:]:
        aggregate[int(index)] = aggregate.get(int(index), 0) + float(sparse[index]) * 0.45
    ordered = sorted(aggregate, key=aggregate.get, reverse=True)[:20]
    chosen = mmr(query, vectors, ordered, limit=limit)
    retrieved = [dict(chunks[index], score=round(aggregate[index], 3)) for index in chosen]
    graph_path = base / "graph.pkl"
    if graph_path.exists():
        with graph_path.open("rb") as handle:
            graph = pickle.load(handle)
        known = {item["id"] for item in retrieved}
        by_id = {item["id"]: item for item in chunks}
        for item in list(retrieved):
            if graph.has_node(item["id"]):
                neighbors = list(graph.predecessors(item["id"])) + list(graph.successors(item["id"]))
                for node_id in neighbors[:3]:
                    neighbor = by_id.get(node_id)
                    if neighbor and node_id not in known:
                        retrieved.append(dict(neighbor, score=item["score"], graph_expanded=True))
                        known.add(node_id)
    return retrieved[:12], float(max(dense_scores[0], default=0.0))
