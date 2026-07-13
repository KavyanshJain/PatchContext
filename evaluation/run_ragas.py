"""Run RAGAS faithfulness and answer-relevancy evaluation for an indexed repository."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parents[1] / ".env")

from app.guardrails import generate
from app.retrieval import retrieve
from app.storage import repo_dir


async def prepare_rows(repo: str, benchmark: list):
    rows = []
    for item in benchmark:
        sources, _ = retrieve(repo_dir(repo), item["question"])
        if not sources:
            continue
        answer = await generate(item["question"], sources, 0)
        rows.append(
            {
                "question": item["question"],
                "answer": answer,
                "contexts": [source["text"] for source in sources],
            }
        )
    return rows


def run(repo: str) -> None:
    benchmark = json.loads((Path(__file__).parent / "benchmark.json").read_text())
    
    rows = asyncio.run(prepare_rows(repo, benchmark))

    if not rows:
        print("No results to evaluate — is the repository indexed?")
        return

    from datasets import Dataset
    from langchain_openai import ChatOpenAI
    from ragas import evaluate
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy, faithfulness

    # Wire ragas to Groq's OpenAI-compatible endpoint so evaluation stays free.
    groq_llm = ChatOpenAI(
        model=os.environ["GROQ_MODEL"],
        api_key=os.environ["GROQ_API_KEY"],
        base_url="https://api.groq.com/openai/v1",
        temperature=0,
    )
    ragas_llm = LangchainLLMWrapper(groq_llm)
    lc_embeddings = HuggingFaceEmbeddings(
        model_name=os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )
    ragas_embeddings = LangchainEmbeddingsWrapper(lc_embeddings)

    if not rows:
        print("No results to evaluate — is the repository indexed?")
        return

    result = evaluate(
        Dataset.from_list(rows),
        metrics=[faithfulness, answer_relevancy],
        llm=ragas_llm,
        embeddings=ragas_embeddings,
        raise_exceptions=False,
    )
    output = Path(__file__).parent / f"results-{repo}.json"
    output.write_text(json.dumps(result.to_pandas().to_dict(orient="records"), indent=2))
    print(f"Results written to: {output}")
    print(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RAGAS evaluation on an indexed repo.")
    parser.add_argument("--repo", required=True, help="Repo key, e.g. karpathy__micrograd")
    args = parser.parse_args()
    run(args.repo)
