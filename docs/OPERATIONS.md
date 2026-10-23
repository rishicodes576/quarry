# Operations

## Configuration and lifecycle

`python scripts/manage.py up` discovers Docker (including the per-user Windows installation), checks the engine/Compose, generates random ignored local secrets, builds, initializes migrations/models/private storage, seeds original samples, and waits for readiness. Model assets and PostgreSQL/Qdrant/object data persist in named volumes. `python scripts/manage.py down` stops the stack without deleting volumes. Restart with `up`; never use `down --volumes` to troubleshoot a database problem.

Development uses a local email sink at port 8025. Public signup requires opening the delivered verification link; entering an address alone creates no account. For real deployments configure `QUARRY_ENV=production`, HTTPS `QUARRY_APP_ORIGIN`, `QUARRY_COOKIE_SECURE=true`, `QUARRY_DEMO_SEED=false`, a real SMTP host/port with STARTTLS, private gateway secret and random database/vector/storage credentials. Invalid production combinations fail startup. A supplied key cannot prove its organization is free; the owner must verify billing before configuring it.

Create a private initial workspace via `python scripts/manage.py create-owner` (hidden password input). Existing owners invite editors/viewers through Settings; users accept one-use links. Changing a user's role or disabled state takes effect server-side. The owner cannot remove or demote themselves through that API. Ownership transfer is an audited operator database change after identity verification, not an unauthenticated recovery escape hatch.

Operator-only plan assignment is available inside the API container:

```powershell
'{"workspace_id":"REPLACE_WITH_ID","plan":"team"}' | docker compose exec -T api python -m quarry.admin set-plan
```

This changes scheduling weight only. It does not collect payments, raise token caps, or grant a latency SLA. Never accept an unverified browser-provided plan or webhook entitlement. A future payment adapter needs verified signatures, deduplicated event IDs, atomic entitlement updates and reconciliation; no payment gateway is currently integrated or contacted.

## Recovery and data protection

`python scripts/manage.py backup` temporarily stops API/workers, makes a PostgreSQL custom-format dump and a ZIP of active private source objects, records SHA-256 checksums, then restarts the services. Backup payloads stay under ignored `.runtime/backups`. Copy them securely off-host and retain the session/encryption configuration separately. These local files are not encrypted at rest by the script; use encrypted host storage and encrypted backup transport/storage. A successful same-host rehearsal is not a complete disaster-recovery program.

`python scripts/manage.py restore-test` creates a new backup and restores it into the separate `quarry-restore` Compose project. It restores database DML grants, verifies object hashes, rebuilds the vector index from durable sources, and executes a cited research query. It uses new storage volumes and port 3001, with Mailpit at 8026. Primary data is never overwritten. Restore volumes persist for inspection; stop them with `docker compose --project-name quarry-restore -f compose.yaml -f infra/restore.compose.yaml down`. Delete rehearsal volumes only after checking their exact names and ensuring they are not primary volumes.

Backups contain account hashes, source content, sessions and checkpoints. Never attach them to public issues or commit them. In production use PostgreSQL PITR and off-host copies; define RPO/RTO from measured restore time and replication behavior. The quiesced script intentionally trades availability during backup for a simple, consistent local snapshot. It does not claim zero-downtime backups or multi-zone failover.

`python scripts/manage.py retention` is a dry run. To apply the documented 30-day research snapshot redaction and 90-day event/audit/job cleanup:

```powershell
docker compose exec -T api python -m quarry.admin retention --apply
```

Retention also removes expired sessions, API keys, verification records and sealed mail, and clears expired pending MFA secrets. Original documents are retained until explicit deletion; superseded source versions count against storage until removed. Deletion excludes sources immediately and schedules physical cleanup. Inspect dead cleanup jobs if capacity does not return. Backup copies have their own retention policy and are not retroactively scrubbed by deleting a live source.

## Scaling and incident diagnosis

APIs and workers can scale independently without copying local application state:

```powershell
docker compose up -d --no-deps --scale api=2 --scale worker=4 api worker
```

The Docker network resolves the API service to its replicas; new connections distribute across them. Existing keep-alive connections can remain on one replica. A production edge/load balancer needs health-aware balancing and connection limits. Model memory is per process; adding workers increases memory and CPU contention. A separate model-serving pool is an option after measuring the bottleneck, not a free throughput multiplier.

Health: `/health/live` and dependency-aware `/health/ready` are internal. `/metrics` is internal and not proxied by the public BFF. It exposes HTTP counters/histograms plus durable shared job counts, oldest pending age, five-minute completion rate, provider failure counts and phase mean durations. Shared gauges should be scraped from one elected endpoint or deduplicated; summing identical shared-state snapshots across API replicas would double-count. Request/job IDs and exception classes appear in structured events without provider keys or source bodies.

If queue age rises, compare admitted arrival rate, completions, downstream latency and memory before increasing replicas. Inspect pending/running/dead jobs and the lease timestamps. A killed worker's lease expires and another worker claims a new fencing token. Do not manually mark a running job done or change its fence to make a stale result commit. Retries are bounded; failed ingestion has a visible retry action. Provider 429 pauses instead of using another service. A selected alternative creates a linked continuation; the original run remains attributable to its original provider.

Security and functional checks intentionally fail closed. `publish` accepts only current source-bound successful reports, the correct GitHub account and local author/committer. Review unresolved findings and update dependencies; do not edit report status or add scanner ignores merely to obtain a green release. The image scanner's raw reports distinguish package presence from exploitability in this deployment. A qualified independent assessment is still required before internet exposure.

## Prepared HTTPS deployment overlay

`infra/production.compose.yaml` and `infra/Production.Caddyfile` provide a prepared HTTPS edge with persistent free ACME certificates and independently scalable API/worker services. This overlay has not been deployed to the internet. Configure the real HTTPS application origin, hostname, operator email, private credentials and a STARTTLS mail service in a separately secured environment before selecting it. It removes the default mail sink from startup and disables demo accounts. Review it with the threat model; it does not create a cloud account, buy infrastructure or collect payments.

The checked local runtime currently targets Linux amd64, matching the Docker Desktop verification host. Native model wheels, copied shared libraries and image digests must be revalidated before an ARM64 release.

## Container maintenance

The default stack builds patched free supporting images from pinned upstream inputs. See `THIRD_PARTY.md` and the Dockerfiles for archive hashes, upstream versions, Go module changes, and license records. Scan all eight image families after changing them. Qdrant is an API-only runtime; its optional dashboard and shell-based OOM recovery mode are not included. Compose restart policy restarts a terminated server, and application indexing/retrieval readiness is checked independently. Update the pinned inputs deliberately and repeat integration, restore and image checks. The retained legacy MinIO profile is for the already documented rollback only; it is stopped and is not an approved public deployment option.

The supplied GitHub Actions workflow is configured but has not been executed on GitHub. Source builds can require substantially more disk than the final runtime images; verify runner memory/disk capacity before interpreting CI readiness. A free self-hosted runner with the tested local capacity is an option. Local passing reports do not establish that a hosted CI run has passed.
