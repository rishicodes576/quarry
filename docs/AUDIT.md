# Implementation and verification audit

Evidence is recorded by the command that actually executes a check. Source changes can make a prior report historical; publication requires fresh matching source hashes. Mock transports, unit callbacks and unexecuted configurations are never treated as live integration evidence. The final source ZIP must exclude credentials, backups, account mail, raw private attachments and browser traces.

## Final local release status

The final functional and complete security reports both passed for source SHA-256 `7e97cdc7effc580ba8abd3fdfb97f50bb0dced6cf91d01021ba5b7d0ac50fe2c`. Functional verification passed 152 backend tests and eight Playwright workflows, with 459/502 critical branches covered (91.434%). All eight runtime image families reported zero High/Critical findings in the configured Trivy scan. Semgrep reported zero findings; filesystem scanning and runtime/development Python audits passed. The optional evaluator still has raw advisory metadata findings, accepted only with the tested local capability-removal patches documented in `security/EVALUATOR_MITIGATIONS.md`. ZAP reported zero failures/warnings and two informational categories. This is not an independent penetration test or a guarantee of no vulnerabilities.

A new isolated Compose project started from empty application volumes and passed stop/start readiness in 139.29 seconds using the shared verified model cache. The final backup rehearsal restored 69 source hashes and completed a new research query with five cited passages in 130.48 seconds. Both rehearsal stacks were stopped without deleting their volumes. The deployed image IDs matched their built tags; the legacy MinIO server remains stopped.

The final quiet load experiment completed 100/100 requests at each worker count with two API replicas: 2.231 / 4.016 / 6.383 runs per second for one / two / four workers. Server run-creation-to-completion P95, including queueing, was 38.07 / 19.57 / 10.13 seconds. A real one-worker noisy-tenant probe completed 25/25 requests and started free-tenant work before the enterprise backlog drained. Thirty-six concurrent resource snapshots record increasing CPU/memory consumption, with coarse sampled maxima rather than instantaneous peaks. See `RESULTS.md`, `MEASUREMENTS.md` and the raw reports for scope. Earlier results below are historical.

Live model-judged quality is still partial, with one fully judged case and no independent human verdict. Production HTTPS/external SMTP, off-host disaster recovery, multi-zone availability and payment processing have not been deployed. GitHub CLI is authenticated as `rishicodes576`; the public repository name was absent at the final read-only check. Publication is left to the explicit management command. No paid service was used.

## Stage 1 — Runtime, identities and provider policy

Detected Docker Engine 29.9.2 and Compose 5.6.1, including the per-user Windows installation path. The application and integration tests use Compose, PostgreSQL, Qdrant and private S3; no application SQLite fallback exists. Git is configured locally for Rishab Chetal `<rishabchetal@gmail.com>`; no remote has been published. Publication checks the exact GitHub account, final author/committer, history, secrets, source freshness and repository collisions. It does not force push.

The owner locally configured and attested a Groq Free Plan key. A real authenticated worker research smoke completed in 6.598 seconds, using two model calls and 2,067 reported tokens, with mechanically valid citation references. That is one smoke run, not a P50 or an independently supported factual answer. Paid adapters remain disabled; paid HTTP behavior is simulated only. The application cannot independently determine whether an organization's billing is enabled.

## Stage 2 — Persistence, ingestion and retrieval

Versioned Alembic migrations initialize durable accounts, documents, passages, conversations, runs, events, quotas, job leases, scoped keys, storage accounting and scheduler state. Ready publication follows indexing; supersession and deletion are checked in SQL as well as vector filtering. Tests cover duplicate and concurrent ingestion, malformed PDF, scanning/OCR rejection, parser timeouts/crashes, deletion during indexing, stale fencing and older versions finishing late.

FastEmbed's wrapper originally introduced a vulnerable image-processing dependency despite the application being text-only. It was replaced with direct ONNX encoders using the same pinned model weights. A seven-input compatibility probe reported exact dense/sparse/reranker agreement. Runtime and development Python audits subsequently reported no known vulnerabilities. Each model file is hashed; a verified local model cache works without a model-hub connection.

