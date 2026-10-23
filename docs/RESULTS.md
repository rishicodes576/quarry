# Measured release results

Raw JSON artifacts are in `evaluation/results`. This report describes local Linux amd64 Docker Desktop experiments on an AMD Ryzen 5 7430U (6 cores/12 threads), 15.9 GB host RAM and a 7.18 GiB Docker memory allocation. API and worker limits are 2 CPU cores and 1536 MiB each. No paid service was used.

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

Live free-provider quality status: partial; requested cases: 37; fully judged cases: 1. Stop reason recorded by the evaluator: `InstructorRetryException`. A later network-recovery retry again stopped at a configured quota gate with HTTP 429, one SDK attempt for the rejected call, no provider switch and zero paid calls; see `live-resume.json`. The completed q001 case has context precision approximately 1.000, recall 1.000 and faithfulness 0.7083. The same model family answered and judged. This single case is not a representative benchmark and does not establish the screenshot's targets. See `ANSWER_REVIEW.md`; independent human verdicts remain pending.

The screenshot's approximately 1.10-second full-answer target is not claimed as achieved. Retrieval, extractive graph time, queued HTTP completion, and live generated-answer latency have distinct scopes. The actual free-provider smoke completed in about 6.60 seconds with two calls and 2067 tokens; its factual support remains unverified.

## Verification and security

Functional release status: **passed**. 152 backend tests and eight Playwright workflows passed. Critical aggregate branch coverage: 459/502 = **91.434%** across the explicit modules in `scripts/release.py`; operator/evaluation CLIs are excluded. Source SHA-256: `7e97cdc7effc580ba8abd3fdfb97f50bb0dced6cf91d01021ba5b7d0ac50fe2c`.

Complete security gate: **passed**; source SHA-256 `7e97cdc7effc580ba8abd3fdfb97f50bb0dced6cf91d01021ba5b7d0ac50fe2c`. Semgrep, Trivy filesystem and runtime/development Python audit reports retain their exact scope. Image reports cover all eight runtime image families. ZAP is an unauthenticated local baseline with zero failures/warnings and two reviewed informational categories; it is not a full authenticated penetration test.

Optional evaluator package metadata still reports two distinct advisories (four raw records). The separate evaluator image removes the vulnerable URL/file-loading and pickle-reading capabilities, with checksum-guarded modifications and exploit-negative tests. The raw pip-audit exit code remains 1. See `../security/EVALUATOR_MITIGATIONS.md`; neither package is in the production backend. This is a documented local mitigation, not an upstream fixed-version or vulnerability-free claim.

Backup restoration, killed-worker recovery, tenant isolation, SSRF/redirect/DNS-rebinding checks, cancellation, SSE reconnect and simulated provider failures have distinct evidence in the verification and operational reports. Production HTTPS, external SMTP, off-host disaster recovery, multi-zone failover, payment collection and independent security review remain unexecuted. The supplied production overlay and monetization discussion are deployment/design options, not live-service claims.

## Sampled resource consumption

Thirty-six timestamped Docker snapshots were captured concurrently with the complete load experiment. Values below sum the observed running Quarry services and include startup/idle intervals, grouped by worker count. CPU 100% represents one logical CPU; these are sampled maxima, not instantaneous peaks.

| Workers | Snapshots | Sampled max CPU | Sampled max RAM GiB |
|---|---:|---:|---:|
| 1 | 21 | 353.9% | 1.86 |
| 2 | 8 | 482.9% | 2.22 |
| 4 | 7 | 703.1% | 2.92 |

Queueing dominates the burst timings, and throughput grows less than linearly while CPU demand and memory rise. These observations do not isolate the causal bottleneck; the next profiling experiments are scheduler-lock wait, PostgreSQL pool wait, and reranker CPU service time.

## Startup and restoration

A new isolated Compose project passed clean startup and stop/start readiness in 139.29 seconds using the verified shared model cache. Backup restoration on the final hardened images verified 69 source hashes and completed a new query with five cited passages in 130.48 seconds. Test stacks were stopped with volumes retained; the primary workspace was not restored over.
