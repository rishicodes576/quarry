"""Independent AI URL/address negative probe. Synthetic DNS only; no sockets/database."""

import json
import pathlib
import subprocess

from component_loader import module_namespace

ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMIT = "9e7833d6ae90c27c0d5338da22855524bc4047bd"
source = subprocess.check_output(
    ["git", "show", COMMIT + ":backend/quarry/network.py"],
    text=True,
    encoding="utf-8",
    cwd=ROOT,
)
namespace = module_namespace(source)
checks = []
for value in [
    "http://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::ffff:127.0.0.1]/",
    "http://10.0.0.1/",
    "http://127.0.0.1.nip.io/",
]:
    parsed, host = namespace["validate_url"](value)
    address = {"127.0.0.1.nip.io": "127.0.0.1"}.get(host, host)
    namespace["socket"].getaddrinfo = lambda *args, addr=address, **kwargs: [
        (2, 1, 6, "", (addr, 80))
    ]
    try:
        namespace["public_addresses"](host, 80)
        blocked = False
    except namespace["FetchError"]:
        blocked = True
    checks.append({"url": value, "blocked": blocked})
for value in [
    "file:///etc/passwd",
    "http://user:pass@example.org/",
    "http://example.org:8080/",
    "https://example.org/\r\nInjected:x",
]:
    try:
        namespace["validate_url"](value)
        blocked = False
    except namespace["FetchError"]:
        blocked = True
    checks.append({"url": value, "blocked": blocked})
result = {
    "reviewed_commit": COMMIT,
    "probe": "original URL/address functions with synthetic DNS answers; no network or database",
    "checks": checks,
    "status": "passed" if all(check["blocked"] for check in checks) else "failed",
}
(ROOT / "evaluation/results/independent-review-ssrf.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(json.dumps(result))
raise SystemExit(0 if result["status"] == "passed" else 1)
