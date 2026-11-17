"""Measure how well retrieval finds the right passage for a question.

Usage (from the repository root):

    uv run python -m evaluation.eval_retrieval                        # uses EMBEDDING_PROVIDER
    EMBEDDING_PROVIDER=hash uv run python -m evaluation.eval_retrieval  # keyword baseline
    uv run python -m evaluation.eval_retrieval --top-k 2 --chunk-size 300 --verbose

Each question in dataset.json names the document and an exact phrase that answers it.
A retrieved chunk counts as a hit when it comes from that document AND contains the phrase.

Metrics:
- hit@k:  share of questions where a correct chunk is in the top k results.
- MRR:    mean reciprocal rank; 1.0 means the correct chunk was always ranked first,
          0.5 means it was usually second, and so on.

Use it to compare settings: chunk size, overlap, top-k and embedding model. Run it before
and after a change instead of guessing whether retrieval got better.
"""

import argparse
import json
import math
from pathlib import Path

from app.ai.chunking import split_pages
from app.ai.embeddings import embedding_model_name, get_embeddings
from app.ai.text_extraction import PageText
from app.core.config import settings

DATASET = Path(__file__).with_name("dataset.json")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def evaluate(top_k: int, chunk_size: int, chunk_overlap: int, verbose: bool) -> dict:
    data = json.loads(DATASET.read_text())
    embeddings = get_embeddings()

    chunks = []  # (document name, chunk text)
    for document in data["documents"]:
        pieces = split_pages(
            [PageText(page_number=None, text=document["text"])], chunk_size, chunk_overlap
        )
        chunks.extend((document["name"], piece.content) for piece in pieces)
    vectors = embeddings.embed_documents([text for _, text in chunks])

    hits, reciprocal_ranks = 0, []
    for item in data["questions"]:
        query = embeddings.embed_query(item["question"])
        ranked = sorted(
            zip(chunks, vectors), key=lambda pair: cosine(query, pair[1]), reverse=True
        )[:top_k]

        rank = next(
            (
                position
                for position, ((name, text), _) in enumerate(ranked, start=1)
                if name == item["expected_document"] and item["expected_phrase"] in text
            ),
            None,
        )
        hits += rank is not None
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        if verbose:
            mark = f"hit @ {rank}" if rank else "MISS"
            print(f"[{mark:>8}] {item['question']}")

    total = len(data["questions"])
    return {
        "embedding_model": embedding_model_name(),
        "chunks": len(chunks),
        "questions": total,
        f"hit@{top_k}": round(hits / total, 3),
        "mrr": round(sum(reciprocal_ranks) / total, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--top-k", type=int, default=settings.RAG_TOP_K)
    parser.add_argument("--chunk-size", type=int, default=300)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    result = evaluate(args.top_k, args.chunk_size, args.chunk_overlap, args.verbose)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
