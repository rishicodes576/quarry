# Third-party software and model notices

Quarry's original application code uses the root MIT license. Independently distributed dependencies, containers and model weights retain their own licenses. Their authors are not claimed as authors of Quarry's original code, and their notices must not be removed.

| Component | License / provenance |
|---|---|
| Next.js, React, TypeScript, Lucide | MIT / ISC; exact versions in `frontend/package-lock.json`, upstream notices retained in package distributions |
| FastAPI, SQLAlchemy, Alembic, Pydantic | MIT; hash-locked exact versions in `backend/requirements.lock` |
| LangGraph and PostgreSQL checkpoint library | MIT; tracing disabled by default, self-hosted persistence |
| ONNX Runtime | MIT; upstream wheel license metadata retained in image |
| Tokenizers, Hugging Face Hub, Qdrant client/server | Apache-2.0 |
| PostgreSQL | PostgreSQL License |
| SeaweedFS 4.48 | Apache-2.0; source [release 4.48](https://github.com/seaweedfs/seaweedfs/tree/4.48), [license copy](docs/licenses/seaweedfs-LICENSE); a checksum-pinned source rebuild updates `golang.org/x/net` to v0.60.0 and uses Go 1.26.10 in a separate local container; the modified go.mod/go.sum are retained in its image |
| SearXNG | AGPL-3.0; separate container, public upstream source [searxng/searxng](https://github.com/searxng/searxng); preserve its image/source notices and obligations when distributing or modifying |
| Caddy | Apache-2.0; checksum-pinned upstream source with JOSE v4.1.6 and a hash-checked upstream security backport to its JOSE v3 dependency; [patch provenance and verification](security/JOSE_BACKPORT.md). Original JOSE [Apache-2.0 license](docs/licenses/go-jose-LICENSE) is retained in this source distribution and the image; modified files retain upstream copyright headers. |
| Mailpit | MIT |
| MinIO (legacy migration profile only) | AGPL-3.0; final public source release `RELEASE.2025-10-15T17-29-55Z`; [license](docs/licenses/minio-LICENSE) and [notice](docs/licenses/minio-NOTICE) retained. Archived vulnerable storage is not the new runtime default. Keep license/source obligations if redistributing the legacy image. |
| Python and OS runtime libraries | PSF and individual package licenses; `/usr/share/doc` and shared-library package provenance retained in the backend image |
| Ragas, Instructor, OpenAI SDK | Apache-2.0 / MIT; optional evaluation dependencies. SDK compatibility does not imply use of a paid service. |
| Semgrep, Trivy, OWASP ZAP, Playwright | Separate free scanner/test distributions; pinned images in source, upstream licenses apply |

Model weights are downloaded from pinned revisions on first startup; weights are not bundled into the source ZIP:

| Use | Repository / immutable revision | License |
|---|---|---|
| Dense MiniLM | `Qdrant/all-MiniLM-L6-v2-onnx` / `d13954661f83248295ba75c1ed411eef3b7b936e` | Apache-2.0 |
| MS MARCO cross-encoder | `Xenova/ms-marco-MiniLM-L-6-v2` / `a09144355adeed5f58c8ed011d209bf8ee5a1fec` | Apache-2.0 |
| BM25 English assets | `Qdrant/bm25` / `22b8d2af71a76161e18dd432d2cee0eefa66e412` | Apache-2.0 |

The model cache retains upstream license/model-card files where supplied. Exact file hashes and declared model licenses are preserved in each benchmark artifact. The underlying dense and reranker model families are `sentence-transformers/all-MiniLM-L6-v2` and `cross-encoder/ms-marco-MiniLM-L-6-v2`; ONNX repositories provide their conversion artifacts.

Original sample documents and relevance labels are synthetic engineering examples. The private resume, interview transcript and screenshot supplied during development are not distributed with the project. No external blog or interview content was copied into the synthetic corpus.

## Supporting container security rebuilds

The Caddy 2.11.7 (Apache-2.0), gosu 1.19 (Apache-2.0), and Mailpit 1.31.6 (MIT) source archives are checksum-pinned in `infra/*Dockerfile` and rebuilt with Go 1.26.10. Caddy's x/net dependency is explicitly updated to v0.60.0. Their upstream license texts and resulting Go module manifests are included in the built images. Mailpit retains its upstream third-party notice file and builds its UI from its committed npm lockfile. PostgreSQL itself is unchanged; its gosu privilege-drop helper is rebuilt, and its Alpine Brotli library is explicitly updated to `1.2.1-r0` for CVE-2026-111497. Caddy runs on a digest-pinned minimal Alpine image with CA certificates, omitting the affected unused Brotli/curl dependency chain from its prior runtime. Actual package inventories and scan results remain in the image reports.

The Qdrant 1.20.0 image retains the unmodified upstream server binary, configuration and necessary dynamic libraries. Its dashboard and unrelated OS utilities are omitted. A package inventory and library copyright notices are retained for the actual copied runtime libraries; the Apache-2.0 Qdrant license is in `docs/licenses/qdrant.LICENSE` and the image. The upstream entrypoint's optional OOM recovery script is omitted: the server is PID 1, handles termination directly, and Compose restarts it on exit. No automatic recovery-mode claim is made. SearXNG retains its upstream image and license notices with the checksum-pinned certifi 2026.10.19 wheel replacing the vulnerable certificate bundle. Search runs as the upstream unprivileged UID 977.

Copies of the installed core frontend package notices are also preserved in [frontend notices](docs/licenses/frontend-notices.txt). The exact dependency graph remains in the npm lockfile; transitive package distributions retain their own notices.
