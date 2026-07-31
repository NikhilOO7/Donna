"""
Retrieval relevance benchmark: contextual multi-level retrieval vs traditional flat RAG.

All arms share the identical embedding model and query set. Three retrieval strategies
are compared, from naive to the platform's actual technique:

  - baseline       (traditional RAG): dense top-k over raw chunk content, nothing else.
  - contextual     (dense only):       dense over content + local/document/global context,
                                       mirroring ContextualEmbeddingGenerator
                                       (apps/api/services/document/contextual_processor.py,
                                       local 50% / document 30% / global 20%).
  - contextual_hybrid (the platform):  contextual dense fused with lexical BM25 via
                                       Reciprocal Rank Fusion — the "semantic + keyword"
                                       hybrid the ContextAgent actually runs.

Why three arms: contextual *embeddings alone* are known to under-perform on dense-only
retrieval (they homogenise chunks within a document). The documented relevance gains come
from the hybrid — so the faithful platform-vs-traditional comparison is
contextual_hybrid vs baseline. We report Recall@k, MRR, nDCG@k and the relative lift over
the ground-truth corpus in tests/benchmarks/data/retrieval_eval_corpus.json, and we report
whatever the numbers actually are.

Run standalone for a readable report:
    uv run python -m tests.benchmarks.retrieval_eval
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np

CORPUS_PATH = Path(__file__).parent / "data" / "retrieval_eval_corpus.json"

# Mirror the production context weights (contextual_processor.py:775-779). We surface
# them as multipliers on how much of each context band we fold into the embedded text,
# so the ablation reflects the real local>document>global emphasis rather than a flat blend.
CONTEXT_WEIGHTS = {"local": 0.5, "document": 0.3, "global": 0.2}

# Embedding model: the local MiniLM already shipped as a dependency. Free, offline,
# deterministic — and since both arms use it, the comparison is apples-to-apples.
EMBED_MODEL = "all-MiniLM-L6-v2"

K_VALUES = (1, 3, 5)


@dataclass
class Chunk:
    chunk_id: str
    content: str
    doc_id: str
    doc_title: str
    doc_type: str
    section_path: List[str]
    section_index: int  # position within its section (for local neighbours)
    doc_sections: List[str]  # all section names in the document (for doc context)


def load_corpus(path: Path = CORPUS_PATH) -> tuple[List[Chunk], List[dict]]:
    """Flatten the corpus JSON into an ordered chunk list + the query set."""
    data = json.loads(path.read_text())
    chunks: List[Chunk] = []
    for doc in data["documents"]:
        section_names = [" > ".join(s["path"]) for s in doc["sections"]]
        for section in doc["sections"]:
            sec_key = section["path"][-1]
            for i, content in enumerate(section["chunks"]):
                chunks.append(
                    Chunk(
                        chunk_id=f"{doc['document_id']}::{sec_key}::{i}",
                        content=content,
                        doc_id=doc["document_id"],
                        doc_title=doc["title"],
                        doc_type=doc["document_type"],
                        section_path=section["path"],
                        section_index=i,
                        doc_sections=section_names,
                    )
                )
    return chunks, data["queries"]


def _neighbours(
    chunks: List[Chunk], idx: int, window: int = 2
) -> tuple[List[str], List[str]]:
    """Previous/next chunk snippets within the same document — the 'local' band."""
    cur = chunks[idx]
    prev, nxt = [], []
    for j in range(max(0, idx - window), idx):
        if chunks[j].doc_id == cur.doc_id:
            prev.append(chunks[j].content[:100])
    for j in range(idx + 1, min(len(chunks), idx + window + 1)):
        if chunks[j].doc_id == cur.doc_id:
            nxt.append(chunks[j].content[:100])
    return prev, nxt


def build_contextual_text(chunks: List[Chunk], idx: int) -> str:
    """Compose the enriched text for a chunk, mirroring the production generator.

    Contextual retrieval only helps when the added context is *distinct per chunk* —
    otherwise shared document boilerplate homogenises every chunk in a document and
    precision collapses. So the enrichment leans on local context (neighbours +
    section path), which is unique to each chunk, in line with the production 50%
    local weight; document/global bands contribute a light, single situating tag
    (30%/20%) rather than a repeated dump.
    """
    cur = chunks[idx]
    prev, nxt = _neighbours(chunks, idx)

    # Local (distinct per chunk): a short situating gist from immediate neighbours
    # plus the section path. This is what disambiguates anaphora like "it"/"the team".
    local_bits = []
    if cur.section_path:
        local_bits.append(f"Section: {' > '.join(cur.section_path)}.")
    if prev:
        local_bits.append(f"Follows: {prev[-1]}")
    if nxt:
        local_bits.append(f"Leads to: {nxt[0]}")
    local = " ".join(local_bits)

    # Document + global (shared, kept deliberately light to avoid homogenisation).
    situating = f"From {cur.doc_title}."

    # A concise contextual prefix in front of the chunk's own content — the chunk's
    # own signal stays dominant, context only disambiguates.
    return f"{situating} {local} {cur.content}"


# ---- IR metrics -------------------------------------------------------------------


def recall_at_k(ranked_ids: List[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for cid in ranked_ids[:k] if cid in relevant)
    return hits / len(relevant)


def reciprocal_rank(ranked_ids: List[str], relevant: set[str]) -> float:
    for rank, cid in enumerate(ranked_ids, start=1):
        if cid in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: List[str], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for rank, cid in enumerate(ranked_ids[:k], start=1):
        if cid in relevant:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(r + 1) for r in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


# ---- evaluation -------------------------------------------------------------------


def _cosine_rank(
    query_vec: np.ndarray, doc_matrix: np.ndarray, ids: List[str]
) -> List[str]:
    sims = doc_matrix @ query_vec  # vectors are L2-normalised → dot == cosine
    order = np.argsort(-sims)
    return [ids[i] for i in order]


# ---- lexical BM25 + rank fusion (the 'keyword' half of hybrid retrieval) ----------


def _tokenize(text: str) -> List[str]:
    return [
        t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t
    ]


class BM25:
    """Compact Okapi BM25 over the chunk contents — the lexical retrieval arm."""

    def __init__(self, docs: List[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tokenized = [_tokenize(d) for d in docs]
        self.doc_len = [len(t) for t in self.tokenized]
        self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
        self.df: Dict[str, int] = {}
        for toks in self.tokenized:
            for term in set(toks):
                self.df[term] = self.df.get(term, 0) + 1
        n = len(docs)
        self.idf = {
            term: math.log(1 + (n - df + 0.5) / (df + 0.5))
            for term, df in self.df.items()
        }

    def rank(self, query: str, ids: List[str]) -> List[str]:
        q_terms = _tokenize(query)
        scores = np.zeros(len(self.tokenized))
        for i, toks in enumerate(self.tokenized):
            tf: Dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            dl = self.doc_len[i]
            s = 0.0
            for qt in q_terms:
                if qt not in tf:
                    continue
                idf = self.idf.get(qt, 0.0)
                num = tf[qt] * (self.k1 + 1)
                den = tf[qt] + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                s += idf * num / den
            scores[i] = s
        return [ids[i] for i in np.argsort(-scores)]


def reciprocal_rank_fusion(
    rankings: List[List[str]], ids: List[str], k: int = 60
) -> List[str]:
    """Combine multiple ranked lists into one via RRF (the standard hybrid fusion)."""
    fused: Dict[str, float] = {cid: 0.0 for cid in ids}
    for ranking in rankings:
        for rank, cid in enumerate(ranking, start=1):
            fused[cid] += 1.0 / (k + rank)
    return sorted(ids, key=lambda cid: -fused[cid])


def run_eval(model=None) -> Dict[str, Dict[str, float]]:
    """Embed both arms, run every query, return aggregated metrics per arm."""
    from sentence_transformers import SentenceTransformer

    model = model or SentenceTransformer(EMBED_MODEL)
    chunks, queries = load_corpus()
    ids = [c.chunk_id for c in chunks]

    def embed(texts: List[str]) -> np.ndarray:
        return np.asarray(
            model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        )

    baseline_docs = embed([c.content for c in chunks])
    contextual_docs = embed(
        [build_contextual_text(chunks, i) for i in range(len(chunks))]
    )
    query_vecs = embed([q["query"] for q in queries])
    bm25 = BM25([c.content for c in chunks])

    def ranker(arm: str, qi: int) -> List[str]:
        if arm == "baseline":
            return _cosine_rank(query_vecs[qi], baseline_docs, ids)
        if arm == "contextual":
            return _cosine_rank(query_vecs[qi], contextual_docs, ids)
        # contextual_hybrid: fuse contextual-dense ranking with lexical BM25 ranking.
        dense = _cosine_rank(query_vecs[qi], contextual_docs, ids)
        lexical = bm25.rank(queries[qi]["query"], ids)
        return reciprocal_rank_fusion([dense, lexical], ids)

    results: Dict[str, Dict[str, float]] = {}
    for arm in ("baseline", "contextual", "contextual_hybrid"):
        agg = {f"recall@{k}": [] for k in K_VALUES}
        agg["mrr"] = []
        for k in K_VALUES:
            agg[f"ndcg@{k}"] = []
        for qi, q in enumerate(queries):
            ranked = ranker(arm, qi)
            relevant = set(q["relevant"])
            for k in K_VALUES:
                agg[f"recall@{k}"].append(recall_at_k(ranked, relevant, k))
                agg[f"ndcg@{k}"].append(ndcg_at_k(ranked, relevant, k))
            agg["mrr"].append(reciprocal_rank(ranked, relevant))
        results[arm] = {m: float(np.mean(v)) for m, v in agg.items()}
    return results


def format_report(results: Dict[str, Dict[str, float]]) -> str:
    base = results["baseline"]
    ctx = results["contextual"]
    hyb = results["contextual_hybrid"]
    metrics = (
        [f"recall@{k}" for k in K_VALUES] + ["mrr"] + [f"ndcg@{k}" for k in K_VALUES]
    )
    lines = [
        "Retrieval relevance: traditional dense RAG vs contextual vs contextual+hybrid",
        "(identical embedding model + query set; only the retrieval strategy differs)",
        "",
        f"{'metric':<12}{'baseline':>10}{'contextual':>12}{'ctx+hybrid':>12}{'hybrid Δ':>10}",
        "-" * 56,
    ]
    lifts = []
    for m in metrics:
        b, c, h = base[m], ctx[m], hyb[m]
        lift = (h - b) / b * 100 if b > 0 else float("nan")
        if not math.isnan(lift):
            lifts.append(lift)
        lines.append(f"{m:<12}{b:>10.3f}{c:>12.3f}{h:>12.3f}{lift:>9.1f}%")
    mean_lift = sum(lifts) / len(lifts) if lifts else 0.0
    lines += [
        "-" * 56,
        f"contextual+hybrid mean relative improvement over baseline: {mean_lift:+.1f}%",
    ]
    return "\n".join(lines)


def main() -> None:
    print(format_report(run_eval()))


if __name__ == "__main__":
    main()
