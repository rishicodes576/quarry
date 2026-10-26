# Current local measurements

Snapshot: 2026-10-26T14:44:49.591247+00:00. Executable source SHA-256: `ba20aa5db83300c72129c44a07dbf54972067b46c9b8c680b133c2a442dccd84`. The current acceptance checklist and campaign progress are in [RELEASE_STATUS.md](RELEASE_STATUS.md). This dated snapshot is not final release acceptance.

These are finite Docker Desktop experiments on the documented laptop, with warm local ONNX models. They use the frozen authored synthetic corpus, not an independently labeled generalization benchmark. Generation measurements are separate from these no-generation timings. No paid external service was used.

## Retrieval

Measured at 2026-10-26T14:14:19.835004+00:00. Each mode timed 120 cases; source-level quality aggregates cover the 100 relevance-labeled cases. Source-unique top five are formed from 20 passages. Model and corpus hashes and per-case ranks remain in `evaluation/results/latest.json` and `retrieval-all.json`.

| Mode | Recall@5 | MRR | nDCG@5 | ID precision@5 | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| dense | 0.9550 | 0.8675 | 0.8861 | 0.2300 | 23.304 | 27.595 |
| bm25 | 0.9400 | 0.8490 | 0.8704 | 0.2365 | 57.982 | 67.942 |
| hybrid | 0.9800 | 0.8817 | 0.9060 | 0.2360 | 34.125 | 47.926 |
| hybrid_rerank | 0.9900 | 0.9025 | 0.9245 | 0.2380 | 917.605 | 1116.678 |

ID precision/recall do not use an LLM judge and are not Ragas model-judged context quality. Approximate/tied ranks may vary; no test-set tuning or target-score substitution is claimed.

## Extractive execution and capacity

The sequential inline durable graph completed 120/120 cases. Worker P50/P95: 1327.49/1573.98 ms; first durable evidence P50/P95: 1119.96/1384.65 ms. Eight arithmetic tool cases matched the expected tool. This is operational completion, not independently reviewed answer accuracy. It excludes HTTP admission and queueing, and uses no generation tokens.

The load probe used two API replicas, five sample workspaces, ten submission threads and 100 requests per worker configuration. Latency includes server queueing. Measurement workloads ran separately from scans and model judging.

| Workers | Completed | Runs/s | End-to-end P50 ms | End-to-end P95 ms | Queue P50 ms |
|---|---:|---:|---:|---:|---:|
| 1 | 100/100 | 2.053 | 22456.8 | 41264.2 | 22052.0 |
| 2 | 100/100 | 3.523 | 11332.9 | 21784.7 | 10865.5 |
| 4 | 100/100 | 5.137 | 7484.9 | 12253.2 | 6870.3 |

| Workers observed | Snapshots | Sampled max total CPU | Sampled max total RAM GiB |
|---|---:|---:|---:|
| 1 | 21 | 371.0% | 2.30 |
| 2 | 9 | 532.5% | 2.68 |
| 4 | 8 | 724.1% | 3.37 |

CPU 100% represents one logical CPU. Samples include startup/idle intervals and are not instantaneous peaks. Queueing dominates this burst; CPU/memory rise with replicas and throughput is sublinear. Scheduler lock wait, connection-pool wait and reranker CPU profiling would distinguish causes; these observations do not establish sustained Internet capacity or an SLA.

## Recovery and release checks

Fresh isolated startup and persistent stop/start passed in 133.67 seconds with the shared verified model cache. Isolated backup restoration passed in 141.25 seconds, verified 149 source hashes and completed a research query with 1 cited passages. Primary data was preserved. Rehearsal stacks were stopped with volumes retained.

The complete functional gate passed: 224 backend tests, nine Playwright workflows, generated API type/contract checks, BFF probes and parser isolation. Critical aggregate branch coverage is 528/582 = 90.722%; this is not per-file or whole-repository coverage. Full security scanning, all eight runtime images, local OWASP checks and the scoped independent AI code review passed for this source. Known optional evaluator metadata advisories retain exact tested mitigations; see `security/EVALUATOR_MITIGATIONS.md`.

The PostgreSQL scan first failed for CVE-2026-92392 in libcurl 8.22.0-r0. The image now pins 8.23.0-r0 and its fresh scan passed. Failed evidence remains in `evaluation/results/historical`; no suppression was introduced.

The production-mode HTTPS/STARTTLS rehearsal uses a private test CA and local mail sink. Hosted installation requires its own transport/origin configuration and host acceptance. Scanner/reviewer success is finite evidence, not a vulnerability-free claim or human certification. The 37-case historical quality campaign and 148 isolated comparisons are separate acceptance gates and remain unfinished until their actual reports and attributed support reviews are complete.

## Hosted verification

The real [GitHub Actions verification run](https://github.com/rishicodes576/quarry/actions/runs/40337592192) passed startup, 224 backend cases, nine browser workflows and all security/image gates on the same executable fingerprint. It completed with zero GitHub annotations. The initial failure was fixed with targeted non-root report ACLs and a writable temporary Hugging Face/Xet cache. Immutable Node 24 checkout and an explicit Ubuntu 24.04 runner address the deprecation/moving-label annotations. Original failed evidence is preserved. See `evaluation/results/github-ci.json` and `cold-model-bootstrap.json`.
