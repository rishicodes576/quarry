# A five-minute reviewer walkthrough

Prepare with `python scripts/manage.py up`. Use the local sample account, keep the provider set to **Local evidence**, and open the benchmark artifacts before the demonstration. If evaluations have not run, show their empty state honestly.

**0:00–0:40 — State the problem.** Engineers need to inspect which source supports a decision and understand how an interrupted research job recovers. Show Research, Source library, Retrieval lab and Settings. Explain that samples are synthetic and generation is optional.

**0:40–1:30 — Follow evidence.** Upload a small Markdown note about a worker's lease and fencing token. Watch pending → indexing → ready. Ask a question about the note. Click its citation and inspect the passage, source/page metadata and content fingerprint. Export the Markdown brief and reload the conversation. Distinguish a quoted extractive brief from generated reasoning.

**1:30–2:15 — Explain execution.** Show the persisted stage timeline and a run ID. Research is a durable job with bounded tools and a fixed provider. Describe the lease, heartbeat and fencing check at publication. Refer to the actual worker-kill test; do not improvise destructive commands against the user's data. Cancellation checks at stage and publication boundaries; it does not rewind an external request already accepted.

**2:15–3:00 — Compare retrieval honestly.** Enter the same question in the lab and compare all four modes. Open the actual frozen evaluation report. Name source-level Recall@5, MRR and nDCG, and distinguish ID-based precision/recall from LLM-judged Ragas scores. Show both latency and quality tradeoffs. The 120 cases are an authored synthetic set, not an independent general benchmark. Never quote a single successful live judge case as a representative 1.000 score.

**3:00–4:00 — Defend shared capacity.** Show Settings' real storage, queue, token and plan limits. Explain that quotas limit consumption, while fair dispatch decides whose work runs next. A larger tenant may receive a higher operator-provisioned weight but cannot bypass shared limits. Show the measured one/two/four-worker load report, including queueing P95 and resource consumption. Discuss why a busy burst produces seconds of queueing even when individual retrieval is fast.

**4:00–4:40 — Demonstrate account boundaries.** Show verification-required public signup with the local mail sink, a viewer invitation and its read-only controls, revocable sessions, and optional MFA. Explain that backend authorization enforces these controls independently of the UI. Scoped machine keys cannot administer accounts. No secret is embedded in browser code.

**4:40–5:00 — Give the operational limits.** Open the audit and restore evidence. State exactly which checks passed, which remain partial, and how optional evaluator advisories were locally mitigated and which production checks remain outstanding. Explain the path to replicated data services and a real business model with bounded included usage. No payment processing or internet deployment is claimed. Finish with the repository's reproducible commands and the independent review required before public exposure.
