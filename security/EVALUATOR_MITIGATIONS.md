# Optional evaluator dependency security assessment

The production API/worker image does not install Ragas or DiskCache. They are optional dependencies in the separate, operator-run evaluation image. The evaluator validates frozen authored data hashes and is not exposed through a public API. No untrusted user can choose its metric implementation or cache directory through Quarry.

The upstream package versions remain `ragas==0.4.3` and `diskcache==5.6.3`. Do not rename their versions, delete advisory records, or claim a zero-finding dependency audit. At verification time the public package index supplies no fixed versions for these two advisories. Raw pip-audit JSON and its nonzero exit code are preserved.

| Advisory | Vulnerable behavior | Actual application patch |
|---|---|---|
| CVE-2026-6587 / PYSEC-2026-3046 | Multimodal faithfulness utilities fetch arbitrary URLs and read local files | The three multimodal image/URL/file entry points are replaced with unconditional errors in the optional image. Quarry supports text-only evaluation. |
| CVE-2025-69872 / PYSEC-2026-2447 | Cache-controlled pickle data can execute code during deserialization | All three DiskCache pickle read sites are replaced with unconditional errors. Primitive non-pickle cache operations remain available. Quarry's metrics do not enable a disk cache. |

`infra/harden_eval.py` requires the exact original SHA-256 of both pinned upstream files before patching, retains their original content except the disabled capabilities, adds a prominent modification notice and records before/after hashes in `/usr/local/share/quarry/eval-hardening.json`. Upstream license metadata remains in the image. A dependency change fails the patch until it is reviewed; there is no blind best-effort rewrite.

`python -m quarry.eval_guard` runs inside that actual image. It verifies the modified source hashes, confirms that metadata/private URLs and local file attempts raise before a mocked network/open call, attempts inline/file/key cache deserialization using an executable sentinel, confirms no sentinel executed, and checks a safe primitive cache operation. Its evidence is `evaluation/results/security/eval-mitigations.json`.

The release gate accepts **only** these exact package/version/advisory tuples when the patched-image checks pass. Any additional advisory, unexpected package version, missing fresh audit, failed patch/hash or executed sentinel fails the gate. No `--ignore-vuln` option is used. This is an application-maintained mitigation with disabled functionality, not an upstream fix or an assertion that the general-purpose packages are safe.

Remove these patches when an upstream fix is available, update the lockfile, and rerun the negative checks plus text-metric compatibility tests. Multimodal evaluation or general pickle caching must not be enabled by configuration around this policy. Maintainers assume responsibility for reviewing this local dependency patch during upgrades.
