# Quarry — Agentic Engineering Research Platform

Next.js, TypeScript, FastAPI, LangGraph, PostgreSQL, Qdrant, ONNX, Docker

- Built a multi-tenant agentic research platform with document/web/Wikipedia tools, passage-level citations, verified signup, MFA, role-based access and recoverable background jobs using Next.js, FastAPI, LangGraph, PostgreSQL and Qdrant.
- Benchmarked dense, BM25, hybrid fusion and cross-encoder reranking across **480 queries on 120 frozen synthetic engineering cases**; achieved **0.990 Recall@5** and **0.925 nDCG@5** on 100 relevance-labeled cases using local ONNX models.
- Scaled local extractive throughput **2.49× (1.89 → 4.70 runs/s)** behind two API replicas with one/four workers (100 requests per configuration); verified **224 backend tests**, **nine browser workflows** and **90.72% aggregate critical backend branch coverage**.

Evidence: [current local measurements](CURRENT_LOCAL_EVIDENCE.md), [verification](../evaluation/results/verification.json), [scaling](../evaluation/results/scaling.json) and [retrieval records](../evaluation/results/latest.json). These are local measurements, not public capacity or independently human-validated answer accuracy. Keep the synthetic-corpus and extractive-workload qualifiers when shortening the bullets. The original resume remains unchanged.
