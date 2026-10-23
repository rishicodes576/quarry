import threading
import time
from functools import lru_cache
from pathlib import Path

from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import load_only

from quarry.config import settings
from quarry.db import Chunk, Document, session
from quarry.encoders import BM25Encoder, CrossEncoder, DenseEncoder

COLLECTION = "quarry_minilm_v1"
MODES = {"dense", "bm25", "hybrid", "hybrid_rerank"}
_model_lock = threading.Lock()


@lru_cache
def qdrant():
    cfg = settings()
    return QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key or None, timeout=20)


def init_index():
    client = qdrant()
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config={
                "dense": models.VectorParams(
                    size=384,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
    for field in ("workspace_id", "document_id"):
        client.create_payload_index(COLLECTION, field, models.PayloadSchemaType.KEYWORD, wait=True)


@lru_cache
def encoders():
    cfg = settings()
    # Model assets are fetched separately and the cache is read-only at runtime.
    return (
        DenseEncoder(Path(cfg.model_cache) / "dense"),
        BM25Encoder(Path(cfg.model_cache) / "bm25"),
        CrossEncoder(Path(cfg.model_cache) / "reranker"),
    )


def warm_models():
    with _model_lock:
        dense, sparse, reranker = encoders()
        list(dense.embed(["model warmup"]))
        list(sparse.embed(["model warmup"]))
        list(reranker.rerank("warmup", ["model warmup"]))


def index_chunks(workspace_id: str, document_id: str, chunks: list[dict]):
    dense, sparse, _ = encoders()
    for start in range(0, len(chunks), 64):
        batch = chunks[start : start + 64]
        texts = [c["text"] for c in batch]
        with _model_lock:
            vectors = list(dense.embed(texts))
            keywords = list(sparse.embed(texts))
        points = [
            models.PointStruct(
                id=chunk["id"],
                vector={
                    "dense": vector.tolist(),
                    "bm25": models.SparseVector(
                        indices=keyword.indices.tolist(), values=keyword.values.tolist()
                    ),
                },
                payload={"workspace_id": workspace_id, "document_id": document_id},
            )
            for chunk, vector, keyword in zip(batch, vectors, keywords, strict=True)
        ]
        qdrant().upsert(COLLECTION, points, wait=True)


def delete_document(document_id: str):
    qdrant().delete(
        COLLECTION,
        models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchValue(value=document_id)
                    ),
                ]
            )
        ),
        wait=True,
    )


def search(workspace_id: str, query: str, mode: str = "hybrid_rerank", limit: int = 5) -> dict:
    if mode not in MODES:
        raise ValueError("Unknown retrieval mode")
    started = time.perf_counter()
    with session() as db:
        documents = db.scalars(
            select(Document)
            .options(
                load_only(Document.id, Document.title, Document.source_url, Document.content_hash)
            )
            .where(
                Document.workspace_id == workspace_id,
                Document.status == "ready",
                Document.deleted.is_(False),
            )
        ).all()
        by_id = {doc.id: doc for doc in documents}
    if not by_id:
        return {"hits": [], "mode": mode, "latency_ms": 0, "candidate_count": 0}
    dense, sparse, reranker = encoders()
    query_filter = models.Filter(
        must=[
            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
            models.FieldCondition(key="document_id", match=models.MatchAny(any=list(by_id))),
        ]
    )
    with _model_lock:
        vector = list(dense.query_embed(query))[0].tolist() if mode != "bm25" else None
        keyword = list(sparse.query_embed(query))[0] if mode != "dense" else None
    sparse_query = (
        models.SparseVector(
            indices=keyword.indices.tolist(),
            values=keyword.values.tolist(),
        )
        if keyword is not None
        else None
    )
    if mode in {"dense", "bm25"}:
        found = (
            qdrant()
            .query_points(
                COLLECTION,
                query=vector if mode == "dense" else sparse_query,
                using="dense" if mode == "dense" else "bm25",
                query_filter=query_filter,
                limit=40,
                with_payload=True,
            )
            .points
        )
    else:
        found = (
            qdrant()
            .query_points(
                COLLECTION,
                prefetch=[
                    models.Prefetch(query=vector, using="dense", filter=query_filter, limit=40),
                    models.Prefetch(
                        query=sparse_query, using="bm25", filter=query_filter, limit=40
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                query_filter=query_filter,
                limit=40,
                with_payload=True,
            )
            .points
        )
    with session() as db:
        chunks = {
            c.id: c
            for c in db.scalars(
                select(Chunk).where(
                    Chunk.id.in_([str(p.id) for p in found]),
                    Chunk.workspace_id == workspace_id,
                )
            ).all()
        }
        # Recheck publication/deletion after Qdrant responds (deletion may race retrieval).
        active = set(
            db.scalars(
                select(Document.id).where(
                    Document.id.in_(by_id),
                    Document.status == "ready",
                    Document.deleted.is_(False),
                )
            ).all()
        )
    hits = []
    for point in found:
        chunk = chunks.get(str(point.id))
        if not chunk or chunk.document_id not in active:
            continue
        doc = by_id[chunk.document_id]
        hits.append(
            {
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "title": doc.title,
                "text": chunk.text,
                "page": chunk.page,
                "section": chunk.section,
                "source_url": doc.source_url,
                "content_hash": doc.content_hash,
                "score": float(point.score),
                "retrieval_score": float(point.score),
                "kind": "document",
            }
        )
    candidates = len(hits)
    if mode == "hybrid_rerank" and hits:
        with _model_lock:
            scores = list(reranker.rerank(query, [h["text"] for h in hits]))
        for hit, score in zip(hits, scores, strict=True):
            hit["score"] = float(score)
        hits.sort(key=lambda h: h["score"], reverse=True)
    return {
        "hits": hits[:limit],
        "mode": mode,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "candidate_count": candidates,
    }
