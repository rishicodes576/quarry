# Quarry

[![Security and integration](https://github.com/rishicodes576/quarry/actions/workflows/security.yml/badge.svg?branch=main)](https://github.com/rishicodes576/quarry/actions/workflows/security.yml)

An engineering research platform with inspectable citations, reproducible retrieval experiments, and recoverable background processing.

**Next.js · TypeScript · FastAPI · LangGraph · PostgreSQL · Qdrant · ONNX · Docker**

![Research workspace with an inspectable cited answer](docs/assets/02-cited-research.png)

Upload technical documents, ask a question, follow the execution timeline, and inspect the passages supporting an engineering decision brief. Compare retrieval strategies against the same corpus and export the result as Markdown.

## Run locally

Requires Python 3.11+ for the management script, Docker Desktop with Linux containers, and Docker Compose 2.24.4+. Application services, model inference and integration tests run in containers. Allow approximately 7 GiB of Docker memory and 50 GB of free disk for initial builds, model downloads and caches.

```powershell
python scripts/manage.py up
```

Open [localhost:3000](http://localhost:3000) and select **Explore sample workspace**, or register an account. Development verification messages are captured in the local [Mailpit inbox](http://localhost:8025); they are not sent to external email addresses.

No generation key is needed for ingestion, retrieval, calculations, source inspection or clearly labeled extractive answers. To enable generation with your own confirmed Groq Free Plan organization:

```powershell
python scripts/manage.py configure-groq
```

Keys remain in ignored local configuration and are never sent to the browser. The application cannot infer an organization's billing status from a key. Paid adapters are disabled by default; using one requires operator configuration and explicit consent for that run. Quota exhaustion preserves the original provider and evidence and never switches providers automatically.

## What the application does

| Capability | Implementation |
|---|---|
| Document processing | Text-based PDF, Markdown, plain text and public HTML; immutable versions, content hashes, page/section references and visible ingestion progress |
| Retrieval | Local ONNX embeddings, BM25 sparse retrieval, reciprocal-rank fusion and cross-encoder reranking; four inspectable modes |
| Research execution | Bounded LangGraph planning with document search, web search, Wikipedia, public-page fetching and restricted arithmetic |
| Evidence | Passage-level citations, retrieval diagnostics, source inspection, durable execution events and Markdown exports |
| Accounts | Email-verified signup, Argon2id passwords, optional TOTP, single-use recovery codes, revocable sessions and scoped API keys |
| Workspace isolation | Server-enforced owner/editor/viewer permissions on retrieval, uploads, downloads, conversations, SSE and exports |
| Recovery | PostgreSQL leases, heartbeats, fencing tokens, bounded retries, cancellation, checkpoints and visible dead jobs |
| Shared capacity | Transactional admission, per-workspace concurrency, weighted dispatch, storage limits and reserved token budgets |
| Infrastructure | Independent API/worker replicas, PostgreSQL, Qdrant, private SeaweedFS S3 storage, isolated parser, self-hosted search and Prometheus metrics |

Scanned PDFs receive an explicit OCR limitation. Retrieved content is treated as untrusted data. Mechanical citation checks and factual-support review are separate: a valid citation identifier does not prove that every claim is supported.

## Measured local results

These are executed Docker Desktop CPU experiments, with the hardware, conditions, hashes and raw records linked below. The corpus is authored synthetic engineering material; its labels are not independently human validated.

| Measurement | Observed result | Evidence |
|---|---|---|
| Retrieval comparison | Four modes × 120 cases = **480 timed queries** | [Per-case results](evaluation/results/latest.json) |
| Hybrid reranking | **0.990 Recall@5**, **0.925 nDCG@5** on 100 relevance-labeled cases | [Measurement scope](docs/CURRENT_LOCAL_EVIDENCE.md) |
| Worker scaling | **2.05 → 5.14 extractive runs/s**, one → four workers behind two APIs; 100 requests per configuration | [Scaling records](evaluation/results/scaling.json) |
| Functional verification | **224 backend tests**, **9 Playwright workflows** | [Verification report](evaluation/results/verification.json) |
| Critical branch coverage | **90.722% aggregate**, 528/582 branches across explicitly listed critical modules | [Coverage scope](evaluation/results/critical-coverage.json) |
| Recovery | Clean startup, persistent restart, interrupted work and isolated backup restoration exercised | [Acceptance checklist](docs/RELEASE_STATUS.md) |

Throughput is a finite local extractive workload, not public-service capacity or an SLA. Retrieval timing, queued completion, generated-answer latency and first durable evidence have different scopes. See [current local measurements](docs/CURRENT_LOCAL_EVIDENCE.md) and the [measurement method](docs/MEASUREMENTS.md).

### Live-quality evaluation status

The historical live campaign completed **37/37 cases**; its original answers, scores and methodology limitations are retained. A separate frozen campaign now extends the comparison across four retrieval modes using independent research conversations and separate judge requests. The full comparison remains in progress. All twelve currently completed answers and 169 decomposed claims have received attributed assistant review; independent human validation is not claimed. Generated answers and citation fallbacks are recorded separately; partial averages are not a complete four-mode result. Exact per-mode completion counts and evidence remain available in the linked reports and the application's evaluation view.

Inspect the [frozen protocol](docs/EVALUATION_PROTOCOL.md), [arithmetic/provenance audit](evaluation/results/isolated-mathematical-audit.json), [historical audit](evaluation/results/mathematical-audit.json) and [release acceptance checklist](docs/RELEASE_STATUS.md). Reports retain their actual sample counts, model/configuration hashes and measurement scope.

```powershell
python scripts/manage.py benchmark --live --until-complete
```

The free-only campaign preserves checkpoints and waits for quota resets. Local execution requires the host and Docker to remain available.

## Reproduce the checks

```powershell
python scripts/manage.py verify
python scripts/manage.py benchmark
python scripts/manage.py loadtest
python scripts/manage.py restore-test
python scripts/security_scan.py --dynamic --images
```

Keep timed measurements separate from load tests and security scans. The suite covers real PostgreSQL/Qdrant/S3 behavior, migrations, API contract and generated-type drift, browser workflows, parser isolation and critical branch coverage. Security tooling includes Semgrep, Trivy, dependency audits and a local OWASP ZAP baseline. Current local scans and scoped independent AI code review passed; known optional evaluator advisories retain their exact tested mitigations. See the [security report](evaluation/results/security/summary.json), [review scope](docs/INDEPENDENT_SECURITY_REVIEW.md) and [evaluator mitigations](security/EVALUATOR_MITIGATIONS.md).

## Review the design

- [Architecture and design decisions](docs/ARCHITECTURE.md)
- [Five-minute reviewer walkthrough](docs/WALKTHROUGH.md)
- [Scaling, capacity and monetization discussion](docs/INTERVIEW_SYSTEM_DESIGN.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Operations and deployment configuration](docs/OPERATIONS.md)
- [Checkpoint scope and outstanding acceptance](docs/PUBLICATION_CHECKPOINT.md)

The default deployment exposes application ports on loopback and keeps data services private. A hosted installation requires its own HTTPS origin, transport credentials and host acceptance checks. Configuration failures are reported at the relevant setup boundary; local test certificates and captured mail are not evidence of a publicly hosted service.

The repository contains the application, reproducible checks, operational configuration, original sample material and recorded evidence. Final release assembly remains gated by the complete evaluation and support reviews:

```powershell
python scripts/manage.py finalize
```

Dependency licenses and required notices are retained in [THIRD_PARTY.md](THIRD_PARTY.md) and `docs/licenses`.
