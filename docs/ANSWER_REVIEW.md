# Answer support review

Status: assistant-assisted inspection completed for five claim paraphrases from the first fully judged case. Independent human validation is pending. The worksheet is `evaluation/results/factual-support-review.csv`; the complete generated response and source passages remain in `live-ragas.json`.

The case asks how expired workers are prevented from publishing results. Its central answer correctly identifies the job-row lock, current fencing token and unexpired lease. The supplied passage explicitly states a 90-second lease and a 30-second heartbeat.

The answer also introduces unsupported tradeoffs. Its longer-lease discussion says a crashed worker could publish stale results, although a crashed process cannot publish and fencing still applies. Its broker alternative implies decoupling publication from the lease check; the actual passage supports an outbox and idempotent consumer, without removing the fencing requirement. Clock-skew and heartbeat-loss concerns are plausible engineering analysis but were not directly established by the cited evidence.

The model judge scored context precision about 1.000, context recall 1.000 and faithfulness 0.7083 on this one case. Relevant retrieval does not guarantee a fully supported recommendation. The mechanical reference validator checks citation IDs and cannot detect those unsupported conclusions. The product's source inspector and factual-support warning expose that distinction.

Future quality work should use development cases to tighten unsupported-claim handling, calibrate abstention and evaluate a separate support-check stage. Preserve the frozen test boundary, name any changed prompt/model configuration, and use a new held-out sample for the resulting claim. Do not edit the recorded answer or replace this partial score with a more flattering rerun. No assertion of perfect answer accuracy is supported by the current evidence.

## Historical case q049 — assistant inspection, 26 October 2026

Reviewer: release assistant (AI); no independent human validation. The saved answer correctly cites the shared-artifact rationale, private S3 storage, API workspace-membership checks and retained content hashes. Its inference that independent local copies can diverge is reasonable but is an inference, not an explicit statement in the supplied passage. Bucket storage alone does not establish consistency or tenant isolation; the passage assigns the latter to server-derived keys and API checks.

The answer adds unsupported comparisons about NFS/GlusterFS, database BLOB performance/cost, instant pod startup and pay-as-you-go pricing. Those claims are not established by its cited passages. The pricing text does not describe an enabled Quarry billing service. The answer appropriately acknowledges that the supplied evidence does not quantify remote-read latency or establish a backup SLA. The original response, including its limitations, remains unchanged. Its recorded context precision/recall/faithfulness scores are approximately 0.750/1.000/0.286; they are not replaced with a more favorable rerun. This inspection does not satisfy the separate complete isolated-v2 review worksheets.