The frozen 120-case four-mode retrieval run completed all 480 queries. Raw ranks, timings, model revisions and hashes are in `retrieval-all.json`. The separate measurement protocol explains authored labels, source-level ranking, warm conditions and ID-based versus model-judged Ragas scores. No test-set score was used to choose a retrieval threshold or manufacture an improvement.

## Stage 3 — Authentication and authorization

Implemented public signup requiring email verification, Argon2id password storage, opaque revocable sessions, optional TOTP with replay prevention, one-use recovery codes, invitation roles, password recovery, owner-only membership administration, expiring scoped machine keys, and shared throttles. The production profile rejects insecure cookie/origin/SMTP/secret combinations. Runtime API/workers receive a non-superuser database role and no migration administrator password.

The browser audit initially found that verification links opened in the same existing signup tab were ignored because the fragment was processed only at mount. The fragment listener now handles both entry and same-tab changes and removes the token from the address bar. Seven browser workflows then passed, including real local SMTP signup/reset, viewer permissions, source upload/index/research/export, responsive navigation and security headers. Real external email delivery is not claimed. A later keyboard workflow found a focus restoration conflict between native autofocus and the dialog trap; the conflicting autofocus was removed and re-verification is required.

A repeat backend run found a test using the last row of an unordered SQL query to pick a password-reset email. It could accidentally redeem the already-used signup token. The test now selects the intended reset purpose and recipient explicitly; the application did not bypass its single-use check. The latest completed backend suite before the last body-backpressure change passed 149 tests. Refer to `verification.json` for the current result, rather than carrying this historical count forward automatically.

## Stage 4 — Shared capacity and recovery

The first real two-API load run exposed a nested-connection deadlock: admission held one connection and the rate limiter requested a second while other transactions occupied the pool waiting for admission. Admission now increments its limiter in the same SQL transaction. A concurrent-submission regression test exercises that path.

The subsequent 100-request bursts completed fully at each worker count: 2.292 / 4.079 / 6.365 completed requests per second with one / two / four workers and two APIs. P50 including queueing was approximately 19.99 / 10.48 / 5.72 seconds. These are laptop burst observations with other verification activity, not a sustained SLA. They were measured before the storage replacement; a current storage/runtime scaling rerun is needed before attributing those numbers to the final build.

Real-service tests include worker termination, lease expiry, checkpoint reuse, stale publication, duplicate reservations, cancellation, search outages and simulated provider exhaustion. Shared dispatch uses weighted virtual finish times, global/workspace concurrency bounds and work-conserving capacity sharing. Independent fair-scheduler tests verify that an enterprise backlog cannot indefinitely starve a free tenant. Costs are estimates and jobs are not preempted.

Quiesced backup restoration passed in an isolated SeaweedFS/PostgreSQL/Qdrant project in 124.78 seconds: 69 source object hashes verified and a new cited research query completed. Primary data was not overwritten. The rehearsal stack was then stopped without deleting its volumes. Same-host recovery does not establish multi-zone availability or off-host disaster recovery.

## Stage 5 — Dependency and storage security

The first image scan found High/Critical vulnerabilities in unused Debian utilities, bundled npm tooling and the archived MinIO server. The backend now uses a minimal distroless runtime with copied-library package status/inventory and license notices retained; unnecessary interactive terminal extensions are omitted. The standalone web runtime omits npm/Yarn tooling. Both built images subsequently scanned with zero High/Critical findings in the configured Trivy scope.

MinIO's public source repository is archived. Its advisory confirms affected open-source releases and a vendor fix in AIStor, which is outside the no-paid constraint. The user explicitly approved replacing it with free SeaweedFS. Migration stopped writers, took a private backup, copied to a new volume, and verified all 69 retained object hashes before cutover. The old MinIO volume remains available for rollback, and its server is stopped. SeaweedFS administration binds only to its container loopback; a private S3 proxy exposes the authenticated endpoint to backend services. Real probes returned 403 for unsigned and forged-signature requests, refused six administrative/control ports from the API, and confirmed runtime SQL DDL is denied.

SeaweedFS 4.48's bundled binary then reported five High findings with available fixes: `golang.org/x/net` v0.58.0 and Go v1.26.8. A checksum-pinned source rebuild with x/net v0.60.0 and Go v1.26.10 subsequently passed the final image scan and real S3 workflows. The source archive hash, patch recipe and resulting module manifests are retained. The original vulnerable-binary report remains historical evidence.

