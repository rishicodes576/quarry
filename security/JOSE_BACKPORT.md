# JOSE RSA parsing security backport

The 28 October database refresh identified [GHSA-mgcc-cww5-fp2q / CVE-2026-116587](https://github.com/go-jose/go-jose/security/advisories/GHSA-mgcc-cww5-fp2q) in the gateway and object-store dependency graphs. The failed CI and raw image reports remain audit history.

Both image builds explicitly upgrade JOSE v4 to the upstream **v4.1.6** security release. Caddy's Smallstep dependency also requires JOSE v3.0.5; no patched v3 release was available when this backport was prepared. This is a local security modification, not an upstream v3 release or a claim that all vulnerabilities are absent.

The v3 build backports the applicable security changes from upstream commit [`a0111f82742fa92bceec9ede40845e73319e6230`](https://github.com/go-jose/go-jose/commit/a0111f82742fa92bceec9ede40845e73319e6230):

- Reject RSA moduli above 4096 bits before private-key validation.
- Check prime bit lengths before multiplication and require `p * q == n` before validation.
- Reject embedded private JWK/ephemeral-key parameters before certificate or private-key computation; retain legitimate standalone private JWK/JWKS parsing.
- Sanitize general JWS unprotected headers before exposing them, and avoid echoing private JWK/merged-header contents in errors.

The v4 algorithm-allowlist API is not transplanted into v3's different public API. The unrelated v4 JWE key-length change is also outside this security backport. Direct standalone JWK parsing still accepts private keys by design and must not be used on arbitrary untrusted private keys.

`jose-v3-backport.json` records exact upstream and patched file hashes and each replacement. The build fails on any source/context/hash mismatch, runs the complete upstream v3 module test suite plus Quarry regressions with a timeout, and compiles the gateway against that same local module. Original Apache-2.0 headers and license are retained. The image includes patched files, manifest, module graph, build test log and executable regression probe for inspection.

The security gate must verify the exact built image, patch hashes and bounded executable regressions. Any version-based scanner finding remains visible; only this exact advisory/package with this verified backport can receive a disposition. Other findings fail normally. Replace the backport with an upstream maintained dependency when available, after repeating these checks.

Tests and probe compilation run from Caddy's root module with `-mod=readonly`, using its selected dependency graph, rather than the older standalone JOSE test dependency versions. The selected modules and test import graph are retained in the image. Go test-binary metadata does not expose its complete dependency inventory to version scanners; the explicit graph/provenance checks supplement the scan rather than claiming that missing metadata proves absence of vulnerabilities.

Build and regression execution are acceptance requirements. This document describes the mechanism; executed reports determine whether it passed.
