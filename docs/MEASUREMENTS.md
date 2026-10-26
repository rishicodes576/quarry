# Measurement protocol

The screenshot's 1.000 context precision/recall and approximately 1.10-second P50 are comparison targets, not prewritten project claims. Retrieval latency, full-agent latency, and end-to-end queueing latency are distinct measurements. A fast local retrieval result does not establish a 1.10-second generated answer.

## Frozen data and relevance metrics

`evaluation/manifest.json` pins SHA-256 hashes for 24 original synthetic engineering sources and 120 cases. The split is 30 development / 90 test cases. Kinds are 48 direct, 24 paraphrase, 12 multi-document, 12 unanswerable, eight contradiction, eight tool and eight hostile-source cases. Source-level relevance is authored with the corpus and is not independently human validated. Corpus content deliberately describes engineering scenarios; it is not always a literal assertion about the current application configuration.

`python scripts/manage.py benchmark` validates hashes before execution, indexes a separate evaluation workspace, loads pinned models, then runs dense, BM25, hybrid RRF and hybrid-plus-reranker sequentially. Each query requests 20 passages, deduplicates source IDs and evaluates the first five unique sources. Recall@5 measures relevant-source coverage; MRR rewards the first relevant source; nDCG discounts relevant ranks. Precision@5 divides relevant returned sources by returned unique sources. Cases with no relevance labels are excluded from relevance aggregates and retained in timing counts. Report both counts.

Ragas IDBasedContextPrecision and IDBasedContextRecall use the authored source IDs without a model call. They are genuine Ragas package metrics, but they are different from model-judged ContextPrecision (an average-precision-style judgment) and ContextRecall. A fixed top-five result with one relevant source may have ID precision 0.2 despite perfect recall. Metrics are not interchangeable.

Model initialization time is recorded separately. Query timings use warm models, no answer cache and a single sequential client. The artifact includes Python/platform/model/file hashes and per-case rows. Approximate search, tied sparse scores, CPU contention and process conditions can change ranks/timings on rerun. Keep all raw rows and describe run conditions; never select only the most flattering repeated result.

## Answer quality and tools

`benchmark --live` explicitly uses the locally configured, attested Groq Free Plan key. Every SDK judge call goes through Quarry's same bounded provider and usage ledger. The selected first 37 held-out answerable cases are recorded before judging; selection is not based on their scores. The evaluator resumes saved completed metrics and stops on provider or application budget exhaustion. It never switches endpoints to get a complete-looking report. A partial report is not a 37-case benchmark.

Context precision/recall and faithfulness are model judged and inherit judge bias, truncation and schema limitations. Using the same model family for answering and judging is not independent validation. The actual report must show completed counts and stop reasons. Mechanical citation validation checks identifiers only. Factual-support review must inspect claims against cited passages separately; `factual_support` remains explicitly unverified until reviewed. A manual-review worksheet is supplied without invented human verdicts.

Tool-selection tests exercise the graph's bounded adapters and permissions. The frozen tool cases currently cover arithmetic; accuracy on those cases does not establish general web/Wikipedia tool routing accuracy. Task completion means the specified terminal execution contract, not automatic proof of a correct engineering recommendation.

## Capacity and reliability

`loadtest` uses five isolated sample workspaces, ten HTTP submission threads, two API replicas and 100 local extractive requests per configuration. It measures one/two/four workers, accepted/completed/rejected counts, P50/P95 including queueing, submission timing, and a Docker resource snapshot. This is a finite burst on one laptop. It does not establish sustained production capacity, an availability SLA, multi-region throughput or fair CPU time. The first attempted load run uncovered an admission/connection-pool deadlock; the fix and subsequent results belong in the audit.

The executed backend suite uses real PostgreSQL, Qdrant, S3 and local ONNX models. Network failure and paid-provider behaviors use simulated transports and are labeled as such. Browser signup/recovery uses actual local SMTP capture, not internet mail. Recovery evidence distinguishes a real killed worker from a unit-level signal callback. `restore-test` records actual restored source hashes and a completed cited query in an isolated stack.

