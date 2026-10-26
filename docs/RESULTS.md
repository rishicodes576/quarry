Current rerun: see [CURRENT_LOCAL_EVIDENCE.md](CURRENT_LOCAL_EVIDENCE.md) for the latest dated local measurement snapshot; older tables below retain their historical scope.

# Measured release results

> Historical checkpoint: this page retains its dated measurement snapshot. The current acceptance status is in [RELEASE_STATUS.md](RELEASE_STATUS.md); the isolated four-mode protocol is in [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md). A successful historical gate does not satisfy the new 148-case release criteria.

Raw JSON artifacts are in `evaluation/results`. This report describes local Linux amd64 Docker Desktop experiments on an AMD Ryzen 5 7430U (6 cores/12 threads), 15.9 GB host RAM and a 7.18 GiB Docker memory allocation. API and worker limits are 2 CPU cores and 1536 MiB each. No paid service was used.

The performance tables below retain their dated local experiment artifacts; timing was not repeated during this final security pass. Current-source release checks are reported separately.

## Retrieval

Run: 2026-10-22T12:26:04.753522+00:00. Frozen, authored synthetic corpus: 24 sources and 120 cases; 30 development and 90 held-out test. 100 cases have relevance labels; all 120 are timed per mode. Warm CPU models, uncached sequential queries, source-unique top five from 20 passages. Labels are not independently validated.

| Mode | Recall@5 | MRR | nDCG@5 | ID precision | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| dense | 0.9550 | 0.8675 | 0.8861 | 0.2300 | 24.7 | 31.3 |
| bm25 | 0.9400 | 0.8540 | 0.8733 | 0.2365 | 57.7 | 61.5 |
| hybrid | 0.9800 | 0.8800 | 0.9055 | 0.2360 | 26.0 | 32.8 |
| hybrid_rerank | 0.9900 | 0.9025 | 0.9245 | 0.2380 | 860.6 | 1062.6 |

Held-out test subset, reported separately from the combined table:

| Mode | Relevant cases | Timed cases | Recall@5 | MRR | nDCG@5 |
|---|---:|---:|---:|---:|---:|
| dense | 75 | 90 | 0.9467 | 0.8489 | 0.8724 |
| bm25 | 75 | 90 | 0.9600 | 0.8553 | 0.8808 |
| hybrid | 75 | 90 | 0.9733 | 0.8500 | 0.8815 |
| hybrid_rerank | 75 | 90 | 0.9867 | 0.8856 | 0.9110 |

Ragas ID-based precision/recall uses source IDs without a judge. These values are not model-judged context precision/recall. Tied sparse scores and approximate search can change some ranks between runs. No threshold was selected against the test split.

## Agent and capacity

The durable extractive graph completed 120/120 cases, with worker P50/P95 1219.9/1447.8 ms and first durable evidence P50/P95 1031.1/1237.6 ms. This sequential inline-worker measurement excludes HTTP admission and queue wait. Arithmetic tool selection: 8 labeled cases, 100% correct. No generation calls or tokens. Operational completion and citation identifier validity do not establish semantic correctness.

Two API replicas; five isolated workspaces; 100 requests per configuration; ten submission threads. Completion latency uses server run-creation-to-finish timestamps, including queueing, excluding ingress and browser/SSE delivery. Local extractive generation only. Measurements run separately from verification and image scans.

| Workers | Completed | Throughput runs/s | End-to-end P50 ms | End-to-end P95 ms | Queue P50 ms |
|---|---:|---:|---:|---:|---:|
| 1 | 100/100 | 2.231 | 20493 | 38065 | 20080 |
| 2 | 100/100 | 4.016 | 10674 | 19571 | 10233 |
| 4 | 100/100 | 6.383 | 5683 | 10125 | 5090 |

Live fairness probe: 25/25 completed on one worker. Free work began before the enterprise backlog drained: True. Queue P95: enterprise 9008 ms; free 9320 ms. This demonstrates finite progress for this burst, not a latency SLA or measured weighted CPU-time allocation.

This is a finite laptop burst, not sustained internet capacity. Queueing dominates burst latency. Model memory grows per worker; shared CPU, the serialized scheduler transaction and PostgreSQL connections bound further scaling. Container resource snapshots are in each load artifact; they are snapshots, not peak-memory measurements.

## Quality limits

Live free-provider quality status: **quota_wait**; requested cases: 37; fully judged cases: **35**. This is an incomplete checkpoint, not a representative complete benchmark. Mean context precision / context recall / faithfulness over the 35 completed cases: **0.852857 / 0.862857 / 0.842901**. The same model family answered and judged; human factual-support review remains separate. Raw responses, passages and original metric configurations are preserved in `live-ragas.json`; q001 faithfulness remains 0.7083 and its support limitations remain in `ANSWER_REVIEW.md`.

