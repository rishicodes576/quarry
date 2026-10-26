# Current local measurements

Snapshot: 2026-10-26T08:54:21.344372+00:00. Executable source SHA-256: `747ab5d84111e9971cb40c5522a8c5904c960795a4e5b0a7b1cc4c260f724546`. The current acceptance checklist and campaign progress are in [RELEASE_STATUS.md](RELEASE_STATUS.md). This dated snapshot is not final release acceptance.

These are finite Docker Desktop experiments on the documented laptop, with warm local ONNX models. They use the frozen authored synthetic corpus, not an independently labeled generalization benchmark. Generation measurements are separate from these no-generation timings. No paid external service was used.

## Retrieval

Measured at 2026-10-26T08:40:54.651161+00:00. Each mode timed 120 cases; source-level quality aggregates cover the 100 relevance-labeled cases. Source-unique top five are formed from 20 passages. Model and corpus hashes and per-case ranks remain in `evaluation/results/latest.json` and `retrieval-all.json`.

| Mode | Recall@5 | MRR | nDCG@5 | ID precision@5 | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| dense | 0.9550 | 0.8675 | 0.8861 | 0.2300 | 25.141 | 33.205 |
| bm25 | 0.9400 | 0.8490 | 0.8710 | 0.2365 | 57.697 | 65.642 |
| hybrid | 0.9800 | 0.8850 | 0.9083 | 0.2360 | 26.254 | 29.571 |
| hybrid_rerank | 0.9900 | 0.9025 | 0.9245 | 0.2380 | 904.335 | 1148.740 |

ID precision/recall do not use an LLM judge and are not Ragas model-judged context quality. Approximate/tied ranks may vary; no test-set tuning or target-score substitution is claimed.

## Extractive execution and capacity

The sequential inline durable graph completed 120/120 cases. Worker P50/P95: 1328.53/1603.96 ms; first durable evidence P50/P95: 1107.89/1369.32 ms. Eight arithmetic tool cases matched the expected tool. This is operational completion, not independently reviewed answer accuracy. It excludes HTTP admission and queueing, and uses no generation tokens.

The load probe used two API replicas, five sample workspaces, ten submission threads and 100 requests per worker configuration. Latency includes server queueing. Measurement workloads ran separately from scans and model judging.

| Workers | Completed | Runs/s | End-to-end P50 ms | End-to-end P95 ms | Queue P50 ms |
|---|---:|---:|---:|---:|---:|
| 1 | 100/100 | 1.887 | 23888.1 | 45710.8 | 23367.9 |
| 2 | 100/100 | 3.201 | 13788.8 | 23421.2 | 13275.0 |
| 4 | 100/100 | 4.698 | 7794.1 | 12963.6 | 7171.5 |

| Workers observed | Snapshots | Sampled max total CPU | Sampled max total RAM GiB |
|---|---:|---:|---:|
| 1 | 23 | 376.2% | 2.37 |
| 2 | 9 | 536.7% | 2.76 |
| 4 | 8 | 705.1% | 3.45 |

CPU 100% represents one logical CPU. Samples include startup/idle intervals and are not instantaneous peaks. Queueing dominates this burst; CPU/memory rise with replicas and throughput is sublinear. Scheduler lock wait, connection-pool wait and reranker CPU profiling would distinguish causes; these observations do not establish sustained Internet capacity or an SLA.

## Recovery and release checks

Fresh isolated startup and persistent stop/start passed in 137.53 seconds with the shared verified model cache. Isolated backup restoration passed in 142.00 seconds, verified 129 source hashes and completed a research query with 5 cited passages. Primary data was preserved. Rehearsal stacks were stopped with volumes retained.

The complete functional gate passed: 224 backend tests, nine Playwright workflows, generated API type/contract checks, BFF probes and parser isolation. Critical aggregate branch coverage is 528/582 = 90.722%; this is not per-file or whole-repository coverage. Full security scanning, all eight runtime images, local OWASP checks and the scoped independent AI code review passed for this source. Known optional evaluator metadata advisories retain exact tested mitigations; see `security/EVALUATOR_MITIGATIONS.md`.

The PostgreSQL scan first failed for CVE-2026-92392 in libcurl 8.22.0-r0. The image now pins 8.23.0-r0 and its fresh scan passed. Failed evidence remains in `evaluation/results/historical`; no suppression was introduced.

The production-mode HTTPS/STARTTLS rehearsal uses a private test CA and local mail sink. Public deployment, real personal Gmail configuration and native-host acceptance remain owner-dependent. Scanner/reviewer success is finite evidence, not a vulnerability-free claim or human certification. The 37-case historical quality campaign and 148 isolated comparisons are separate acceptance gates and remain unfinished until their actual reports and attributed support reviews are complete.
