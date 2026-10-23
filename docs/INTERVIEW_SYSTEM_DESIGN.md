# Defending Quarry's system design

These scenarios are derived from the supplied interview's technical questions. The private transcript is not part of this repository. Demonstrate the behavior and explain the constraint before naming the mechanism.

## A large customer is within quota and still crowds out smaller customers

An account quota measures how much work is allowed over time. It does not decide whose work runs next. Quarry makes those decisions in two places:

1. The FastAPI admission boundary authenticates, authorizes, binds the idempotency key to its payload, and checks bounded shared and workspace queue capacity. It commits the run, job and durable event together. An accepted run returns `202` and an ID; a full workspace returns `429`; exhausted shared admission returns `503` with a retry hint. Requests do not occupy an HTTP connection while waiting for compute.
2. Workers choose the oldest eligible job from each workspace, then select the smallest weighted virtual finish time. The formula is `max(tenant_finish, shared_virtual_time) + estimated_cost / weight`. The operator provisions weights of 1, 2 or 4; a request cannot submit its own weight. After dispatch, both the tenant finish and shared virtual clock advance transactionally in PostgreSQL. A short scheduler lock serializes capacity decisions across worker replicas; jobs also use `SKIP LOCKED` and fenced leases.

The queue shares idle capacity. It does not reserve a server for every customer or provision for the sum of their advertised quotas. Tests exercise a continuously backlogged high-weight tenant and a smaller trial tenant, a late arrival, concurrent claimers and the global concurrency ceiling. See `backend/tests/test_fair_capacity.py` and the executed verification artifacts for results.

This is non-preemptive scheduling with estimated costs, not a guarantee of equal CPU time. An already running job finishes or reaches its execution bound before its slot becomes available. Cheap and expensive request classes use different cost estimates; estimates must be calibrated from observed phase durations. Dedicated queues or capacity pools are appropriate when a customer purchases an actual latency/isolation commitment. Do not sell an unqualified "unlimited" plan on finite shared infrastructure.

## One customer spends the deployment's generation allowance

Provider reservations lock both a shared deployment ledger and the workspace ledger before making a model request. The input/output envelope is bounded and a conservative reservation covers it. Known usage releases unused capacity; ambiguous interrupted calls consume their reservation conservatively. Provider quota exhaustion pauses the run and retains its provider and evidence. No fallback spends money automatically.

Workspace allowance and scheduling priority are independent. Raising a plan's scheduling weight does not raise the deployment's token budget or enable paid generation. `/v1/usage` exposes the account's used and reserved tokens, finite limits, pending/running work and queue age. The shared cap remains a hard admission constraint even if several customers simultaneously have unused personal allowances. A free provider may enforce an additional, smaller external cap; its key does not reveal billing status.

## What happens during a traffic burst?

Keep the request path short: validate, admit and enqueue. The browser follows persisted SSE events with a reconnect cursor and can poll or cancel. Worker capacity grows independently of the API. Bounded retries and visible dead jobs keep poison work from circulating forever. A lease expires after a worker dies, and a new worker resumes durable graph checkpoints; stale workers cannot publish SQL results or graph writes.

Retries use the same idempotency key and payload. A different payload with the same key is rejected. Queue rejection is deliberate load shedding: it protects already accepted work. A retry hint is not a completion-time guarantee. Clients should use bounded exponential backoff with jitter and a total deadline.

The current single PostgreSQL scheduler row can become a throughput bottleneck. Measure its transaction latency and lock wait before replacing it. A future scheduler can partition tenants by a stable hash and allocate explicit capacity budgets to each partition, or use a broker plus a separate fair dispatcher. Adding a broker alone does not implement fairness.

## How would you deploy it beyond one laptop?

The supported runnable baseline is Docker Compose. APIs hold no local sessions or application state. PostgreSQL stores identity, entitlements, quotas, jobs, checkpoints and events; Qdrant stores retrieval indexes; private S3-compatible storage holds immutable source versions. This permits independently scaling APIs and workers without sticky sessions. ONNX weights are pinned, prepared once and mounted read-only.

For a public service, place TLS termination and request/body/time limits in front of the web/API boundary. Use private networks, separate migration and runtime database identities, a supported S3 service, authenticated Qdrant and an actual email delivery service. Production refuses demo seed, insecure cookies, missing verification mail delivery, missing private-service credentials and excessive database privileges. Keep secrets in deployment secret storage and restrict administrator credentials to initialization.

Separate capacity pools for ingestion and research if parsing spikes affect interactive research. Scale workers on queue age and sustainable service rate, with a minimum warm pool, a maximum replica/cost ceiling, and a stabilization window. Scale APIs on request latency/CPU/connections; model inference also consumes API CPU in the retrieval comparison endpoint. Queue length by itself is insufficient when job costs differ.

Start with a single write region. Use managed or independently operated PostgreSQL failover, backups and tested restoration, replicated object storage and Qdrant recovery procedures. Multi-region active writes require an explicit consistency and tenant placement design; Compose alone does not supply high availability. A warm spare or Kubernetes manifest is not evidence that failover works. See operational runbooks and executed restoration/scaling evidence before making availability claims.

## Capacity math you can explain

Measure arrival rate `lambda`, mean service time `S`, worker count `c`, and queue delay. Approximate utilization is `rho = lambda * S / c`; near saturation, tail latency rises sharply. For a target utilization of 0.65, estimate `c >= lambda * S / 0.65`, then validate with burst and mixed-cost workloads. Little's Law, `L = lambda * W`, relates average work in the system to throughput and time in the system under stable conditions; it is not a tail-latency guarantee.

Use the local one/two/four-worker experiment as a measured baseline, not as proof of internet-scale capacity. State corpus size, hardware, concurrent clients, warm/cold conditions, accepted and rejected requests, and whether the workload includes real model generation. The bundled load test uses local extractive answers, so it cannot establish live-provider throughput or cost.

## How could the service earn revenue without uncontrolled cost?

Possible products are a small free allowance, a workspace subscription with bounded included usage, prepaid compute credits, or a deployment/support contract for a customer-owned installation. These are business options, not active payment features. Quarry currently collects no money. Operator-managed plan entitlements are working server-side controls; changing a browser field cannot upgrade them. Model-provider consent is a separate control from a Quarry subscription.

A real billing integration would validate signed payment webhooks, deduplicate event IDs, reconcile entitlement state with the payment provider, handle failed/late/refunded payments and keep an append-only usage ledger. Never accept client-submitted prices or use payment success redirects as proof of payment. Reconcile metered usage independently of worker retries so a resumed job is not charged twice. Define whether a failed run consumes credits and whether interrupted, uncertain provider usage is refundable.

Price only after measuring compute time, storage bytes/retention, bandwidth, model-token usage, email, support and idle capacity. A useful model is `contribution = revenue - variable_cost`, followed by a separate fixed-capacity allocation. Cost estimates must name region, date, utilization assumptions and current supplier prices. No cloud resources or paid service are provisioned by this project builder. Bring-your-own generation keys can transfer model billing ownership while Quarry still enforces its own request and compute limits.

## A concise interview demonstration

Show a verified signup, upload a source, run a cited question, inspect its durable timeline and download the brief. Then show the noisy-tenant dispatch test, shared budget exhaustion, a killed worker resuming its graph, and a restored backup producing a cited answer. Explain one observed bottleneck and the next experiment that would justify a change. Keep measured results, design alternatives and unverified claims distinct.
