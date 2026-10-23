# Independent AI component probes

These small, reviewable harnesses reproduce the independent AI review and verify its corrections. They are diagnostic tools, not a human audit/certification, application runtime, penetration-test framework, or load test. They never connect to Quarry, PostgreSQL, SMTP, model providers, or an external HTTP server. They do not read `.env` or private documents.

Run from a repository checkout using Python 3.11+ and Node.js 22+. The BFF probes additionally require the already pinned frontend development dependencies (`frontend/node_modules/typescript`). They transpile the actual route module into an isolated VM, substitute upstream `fetch`, and exercise inert Web Streams. No browser, API server, Docker stack, or database needs to be running.

```powershell
node security/review-probes/bff-patch.cjs
python security/review-probes/python-patch.py
```

The Python patch probe starts one temporary HTTP server bound only to `127.0.0.1` on an automatically assigned port. It feeds tiny trickled responses to the actual fetch implementation, substitutes synthetic DNS answers and an inert parser spy, then closes the server. A sandbox may require permission for this loopback socket. The DNS timeout is scaled to 0.04 seconds, fetch deadline to 0.12 seconds; the BFF body timeout is scaled from 15 seconds to 50 milliseconds. Tolerances allow normal scheduler jitter; these are correctness probes rather than latency benchmarks. The BFF probe also checks that a second SSE event arrives after the scaled upstream header deadline without aborting an already established stream. A five-second Node watchdog bounds the harness if a later regression leaves streams unresolved.

To reproduce the original findings and the baseline SSRF negative checks, the Git history must contain commit `9e7833d6ae90c27c0d5338da22855524bc4047bd`:

```powershell
node security/review-probes/bff.cjs
python security/review-probes/python.py
python security/review-probes/ssrf.py
```

Baseline probes intentionally demonstrate the old failure mode; they do not assert that current source is still vulnerable. A ZIP without Git history cannot run those baseline commands. The patch probes read the current source directly and include its per-file hashes in their JSON evidence.

Results are written to `evaluation/results/independent-review-*.json`. Running a probe replaces only its own report. The original-module Python probes use the standard module loader and construct the actual function with inert reviewer globals. Only trusted repository source selected by the reviewer is loaded; no downloaded/user-supplied source is executed. The parser spy confirms routing to the isolated entry point, not the strength of the child sandbox. The synthetic SSRF cases do not establish complete DNS-rebinding resistance or test a production network.

For scope, findings, limitations, and release status, read [the independent AI review](../../docs/INDEPENDENT_SECURITY_REVIEW.md). Full Docker integration/browser/scanner checks remain separate evidence.
