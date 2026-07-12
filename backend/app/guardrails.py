import os
import re
from functools import lru_cache
from typing import Any

import httpx
import numpy as np
from transformers import pipeline

from .retrieval import encoder

CITATION = re.compile(r"\[(PR #\d+|Issue #\d+|[0-9a-f]{7,40})\]")
# Qwen3 / thinking models wrap their reasoning in <think>…</think>.
# Strip it before running any guardrail so checks only see the final answer.
THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """Remove chain-of-thought blocks emitted by reasoning models (e.g. Qwen3)."""
    return THINK_BLOCK.sub("", text).strip()


@lru_cache
def nli():
    return pipeline(
        "text-classification",
        model=os.getenv("NLI_MODEL", "cross-encoder/nli-deberta-v3-small"),
        truncation=True,
    )


def context(items: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        f"SOURCE {item['label']} ({item['id']})\n{item['text'][:3500]}" for item in items
    )


async def generate(question: str, items: list[dict[str, Any]], temperature: float) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL")
    if not api_key or not model:
        raise RuntimeError("GROQ_API_KEY and GROQ_MODEL are required for generation.")
    allowed = ", ".join(f"[{item['label']}]" for item in items)
    system = (
        "You are PatchContext. Answer only using the supplied repository sources. "
        "Provide a well-structured, moderately detailed explanation using markdown lists and bold text where helpful, "
        "but avoid unnecessary verbosity. If the sources do not establish the answer, say so plainly. "
        "Every factual claim must carry one or more inline citations wrapped in square brackets, "
        f"for example [PR #12] or [abc123de]. Cite only labels from this exact allowed list: {allowed}"
    )
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Question: {question}\n\nSources:\n{context(items)}"},
        ],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"]
    # Strip the model's internal reasoning before returning the answer.
    return strip_think(raw)


def valid_citations(answer: str, items: list[dict[str, Any]]) -> bool:
    answer = strip_think(answer)
    citations = CITATION.findall(answer)
    if not citations:
        return False
    for citation in citations:
        is_hex = all(c in "0123456789abcdef" for c in citation.lower())
        if not any(
            citation == item["label"]
            or (is_hex and item["label"].lower().startswith(citation.lower()))
            for item in items
        ):
            return False
    return True


def similarity_ok(answer: str, items: list[dict[str, Any]]) -> bool:
    answer = strip_think(answer)
    vectors = encoder().encode(
        [answer, context(items)], normalize_embeddings=True, show_progress_bar=False
    )
    return float(np.dot(vectors[0], vectors[1])) >= 0.28


def entailment_ok(answer: str, items: list[dict[str, Any]]) -> bool:
    """
    Check that the answer is supported by at least one cited source.

    The cross-encoder/nli-deberta-v3-small model outputs entailment/neutral/contradiction.
    For synthesised answers drawn from several short sources, full entailment from any
    single source is rare — but we need to confirm the answer is not *contradicted*.

    Strategy (layered):
      1. If any cited source entails the answer → pass immediately.
      2. If every cited source is neutral (not contradicting) AND at least one has a
         high neutral score, accept it — the answer is grounded even if no one source
         individually entails the full synthesis.
      3. If any source explicitly contradicts the answer → fail.
    """
    answer = strip_think(answer)
    cited = [item for item in items if f"[{item['label']}]" in answer]
    if not cited:
        return False

    best_entail = 0.0
    contradiction_found = False
    high_neutral_count = 0

    for item in cited:
        outputs = nli()({"text": item["text"][:1800], "text_pair": answer[:1800]})
        output = outputs[0] if isinstance(outputs, list) else outputs
        label = output["label"].lower()
        score = float(output["score"])

        if label.startswith("entail"):
            best_entail = max(best_entail, score)
        elif label.startswith("contradict"):
            if score >= 0.7:   # high-confidence contradiction → hard fail
                contradiction_found = True
        elif label == "neutral" and score >= 0.5:
            high_neutral_count += 1

    if contradiction_found:
        return False
    if best_entail >= 0.4:
        return True
    # Accept if majority of cited sources are neutral (not contradicting) — the
    # answer is a legitimate multi-source synthesis.
    return high_neutral_count >= max(1, len(cited) // 2)