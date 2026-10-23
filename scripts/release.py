"""Release evidence binds checks to the executable source, never to secrets or generated reports."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITICAL = ["accounts", "agent", "api", "capacity", "config", "encoders", "ingest", "metrics", "network", "parse_document", "parser_service", "providers", "queue", "retrieval", "schemas", "security", "storage", "tools", "worker"]
SKIP = {"node_modules", ".next", "__pycache__", ".pytest_cache", ".ruff_cache", "results", "assets"}


def fingerprint():
    digest = hashlib.sha256()
    paths = []
    for name in ["backend", "frontend", "infra", "scripts", "security", ".github", "evaluation"]:
        # Prune before descent: traversing node_modules/.next on a Windows bind mount
        # can take minutes even though those files never contribute to the digest.
        for folder, directories, files in os.walk(ROOT / name):
            directories[:] = [d for d in directories if d not in SKIP]
            paths.extend(p for filename in files if (p := Path(folder) / filename).suffix
                         not in {".pyc", ".log", ".tsbuildinfo"} and filename != ".coverage")
    paths.extend(ROOT / name for name in ["compose.yaml", ".dockerignore", ".env.example", ".gitignore", ".gitattributes"])
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        payload=path.read_bytes()
        # Functional source fingerprints are stable across Windows/Unix text checkouts.
        # Frozen dataset integrity is separately checked against its exact original bytes.
        if b'\0' not in payload:
            payload=payload.replace(b'\r\n',b'\n')
        digest.update(payload)
    return digest.hexdigest()


def coverage_gate():
    data = json.loads((ROOT / "evaluation/results/coverage.json").read_text(encoding="utf-8"))
    rows = []
    for name in CRITICAL:
        value = data["files"]["quarry/" + name + ".py"]["summary"]
        rows.append({"module": name, "covered": value["covered_branches"], "total": value["num_branches"]})
    covered, total = sum(r["covered"] for r in rows), sum(r["total"] for r in rows)
    result = {"status": "passed" if covered / total >= .9 else "failed", "scope": "Aggregate branches across explicitly listed request, authorization, queue, agent, retrieval and provider modules; operator/evaluation CLIs excluded. This is not per-file coverage.", "covered": covered, "total": total, "percent": round(100 * covered / total, 3), "modules": rows}
    (ROOT / "evaluation/results/critical-coverage.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
