# Current audited release status

Status: **incomplete**. Source: `ba20aa5db83300c72129c44a07dbf54972067b46c9b8c680b133c2a442dccd84`.

Legacy campaign: **37/37**. Isolated paired comparisons: **36/148**. Successful backend cases with current JUnit evidence: **224**.

| Requirement | Acceptance | Evidence |
|---|---|---|
| Docker/Compose runtime, PostgreSQL only, fail-closed production | passed | 1 matching successful JUnit executions; current source required |
| Public email-verified signup, generic responses and one-use links | passed | 2 matching successful JUnit executions; current source required |
| Argon2id policy, reset, password changes and revocation | passed | 2 matching successful JUnit executions; current source required |
| TOTP enrollment, replay defense and single-use recovery | passed | 1 matching successful JUnit executions; current source required |
| Shared session expiry, caps, revocation and CSRF | passed | 2 matching successful JUnit executions; current source required |
| Owner/editor/viewer and cross-workspace resource permissions | passed | 2 matching successful JUnit executions; current source required |
| Scoped expiring server API keys and no cookie fallback | passed | 2 matching successful JUnit executions; current source required |
| PDF/Markdown/text/public HTML, provenance and immutable versions | passed | 3 matching successful JUnit executions; current source required |
| Explicit scanned/encrypted/malformed/oversized source errors | passed | 4 matching successful JUnit executions; current source required |
| Networkless credentialless bounded parser service | passed | 2 matching successful JUnit executions; current source required |
| Private S3 shared storage, atomic capacity and cleanup | passed | 2 matching successful JUnit executions; current source required |
| Immediate retrieval exclusion and historical evidence/checkpoint cleanup | passed | 2 matching successful JUnit executions; current source required |
| Local ONNX dense, BM25, hybrid RRF and cross-encoder reranking | passed | 1 matching successful JUnit executions; current source required |
| Bounded LangGraph planning, research, citation checks and extractive operation | passed | 2 matching successful JUnit executions; current source required |
| Restricted arithmetic, web/Wikipedia/page tools and graceful outages | passed | 19 matching successful JUnit executions; current source required |
| Payload-bound idempotency and transactional durable queue | passed | 1 matching successful JUnit executions; current source required |
| Persistent conversations, durable event replay, revocation and exports | passed | 2 matching successful JUnit executions; current source required |
| SKIP LOCKED leases, heartbeat, killed-worker recovery and stale fencing | passed | 3 matching successful JUnit executions; current source required |
| Cancellation, graceful shutdown, bounded retries and visible dead work | passed | 2 matching successful JUnit executions; current source required |
| Shared and tenant backpressure, concurrency and weighted scheduling | passed | 3 matching successful JUnit executions; current source required |
| Atomic shared token reservations, usage settlement and per-run paid consent | passed | 2 matching successful JUnit executions; current source required |
| Quota exhaustion retains provider/evidence; no automatic paid fallback | passed | 4 matching successful JUnit executions; current source required |
| Conversation/source/research/member/invitation admission ceilings | passed | 4 matching successful JUnit executions; current source required |
| DNS rebinding, private addresses, redirects, TLS pinning and deadlines | passed | 4 matching successful JUnit executions; current source required |
| Source instructions remain untrusted; bounded tools and citation validity | passed | 2 matching successful JUnit executions; current source required |
| Bounded/redacted failures, secret-safe responses and authenticated proxy hops | passed | 4 matching successful JUnit executions; current source required |
| Prometheus operational gauges and structured execution diagnostics | passed | 1 matching successful JUnit executions; current source required |
| Retention/deletion controls and workspace-scoped orphan reconciliation | passed | 1 matching successful JUnit executions; current source required |
| Isolated case/mode research conversations and typed authenticated results | passed | 2 matching successful JUnit executions; current source required |
| Frozen model/data/config protocol; restart/cache/provenance guards | passed | 4 matching successful JUnit executions; current source required |
| Independent score arithmetic, corruption rejection and unsafe arithmetic defense | passed | 15 matching successful JUnit executions; current source required |
| Fresh Compose startup and persistent restart | passed | clean-start-restart.json |
| Isolated backup restore with source hashes and cited query | passed | restore.json |
| Two APIs with one/two/four workers; throughput/queueing/resource samples | passed | scaling.json |
| Loopback production HTTPS/STARTTLS signup/session rehearsal | passed | production-rehearsal.json |
| 120 frozen cases, four modes, 480 retrieval rows | passed | mathematical-audit.json |
| All eight frozen calculator expressions checked against exact values | passed | arithmetic-validation.json |
| Independent AI security review of final source deltas | passed | independent-review-acceptance.json |
| Public Oracle infrastructure | deferred_owner | Owner account creation/identity verification is deferred |
| Real free personal Gmail sender | deferred_owner | Owner app password and private free-plan confirmation are deferred |
| Actual public hostname/HTTPS/native-host acceptance | deferred_owner | Requires owner-controlled infrastructure and hostname access |
| Current complete functional/browser/coverage gate | passed | release-readiness.json |
| Current complete security gate | passed | release-readiness.json |
| Original 37/37 preserved campaign | passed | release-readiness.json |
| All four modes and 148 isolated evaluations with audited provenance | incomplete | release-readiness.json |
| Attributed claim and complete-answer support review, including claims omitted by model decomposition | incomplete | release-readiness.json |

Mail progress: private sender credentials are configured; live certificate-verified SMTP authentication and one authorized same-account inbox receipt passed (`smtp-delivery.json`). Public-origin signup/recovery and deployed-outbox acceptance remain pending. The generated checklist's earlier credential-deferral wording predates this owner setup; it must not be read as a claim that sender credentials are still missing.

Only owner-dependent provisioning/mail/DNS is deferred. Free quota waits remain unfinished work. Historical reports are retained; they do not override this current status. Known evaluator advisories and tested mitigations remain disclosed. No public deployment or human certification is implied.
