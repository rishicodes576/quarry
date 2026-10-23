# Completion and remaining boundaries

Evidence snapshot: final source `0f0f03ed2478dbd33108e5ddeb8053d2d649e3ff694cb039f72fa9517638060e`. No paid service was used.

| Requirement | Delivered and checked | Evidence / boundary |
|---|---|---|
| Accounts and permissions | Public verified signup, reset, MFA/recovery, session/key revocation and workspace roles | Backend and browser suites; real Internet mail awaits owner SMTP credentials |
| Research product | Documents, persistent conversations, durable timeline/SSE, source inspector, four retrieval modes and exports | Eight Playwright workflows and actual UI captures |
| Ingestion isolation | Separate credentialless/networkless parser container, bounded children, retryable overload, immutable publication | Real parser/socket tests and runtime isolation probes |
| Durability/recovery | Shared PostgreSQL leases, heartbeats, fencing, checkpoints, cancellation and bounded retries | Integration tests and isolated backup/restore artifacts |
| Resource admission | Shared/tenant queue, byte/token/concurrency caps and retained metadata ceilings | Concurrent PostgreSQL tests and scoped usage UI |
| Storage reconciliation | One-workspace dry run/apply, 24-hour age floor and protected references | Actual S3 test workspace; coordinate external restores/writers |
| Retrieval measurements | 120 frozen cases, four modes, 480 timed queries and held-out metrics | Raw results; authored synthetic labels, not general accuracy |
| Live quality measurements | 12/37 fully judged cases and durable free campaign continuation | Incomplete sample; no representative 37-case claim |
| Scalability | Two API replicas and one/two/four workers measured | Local finite workload, not production SLA or multi-zone HA |
| Security verification | Independent AI review, static/dependency/image scans, ZAP baseline and negative tests | Finite review scope; optional evaluator advisories disclosed |
| Production settings | Local trusted HTTPS/STARTTLS signup/session rehearsal passed | Private test CA/sink; Oracle account verification and real SMTP credentials await the owner |
| ARM readiness | Real ONNX inference and Qdrant executable passed in ARM64 emulation | Complete native-host Compose acceptance remains for deployment |
| Delivery | Source, reproducible commands, diagrams, runbooks, audit, screenshots and ZIP | Secrets/private attachments/build caches excluded |

No report establishes freedom from all vulnerabilities, human certification, a paid billing integration, off-host disaster recovery, multi-zone failover, or an always-on public deployment. Those cannot be inferred from local containers or a source review.

The latest instruction requests public deployment. The owner confirmed the Oracle account has not yet been created/verified. Required human identity/card verification cannot be replaced by a local test. See `ORACLE_DEPLOYMENT.md` for the concrete free-host, DNS, SMTP and acceptance steps.
