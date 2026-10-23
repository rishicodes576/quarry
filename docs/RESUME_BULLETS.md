# Evidence-backed resume options

The original resume is unchanged. Choose two or three bullets for the available space; keep the dataset and workload qualifiers when shortening them.

- Built Quarry, a multi-tenant engineering research platform using Next.js, FastAPI, LangGraph, PostgreSQL, Qdrant and private S3 storage, with verified signup, MFA, role-based access and recoverable fenced background jobs.
- Compared four retrieval strategies across 480 queries on 120 frozen synthetic engineering cases; hybrid reranking achieved 0.987 Recall@5 on 75 relevance-labeled held-out cases, with complete per-case ranks, model hashes and reproducible evaluation artifacts.
- Demonstrated 2.86x local extractive throughput when scaling from one to four workers behind two API replicas (2.23 to 6.38 runs/second; 100 requests per configuration), and verified free-tenant progress during an enterprise backlog.
- Verified 152 backend tests, eight browser workflows and 91.4% aggregate branch coverage across critical backend modules; restored 69 source hashes and completed a cited research query in an isolated backup rehearsal.

Supporting evidence: `RESULTS.md`, `MEASUREMENTS.md`, `AUDIT.md` and the raw JSON under `evaluation/results`. These results do not establish general answer accuracy, a production SLA, independent security certification or a completed 37-case live Ragas benchmark. Avoid the screenshot's 1.000 quality and 1.10-second generated-answer claims: they were comparison targets and were not established as representative Quarry results.
