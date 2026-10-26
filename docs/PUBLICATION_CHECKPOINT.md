# Public work-in-progress checkpoint

Publication scope authorized on 26 October 2026: publish the implemented project and available evidence now, while preserving the final acceptance requirements. This source publication is not a completed release or a publicly hosted application. The final `manage.py publish` and `finalize` commands retain their complete-measurement gates.

`manage.py publish` is a guarded initial-repository creation command and deliberately refuses an existing repository or remote. After this authorized checkpoint creates the repository, later updates use its verified existing Git remote. A completed release still requires a successful `manage.py finalize`; this checkpoint does not satisfy or remove that requirement.

| Component | Status at this checkpoint |
|---|---|
| Next.js interface, FastAPI service, accounts, workspace authorization and durable research jobs | Implemented; current local functional gate passed with 224 backend tests and nine browser workflows |
| Docker Compose, PostgreSQL, Qdrant, private SeaweedFS S3, parser service, workers and local search | Implemented with local startup, persistence, recovery, scaling and restore evidence |
| Retrieval comparisons | Four modes, 120 frozen authored synthetic cases and 480 timed queries; source-level relevance labels are not independently human validated |
| Security | Current local scans and scoped independent AI code review passed; known evaluator metadata advisories and exact tested mitigations remain disclosed |
| Historical live quality campaign | 37/37 completed; arithmetic audit passed, with 92 verdict-derived scores recomputed and 19 historical scores explicitly lacking original judge RPC provenance |
| Isolated primary comparison | 12/148 completed, all in dense mode; the other modes and the remaining cases are unfinished |
| Answer support review | All 12 completed answers and 169 decomposed claims reviewed with explicit assistant attribution; remaining cases await execution. No human validation is claimed |
| Hosted installation | Operator-supplied infrastructure, HTTPS origin and mail transport configuration are required; local transport rehearsals are verified separately |
| GitHub CI | Actual hosted startup, 224 backend tests, nine browser workflows and complete security scans passed with zero GitHub annotations. See `evaluation/results/github-ci.json` |

The twelve completed isolated cases contain four generated answers and eight citation-fallback answers. Those answer kinds are recorded individually. Their partial averages are not a complete four-mode comparison or a general answer-quality claim. Finite checks, model judgments and assistant review do not establish perfect security or perfect factual accuracy.

The free-only evaluation campaign keeps its original provider, frozen protocol and quotas. It retains checkpoints through free-budget waits. No paid provider has been used or enabled as an automatic fallback.

See [the current acceptance checklist](RELEASE_STATUS.md), [evaluation protocol](EVALUATION_PROTOCOL.md), [current local measurements](CURRENT_LOCAL_EVIDENCE.md), [threat model](THREAT_MODEL.md), [operations](OPERATIONS.md) and [deferred deployment tasks](DEPLOYMENT_LATER.md). Raw reports are in `evaluation/results`; each report retains its own source binding and measurement scope.

Local credentials, private runtime state, backups, browser traces, original resume and interview attachments, dependency caches and model weights are excluded from the public source. Dependency licenses and notices remain included. Git author and committer attribution is Rishab Chetal `<rishabchetal@gmail.com>`.
