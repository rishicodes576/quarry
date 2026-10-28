# Current local measurements

Snapshot: 2026-10-28T13:44:33.401177+00:00. Current executable source SHA-256: `81d2eaabc9fbb66ef1db25f409497dc4ec7a061b11dd28e948946830370ae453`. See [the acceptance checklist](RELEASE_STATUS.md); this is an audited local checkpoint, not final 148-case or public-host acceptance.

These are finite Docker Desktop CPU experiments. The authored synthetic corpus is not an independently human-labeled generalization benchmark. No paid external service was used. Raw reports retain hardware, configuration, model/corpus hashes, dates and sample counts.

## Retrieval and inline graph snapshot

The retained retrieval experiment was measured at 2026-10-26T14:14:19.835004+00:00. Retrieval, encoder, scorer and frozen corpus bindings are unchanged by the gateway/storage/security-gate fixes. These 480 queries were not rerun in the security check. Each mode timed 120 cases; source-level quality covers 100 relevance-labeled cases, with unique top-five sources from 20 passages.

| Mode | Recall@5 | MRR | nDCG@5 | ID precision@5 | P50 ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|
| dense | 0.9550 | 0.8675 | 0.8861 | 0.2300 | 23.304 | 27.595 |
| bm25 | 0.9400 | 0.8490 | 0.8704 | 0.2365 | 57.982 | 67.942 |
| hybrid | 0.9800 | 0.8817 | 0.9060 | 0.2360 | 34.125 | 47.926 |
| hybrid_rerank | 0.9900 | 0.9025 | 0.9245 | 0.2380 | 917.605 | 1116.678 |

ID metrics do not use an LLM judge and are not Ragas model-judged context quality. No test-set tuning or target-score substitution is claimed.

The retained sequential inline durable graph completed 120/120 cases: worker P50/P95 1327.49/1573.98 ms; first durable evidence P50/P95 1119.96/1384.65 ms. Eight arithmetic-labeled cases selected the expected tool. This is operational completion, not semantic answer accuracy; HTTP admission and queueing are excluded and generation usage is zero.

## Fresh extractive scale experiment

Two API replicas, one/two/four workers, five isolated sample workspaces, ten submission threads and 100 requests per configuration. The asset cache was already populated; fixture ingestion precedes measurement, and fresh worker processes may incur model warmup. Latency includes server queueing. Scans, restore/rehearsal stacks and model judging were stopped before this experiment.

| Workers | Completed | Runs/s | End-to-end P50 ms | End-to-end P95 ms | Queue P50 ms |
|---|---:|---:|---:|---:|---:|
| 1 | 100/100 | 2.244 | 20749.3 | 37738.6 | 20393.9 |
| 2 | 100/100 | 3.762 | 12443.8 | 20881.3 | 11958.0 |
| 4 | 100/100 | 5.403 | 7318.9 | 11427.1 | 6774.2 |

| Workers observed | Snapshots | Sampled max total CPU | Sampled max total RAM GiB |
|---|---:|---:|---:|
| 1 | 20 | 374.0% | 2.06 |
| 2 | 8 | 444.4% | 2.43 |
| 4 | 7 | 831.4% | 3.21 |

CPU 100% is one logical CPU. Samples include startup/idle and are not instantaneous peaks. Queueing dominates this burst; throughput is sublinear and CPU/memory rise with workers. Scheduler/connection-pool wait and reranker profiling would distinguish causes. These results are not public capacity, sustained Internet throughput or an SLA.

An additional read-only arithmetic audit recomputed the published server P50/P95, queue median, throughput and zero model/token usage from all 300 actual run records. Raw timestamps and input hashes are in [load-timing-audit.json](../evaluation/results/load-timing-audit.json). The runner-reported submission median has no retained per-submission samples and is explicitly outside that independent recomputation. Prior source-bound scale results remain in `evaluation/results/historical/*-ba20.json`.

## Fresh recovery and security gates

Clean isolated startup and persistent stop/start passed in 133.14s. Isolated backup restoration passed in 137.56s, verified 149 source hashes and completed a query with 1 cited passage. The private-CA/local-STARTTLS production-mode signup/session rehearsal passed in 94.15s. Primary data was preserved; disposable stacks were stopped with their volumes retained.

Final-source functional checks passed: **240 backend tests**, **nine Playwright workflows**, generated API contracts/types, BFF and parser-boundary probes. Aggregate critical branch coverage is **528/582 = 90.722%**, not per-file or whole-repository coverage.

All 14 full security gate steps passed: Semgrep, Trivy source/secret/config analysis, locked dependency audits, OWASP ZAP and eight runtime-image gates. Raw optional evaluator advisories and the locally backported legacy JOSE finding remain disclosed and require their exact executed mitigations; see [evaluator controls](../security/EVALUATOR_MITIGATIONS.md) and [JOSE controls](../security/JOSE_BACKPORT.md). Independent AI source review passed separately; its reviewer did not execute builder tests or scans. No human certification or vulnerability-free claim is made.

## Quality and hosted verification

Historical live quality is 37/37, with 19 historical RPC-provenance gaps preserved. The frozen isolated comparison remains 36/148 at its free quota gate; the 37 available answer texts and 559 claim records have attributed assistant review. Low and zero model scores remain unchanged; no independent human answer validation is claimed.

The [fresh hosted verification](https://github.com/rishicodes576/quarry/actions/runs/40701137034) for code commit `cf2e42e` passed cold startup, 240 backend cases, nine browser workflows and all security/image gates with zero annotations. Its executable fingerprint matches this checkpoint; the exact tested commit remains recorded in [github-ci.json](../evaluation/results/github-ci.json). Documentation/evidence follow-up commits do not change that source binding. The prior JOSE security failure remains in history. Public/native-host acceptance remains a separate installation step; local private-CA/mail rehearsal does not establish public ACME or external application email delivery.