Judge RPC outputs are persisted by prompt/model/configuration hash and reused on resume. New metrics record model/provider and judge run IDs. Legacy records retain their original configuration history. A changed model/provider or frozen dataset is rejected rather than silently mixed. Temporary provider limits receive bounded same-provider retries; local daily limits pause until UTC reset. `python scripts/manage.py benchmark --live --until-complete` starts an explicit background campaign with at most 64 resumes. Non-quota failures stop for inspection. No paid service or automatic provider switch is used.

The screenshot's approximately 1.10-second full-answer target is not claimed as achieved. Retrieval, extractive graph time, queued HTTP completion, and live generated-answer latency have distinct scopes. The free-provider smoke completed in about 6.60 seconds with two calls and 2067 tokens; mechanical citation validity does not establish factual correctness.

## Verification and security

Functional release status: **passed**. **193 backend tests**, eight Playwright workflows, and the BFF deadline/SSE component probe passed. Critical aggregate branch coverage: **504/556 = 90.647%**, including the new parser service and bounded child entry point. Operator/evaluation CLIs are excluded from this aggregate; whole-repository coverage is lower. Source SHA-256: `82956962a7257027ac4bcc7387356be3fe2cf9f7b0443d17cd8eb9197f675bba`.

Complete security gate: **passed** for that same source. Semgrep, Trivy filesystem, runtime/development dependency audits, all eight runtime image families and the unauthenticated local OWASP ZAP baseline retain their raw evidence. The source scanner includes new/uncommitted files. Scanner coverage is finite.

Optional evaluator package metadata still reports two distinct advisories (four raw records). The separate evaluator image removes vulnerable URL/file-loading and pickle-reading capabilities through checksum-guarded local patches and exploit-negative checks. Raw pip-audit exit 1 remains visible. See `../security/EVALUATOR_MITIGATIONS.md`; these dependencies are absent from the production backend. This is a documented mitigation, not an upstream fix or a vulnerability-free claim.

The separate independent AI reviewer recorded five initial findings, inspected their fixes and additional metadata caps, ran component probes and inspected live parser isolation. See `INDEPENDENT_SECURITY_REVIEW.md`. It was not a human audit/certification. The local production-mode HTTPS/STARTTLS signup rehearsal passed; its private test CA and local SMTP sink do not substantiate Internet delivery or public ACME issuance. ARM64 emulation ran real local embedding/reranking inference and the Qdrant executable; the complete stack has not been validated on a native Oracle host. Public deployment and Gmail configuration are explicitly deferred; see `DEPLOYMENT_LATER.md`. Multi-zone failover, off-host disaster recovery, payment collection and independent human factual-support review are not claimed.

## Sampled resource consumption

Thirty-six timestamped Docker snapshots were captured concurrently with the complete load experiment. Values below sum the observed running Quarry services and include startup/idle intervals, grouped by worker count. CPU 100% represents one logical CPU; these are sampled maxima, not instantaneous peaks.

| Workers | Snapshots | Sampled max CPU | Sampled max RAM GiB |
|---|---:|---:|---:|
| 1 | 21 | 353.9% | 1.86 |
| 2 | 8 | 482.9% | 2.22 |
| 4 | 7 | 703.1% | 2.92 |

Queueing dominates the burst timings, and throughput grows less than linearly while CPU demand and memory rise. These observations do not isolate the causal bottleneck; the next profiling experiments are scheduler-lock wait, PostgreSQL pool wait, and reranker CPU service time.

## Startup and restoration

A fresh isolated Compose project passed startup and stop/start readiness in 132.65 seconds using the shared verified model cache. A PostgreSQL marker persisted across restart. The most recent recorded backup restoration verified 89 source hashes and completed a query with 5 cited passages in 128.39 seconds. Rehearsal stacks were stopped with volumes retained; primary data was untouched.

## Free campaign continuation

The repository defaults remain 100,000 daily campaign/shared tokens and 60-second judge spacing. For this operator-run campaign, the ignored local configuration explicitly selects 200,000 daily tokens and 15-second ordinary spacing. Each provider 429 still receives at least 60 seconds or its longer retry hint; retries are bounded. Ordinary workspace allowances remain 30,000 tokens. The fixed model, dataset, prompt and Ragas scoring method are unchanged. Conservative reservations, including ambiguous-call charges, remain enforced. Changes are recorded in `campaign-budget-change.json`. Published Free Plan allowances are organization-specific and a key cannot prove billing status: [Groq limits](https://console.groq.com/docs/rate-limits). No plan was upgraded and no paid provider was enabled.


## Final arithmetic verification — 25 October 2026

The independent saved-measurement audit passed for 35/37 live cases at this snapshot, all 480 unique retrieval rows (and the saved development/latest artifacts), 120 agent cases, and one/two/four-worker throughput ratios. It recomputed **86** live metric values from exported binary judge verdicts; **19** recorded values lack original RPC identifiers and remain explicitly listed rather than receiving invented provenance. This validates arithmetic, not the correctness of model judgments or authored labels. All eight frozen calculator expressions also matched independently specified exact decimal answers. See `mathematical-audit.json`, `judge-verdicts.json` and `arithmetic-validation.json`. No extra provider call was made by these checks.