Semgrep's configured public community packs and Trivy filesystem scanning have reported zero findings in their stated scope. Python dependency audits cover runtime, development and optional evaluation separately. OWASP ZAP's first baseline reported four warnings: inline style permission, missing embedder policy, non-storable responses and modern-application classification. The first two were fixed with nonce styles and explicit cross-origin isolation headers. The remaining two are reviewed informational dispositions in `security/zap-baseline.conf`: intentional no-store privacy policy and JavaScript-application classification. They remain visible as informational findings; exploitable findings are not suppressed.

## Stage 6 — Answer quality and release constraints

The initial live judge adapter incorrectly forwarded an Instructor `mode` parameter to the SDK. The installed Ragas adapter already enables JSON mode; the parameter was removed. Complex structured responses then exposed the provider's bounded-output limit. GPT-OSS requests now use documented low reasoning/hidden format and a 2,000-token output cap within the conservative reservation. Historical metric configurations are retained, and free rate limits pause the evaluation without fallback.

The first fully judged case has model-judged context precision about 1.000, recall 1.000 and faithfulness 0.7083. Only one complete case is available at this stage; the requested 37-case run remains partial. Its answer contains claims the supplied passages do not independently establish. The mechanical citation check correctly does not claim entailment. Human factual-support review and a representative completed quality sample remain outstanding; a single favorable context score is not a headline benchmark.

Current release reports and the final delivery note must distinguish completed local behavior from partial live judging, prepared production configuration, and unexecuted cloud deployment/payment options. No project, scanner or test can establish absolute freedom from vulnerabilities. Both local publication gates now pass for the final source; the outstanding production and independent-review limits remain. Required follow-up includes an independent security review, real SMTP/TLS deployment validation, supported multi-node storage topology and off-host backup practices before internet exposure.

## Final audit follow-up — supporting images

The scan scope was expanded from the three application-built images to all eight runtime image families. This exposed additional upstream findings in Caddy, Mailpit, PostgreSQL's gosu helper, SearXNG's certifi bundle, and the Qdrant dashboard/base packages. Original reports remain under `evaluation/results/security/historical`. Checksum-pinned free source rebuilds replace the affected Go binaries; certifi is updated to 2026.10.19; Qdrant retains its original binary and required libraries while omitting its unused dashboard and unrelated utilities. Runtime package inventories and license notices remain available.

The first expanded scan also flagged an unnecessary explicit root user in Qdrant's build stage and the PostgreSQL image's inherited startup user. The redundant build-stage directive was removed and PostgreSQL now starts as its own UID 70. An isolated, network-disabled empty-volume probe verified successful initialization as UID 70. Search uses its upstream UID 977. No scanner ignore was added for these findings. Fresh final reports, rather than the first expanded attempt, determine release status.

An earlier attempt ran two verification processes against the same test database and produced invalid cross-suite collisions. A cross-process verification lock was added, and sequential full suites subsequently passed. Current critical branch coverage is an explicitly scoped aggregate, not whole-repository coverage. Docker build contexts now exclude ignored runtime backups as well as local keys and caches.

The final screenshot review found a stale MinIO label in Settings after the storage implementation had changed. It was corrected to private S3. The formatter gate initially rejected that edit; formatting was applied, the Next.js production build passed, and both full source-bound release suites were executed again. The final screenshots are actual browser captures, not design mockups.

## Network-recovery completion checks

After connectivity returned, Docker and the running primary services were healthy. Public-page fetching returned one source, Wikipedia returned three sources, and self-hosted SearXNG returned three search results on the hardened runtime. The real evaluation browser workflow passed again and refreshed the screenshot using the final measured values. The current source fingerprint still exactly matched both passing release reports.

The optional live quality evaluation was resumed using only the locally attested free key and unchanged hard budgets. Further judging was rejected by a quota gate with HTTP 429; the SDK made one attempt for that rejected call, kept Groq as its provider, and made no paid call. The report remains partial with one complete judged case. The earlier automatic approval-review interruption was an account usage-limit review failure, not a determination that the actions were unsafe; the affected checks were retried successfully after access resumed.