Critical branch coverage is the aggregate across the explicitly listed authentication, authorization, API, queue, worker, provider, graph, network, parser, retrieval, configuration, schema, storage, encoder, capacity, telemetry and tool modules in `scripts/release.py`. It is not whole-repository coverage or a claim that every file exceeds 90%. Operator and evaluation CLIs are verified operationally and remain visible in the full coverage JSON rather than being hidden from the report.

## Results and resume use

Use the actual JSON artifacts under `evaluation/results` and their timestamps. Main retrieval results are `latest.json` / `retrieval-all.json`; scaling is `scaling.json`; live quality is `live-ragas.json`; functional checks are `verification.json`; dependency/image/dynamic scanner evidence is under `security`. Preserve source/model/corpus fingerprints and clearly mark partial or historical reports after code or storage changes. Resume bullets must name the measured dataset and sample counts and avoid claims of perfect factual accuracy or vulnerability freedom.

## Final load observation details

The timed burst starts after worker replicas report ready and fixture documents have indexed. It is not a cold-container-launch benchmark. The artifact's `end_to_end_*` values use durable server timestamps from run creation to completion, including queue wait; they exclude pre-admission network time and browser/SSE delivery. HTTP submission timing is reported separately. Requests go directly to the internal API service, so these numbers are not full public-edge latency.

For the final run an independent lightweight observer executed `docker stats --no-stream --format "{{json .}}"`, waited two seconds after each command, and repeated while the complete `python scripts/manage.py loadtest` command ran. `load-resources.json` retains timestamped raw snapshots, observer errors and sampled maxima grouped by observed worker count. Groups include startup and idle intervals. Docker CPU 100% represents one logical CPU; sampled maxima are not instantaneous peaks. To repeat the observation, capture timestamped Docker stats in a second terminal while running the management command. This additional observer is an executed experiment, not an automatically included step of the management command.

The final noisy-tenant probe submits 20 enterprise requests followed by five free requests with two API replicas and one actual worker. Normal admission limits remain enabled. The raw dispatch order demonstrates finite progress for that burst; it does not prove a latency SLA, steady-state throughput or weighted CPU-time fairness.


## Independent arithmetic audit

Run the saved-measurement audit without generating new model calls:

```powershell
docker compose --profile evaluation run --rm --no-deps evaluate python -m quarry.metric_audit --export-judges --require-live-complete
```

The auditor implements the formulas separately from the benchmark implementation and fails on missing/duplicate source-mode rows, missing summaries, changed frozen labels/splits, incorrect counts, nonfinite scores or arithmetic mismatches. `mathematical-audit.json` records the input file hashes and exact checked scope; `judge-verdicts.json` contains the referenced synthetic-workspace judge outputs, never credentials. The strict option requires all 37 selected cases and a verdict export. Historical metrics without saved RPC identifiers remain explicitly listed as unaudited at the verdict level; their presence is not disguised as complete provenance.

For unique source ranks 1 through k=5, let y_i be binary source relevance and R the complete source-label set. Recall is sum(y_i)/|R|; reciprocal rank is 1/(first relevant rank), or zero; DCG is sum(y_i/log2(i+1)); nDCG divides DCG by the ideal ordering of min(k,|R|) relevant sources. Returned-source precision divides sum(y_i) by the number returned, not always five. Relevance summaries are unweighted arithmetic means over relevance-labeled cases. Unanswerable/tool cases stay in timing counts.

Ragas context precision is average precision over judge relevance verdicts: sum(precision_at_i * verdict_i)/(sum(verdict_i)+1e-10). Its denominator counts judged relevant returned passages, so a value near one does not establish complete source coverage or that every returned passage is useful. Ragas context recall averages binary reference-statement attributions; faithfulness averages supported generated-statement verdicts. Those are model judgments, distinct from deterministic source-ID metrics. The audit recomputes scores from available saved verdicts without re-judging their correctness.

Latency P50/P95 uses linear interpolation at position (n-1)*p in the sorted observations. The audit allows .0011 ms for independently rounded retrieval rows and summaries. Throughput is completed runs divided by measured duration; rounding does not imply extra measurement precision. Unit tests include known nontrivial ranks, hand-calculated judge ratios, interpolation and deliberately corrupted score/summary/split artifacts.
