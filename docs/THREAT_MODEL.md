# Security and trust model

Assets are source documents, workspace membership, account credentials, research evidence, provider keys, finite compute/storage capacity, and the integrity of exported findings. Untrusted actors include public signup users, another workspace's members, stolen browser sessions or machine keys, malicious source authors and public web servers. Operators and the Docker host are trusted; a compromised host can read local configuration and volumes.

| Boundary / attack | Implemented control | Evidence / remaining limit |
|---|---|---|
| Account takeover | Argon2id (19 MiB, three iterations), bounded verification concurrency, 15–128-character passphrases, uniform unknown-user hashing, shared per-address and per-email throttles | Real auth tests; blocklist is intentionally small, no breached-password service |
| Public signup / recovery | No account before verification; opaque HMAC-stored 30-minute one-use tokens, atomic redemption; generic email responses, encrypted durable SMTP outbox | Browser uses actual local SMTP capture; real internet SMTP/DNS delivery is not exercised |
| MFA bypass / replay | Encrypted TOTP secret, setup expiry, monotonically consumed steps, one-use hashed recovery codes; credential changes revoke sessions and machine keys | Integration tests include replay and recovery reuse; no WebAuthn/passkey implementation |
| Session theft / CSRF | HttpOnly SameSite=Lax opaque cookie, absolute and idle expiry, server-side revocation, secure production cookie, same-origin mutation enforcement in BFF and API | Production requires HTTPS; local HTTP is loopback only; same-origin XSS would still be serious |
| Machine credential theft | Expiring read/write scope, key returned once, HMAC storage, user-role attenuation, per-key throttle, no account/admin access | Server integration credentials only; invalid bearer cannot fall back to a cookie |
| Tenant escape / IDOR | Every resource lookup includes workspace, server-side roles, SQL and Qdrant eligibility filters, authorization on source downloads, exports, events and SSE rechecks | Cross-workspace and viewer write tests; one workspace per user in this version |
| Prompt injection | Sources treated as inert untrusted data, fixed bounded tools, no shell/Python execution tool, explicit evidence-only generation, reference validation | Hostile-source test cases and tool tests; prompts do not prove semantic immunity or factual correctness |
| SSRF / rebinding | HTTP(S) public-address allowlist, DNS answers checked then pinned to sockets, original TLS SNI, redirects revalidated, restricted ports, response and time limits | Tests exercise DNS replacement, private redirects and unsupported schemes; trusted internal SearXNG is separate |
| Uploaded parser abuse | Size/character/page limits; scanned/encrypted PDF errors; credentialless networkless parser container plus bounded child with Linux memory/CPU/file limits and minimal environment | Test corrupt/oversized PDFs and child timeout/crash. No OCR; container/child isolation is not a per-document security VM |
| Script injection | Plain-text source rendering; no raw HTML execution; nonce CSP, frame blocking, no script eval/inline permission | Browser tests watch CSP and exercise hostile snippets; source Markdown exports remain untrusted when opened in other tools |
| Resource exhaustion / noisy neighbor | Shared and workspace queue/storage caps, server plan weights, fair dispatch, bounded provider and token reservations, global concurrency limit | Concurrent database/service tests and separate load artifacts; signups still need edge abuse monitoring/CAPTCHA at large public scale |
| Worker races / stale writes | Lease expiry, heartbeat, random fencing, row locks, deterministic indexing, checkpoint guards, cancellation at commit | Real-service recovery tests; external SMTP/model calls remain at-least-once or ambiguous across crashes |
| Dependency compromise | Hash-locked Python dependencies, npm lockfile, image digests, public scanner reports, least-privilege runtime | Scanners have finite coverage. Known base-image/storage findings block a clean public release; see audit |
| Secret leakage | Server-only environment whitelist, ignored `.env`/backups, redacted errors, no raw provider errors, fragment email tokens, encrypted outbox, no browser traces in deliverables | Logs contain IDs and exception classes; Docker-host administrators remain trusted |

## Production gate

Do not expose the local demonstration stack by binding it to all interfaces or opening a tunnel. Configure a real HTTPS origin, secure cookies, no demo account, verified STARTTLS SMTP, private storage/vector credentials, a supported maintained S3 implementation, least-privilege bucket policy, encrypted off-host backups and restoration drills. Apply outbound network policy independently of application SSRF checks. Restrict database and storage administration to operators. Terminate public TLS at a trusted edge which overwrites client-IP headers; never trust an arbitrary forwarded header from the internet.

The source review used [Vibe Security](https://github.com/raroque/vibe-security-skill/blob/main/vibe-security/SKILL.md) and the [vibe-check checklist](https://github.com/benavlabs/vibe-check). Their recommendations were reviewed as external reference material; neither repository was executed as trusted code. Findings are substantiated separately by tests and scanners. No report claims the project is vulnerability-free.

## Reporting and response

Report security issues privately to the repository maintainer. Include the affected version, authenticated role, prerequisites and a minimal reproduction without private documents or keys. Rotate exposed credentials, revoke affected sessions/API keys, stop public admission if tenant isolation is uncertain, preserve redacted event evidence, and restore only after the root cause and regression checks are established. Rotation of the master session secret also makes encrypted MFA/outbox data unreadable; plan a controlled re-enrollment and mail reissue rather than blindly changing it.

## Additional verified boundaries

Production authentication rejects persisted demonstration accounts as well as preventing new demo seeding. Request body admission is bounded at both the Next.js proxy and API before buffering mutation bodies; saturation returns a retryable response. These bounds protect process memory and complement shared PostgreSQL admission quotas. Optional evaluation dependencies retain raw advisory findings but have the affected URL/file-loading and pickle-reading capabilities removed in the separate evaluator image; see `security/EVALUATOR_MITIGATIONS.md` and its exploit-negative checks. They are absent from the production backend.


## JOSE parsing and evidence integrity (28 October 2026)

Crafted RSA JWKs can exhaust CPU during private-key validation (CVE-2026-116587). Storage and gateway v4 dependencies are pinned to the upstream fixed release. The remaining gateway v3 dependency uses the exact source-hash-checked upstream security backport documented in [JOSE_BACKPORT.md](../security/JOSE_BACKPORT.md). Modulus/prime checks precede expensive validation; untrusted embedded private material rejects before private-key or certificate work, and errors do not echo private header contents. The original package version/finding remains disclosed.

The diagnostic executable and gateway are compiled under the same read-only selected module graph. Full upstream tests, bounded positive/adversarial probes, exact saved-image configuration and patch/import/source hashes constrain the disposition to those two executables and this one advisory/package/version. Other findings fail. This is a maintained local backport, not an upstream v3 release or assurance against unknown native-code flaws.

A failed, partial or interrupted security recheck must not leave an old success usable as current evidence. Scan startup marks the full gate incomplete, final full success requires every step, and truncated import-graph artifacts reject before inclusion checks. Independent AI review and builder-executed scans/tests are separately attributed; neither is human certification. Raw failed reports are retained for audit history.
