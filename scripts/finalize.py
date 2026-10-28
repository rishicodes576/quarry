"""Standard-library release assembly. No provider calls, commits, or publication."""

import argparse
import csv
import fnmatch
import hashlib
import io
import json
import re
import subprocess
import tarfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.parsers import expat

from release import ROOT, SKIP, fingerprint

IDENTITY = "Rishab Chetal|rishabchetal@gmail.com|Rishab Chetal|rishabchetal@gmail.com"
PATTERNS = [re.compile(rb"(?:gsk_|sk-proj-|gho_|github_pat_)[A-Za-z0-9_-]{20,}"), re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")]


def read(name):
    path = ROOT / "evaluation/results" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def current_inputs(report, *, isolated=False):
    inputs = report.get('input_sha256', {})
    if not inputs:
        return False
    if isolated:
        required = {f'isolated-v2-{mode}{suffix}.json' for mode in ('dense','bm25','hybrid','hybrid_rerank') for suffix in ('','-verdicts','-research')}
        if not required <= set(inputs):
            return False
    elif 'results/live-ragas.json' not in inputs:
        return False
    for name, expected in inputs.items():
        if isolated:
            if Path(name).name != name:
                return False
            path = ROOT/'evaluation/results'/name
        else:
            path = ROOT/'evaluation'/name
            if not path.resolve().is_relative_to((ROOT/'evaluation').resolve()):
                return False
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def current_protocols():
    required = {'agent.py','providers.py','retrieval.py','encoders.py','tools.py','live_eval.py','campaigns.py','campaign_runner.py','model_assets.py','eval_guard.py'}
    for mode in ('dense','bm25','hybrid','hybrid_rerank'):
        report = read('isolated-v2-'+mode+'.json')
        definition = report.get('protocol_definition', {})
        files = definition.get('implementation_sha256', {})
        if set(files) != required:
            return False
        for name, expected in files.items():
            path = ROOT/'backend/quarry'/name
            if hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
                return False
        scorer = definition.get('scorer_files_sha256', {})
        for name, path in {'requirements.lock':ROOT/'backend/requirements.lock','requirements-eval.lock':ROOT/'backend/requirements-eval.lock','harden_eval.py':ROOT/'infra/harden_eval.py'}.items():
            if hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest() != scorer.get(name):
                return False
    return True


def passed_junit(path):
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('JUnit report exceeds release bounds')
    parser=expat.ParserCreate()
    passed, current = [], []
    def reject(*_):
        raise ValueError('JUnit DTD/entity declarations are forbidden')
    def start(name, attributes):
        if name == 'testcase':
            current.append([attributes.get('classname','')+'.'+attributes.get('name',''),True])
        elif name in {'failure','error','skipped'} and current:
            current[-1][1]=False
    def end(name):
        if name == 'testcase' and current:
            record=current.pop()
            if record[1]:
                passed.append(record[0])
    parser.StartDoctypeDeclHandler=reject
    parser.EntityDeclHandler=reject
    parser.ExternalEntityRefHandler=lambda *_:0
    parser.StartElementHandler=start
    parser.EndElementHandler=end
    parser.Parse(path.read_bytes(),True)
    return passed


def readiness():
    source = fingerprint()
    definitions = json.loads((ROOT / "evaluation/requirements.json").read_text(encoding="utf-8"))
    verification, security = read("verification.json"), read("security/summary.json")
    verified = verification.get("status") == "passed" and verification.get("source_sha256") == source
    secured = security.get("status") == "passed" and security.get("source_sha256") == source
    junit = ROOT / "evaluation/results/backend-junit.xml"
    passed = []
    if junit.exists() and verified and hashlib.sha256(junit.read_bytes()).hexdigest() == verification.get('backend_junit_sha256'):
        passed=passed_junit(junit)
    checks = []
    for item in definitions:
        if item.get("owner_dependency"):
            status, reason = "deferred_owner", item["owner_dependency"]
        elif item.get("tests"):
            matches = [[p for p in passed if fnmatch.fnmatchcase(p, pattern)] for pattern in item["tests"]]
            status = "passed" if verified and all(matches) else "incomplete"
            reason = f"{sum(map(len, matches))} matching successful JUnit executions; current source required"
        else:
            artifact = read(item["artifact"])
            status = "passed" if artifact.get(item.get("status_field", "status")) == item.get("expected", "passed") else "incomplete"
            if item.get("source_bound") and artifact.get("source_sha256") != source:
                status = "incomplete"
            reason = item["artifact"]
        checks.append({**item, "status": status, "acceptance": reason})
    isolated, arithmetic, legacy = read("isolated-mathematical-audit.json"), read("mathematical-audit.json"), read("live-ragas.json")
    legacy_current = current_inputs(arithmetic)
    isolated_current = current_inputs(isolated, isolated=True) and current_protocols()
    checks.extend([
        {"id": "current-functional-gate", "requirement": "Current complete functional/browser/coverage gate", "status": "passed" if verified and passed else "incomplete"},
        {"id": "current-security-gate", "requirement": "Current complete security gate", "status": "passed" if secured else "incomplete"},
        {"id": "legacy-37", "requirement": "Original 37/37 preserved campaign", "status": "passed" if legacy.get("status") == "completed" and arithmetic.get("live_complete") and legacy_current else "incomplete"},
        {"id": "isolated-148", "requirement": "All four modes and 148 isolated evaluations with audited provenance", "status": "passed" if isolated.get("status") == "passed" and isolated.get("complete") and isolated.get("completed") == 148 and isolated_current else "incomplete"},
    ])
    worksheet = ROOT / "evaluation/results/isolated-factual-support-review.csv"
    reviewed = []
    if worksheet.exists():
        with worksheet.open(newline="", encoding="utf-8") as handle:
            reviewed = list(csv.DictReader(handle))
    expected_claims = isolated.get('expected_claim_reviews', {})
    actual_claims = {f"{r['mode']}|{r['case_id']}|{r['claim_number']}":r for r in reviewed}
    support_done = bool(expected_claims) and len(reviewed) == len(actual_claims) and set(actual_claims) == set(expected_claims)
    if support_done:
        for key, row in actual_claims.items():
            # CSV round trips stringify the original integer verdict.
            try:
                bound = {name:row[name] for name in ('claim','model_reason','context_sha256')}
                bound['model_verdict'] = int(row['model_verdict'])
                digest = hashlib.sha256(json.dumps(bound,sort_keys=True).encode()).hexdigest()
                if digest != expected_claims[key] or row.get('assistant_support_decision') not in {'supported','unsupported','uncertain'} or not row.get('assistant_review_note','').strip() or not row.get('assistant_reviewer','').strip():
                    support_done = False
            except (KeyError,ValueError):
                support_done = False
    answers = ROOT / "evaluation/results/isolated-answer-review.csv"
    answer_reviews = []
    if answers.exists():
        with answers.open(newline="", encoding="utf-8") as handle:
            answer_reviews = list(csv.DictReader(handle))
    expected_answers = isolated.get('expected_answer_reviews', {})
    actual_answers = {f"{r['mode']}|{r['case_id']}":r for r in answer_reviews}
    answers_done = len(answer_reviews) == len(actual_answers) == len(expected_answers) == 148 and set(actual_answers) == set(expected_answers)
    if answers_done:
        answers_done = all(all(row.get(name) == expected_answers[key][name] for name in ('answer_sha256','context_sha256')) and row.get('answer_review_complete') == 'yes' and row.get('unlisted_claims_reviewed') == 'yes' and row.get('assistant_reviewer','').strip() and row.get('support_summary','').strip() for key,row in actual_answers.items())
    checks.append({"id": "factual-support", "requirement": "Attributed claim and complete-answer support review, including claims omitted by model decomposition", "status": "passed" if support_done and answers_done and isolated.get("complete") and isolated_current else "incomplete"})
    result = {"status": "complete" if all(c["status"] in {"passed", "deferred_owner"} for c in checks) else "incomplete", "created_at": datetime.now(UTC).isoformat(), "source_sha256": source, "checks": checks, "backend_cases_passed": len(passed), "legacy_completed": sum(len(r["metrics"]) == 3 for r in legacy.get("rows", [])), "isolated_completed": isolated.get("completed", 0), "provider_calls": 0, "limitations": "Finite local verification and assistant review; no human certification or vulnerability-free claim"}
    (ROOT / "evaluation/results/release-readiness.json").write_text(json.dumps(result, indent=2), encoding="utf-8", newline="\n")
    return result


def render(result):
    rows = ["# Current audited release status", "", f"Status: **{result['status']}**. Source: `{result['source_sha256']}`.", "", f"Legacy campaign: **{result['legacy_completed']}/37**. Isolated paired comparisons: **{result['isolated_completed']}/148**. Successful backend cases with current JUnit evidence: **{result['backend_cases_passed']}**.", "", "| Requirement | Acceptance | Evidence |", "|---|---|---|"]
    for item in result["checks"]:
        rows.append(f"| {item['requirement']} | {item['status']} | {item.get('acceptance', 'release-readiness.json')} |")
    rows += ["", "Installation prerequisites are recorded in operational guidance; verified mail transport and public application acceptance are separate checks. Free quota waits remain unfinished work. Historical reports are retained; they do not override this current status. Known evaluator advisories and tested mitigations remain disclosed. No public deployment or human certification is implied.", ""]
    (ROOT / "docs/RELEASE_STATUS.md").write_text("\n".join(rows), encoding="utf-8", newline="\n")
    path = ROOT / "README.md"
    text = path.read_text(encoding="utf-8")
    replacement = f"**Current release status: {result['status']}.** Legacy campaign {result['legacy_completed']}/37; isolated comparisons {result['isolated_completed']}/148. See [the requirement-by-requirement acceptance report](docs/RELEASE_STATUS.md). Installation requirements and verification limits are recorded in the operational guidance."
    text = re.sub(r"^\*\*(?:Historical local release checks passed:|Local release checks passed:|Current release status:).*?$", lambda _: replacement, text, flags=re.M)
    path.write_text(text, encoding="utf-8", newline="\n")


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def secret_values():
    paths = [ROOT / ".env", *(ROOT / ".runtime").rglob("*.env")]
    values = []
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            if len(value) >= 12 and any(term in key for term in ("KEY", "SECRET", "PASSWORD", "DATABASE_URL")):
                values.append(value.encode())
    return values


def check_payload(name, payload, secrets):
    parts = Path(name).parts
    if (Path(name).is_absolute() or ".." in parts or set(parts) & {".runtime", ".git", "node_modules", ".next", "__pycache__"}
            or (Path(name).name.startswith(".env") and Path(name).name != ".env.example")):
        raise ValueError("Private or unsafe archive path: " + name)
    if any(value in payload for value in secrets) or any(pattern.search(payload) for pattern in PATTERNS):
        raise ValueError("Credential audit failed in " + name)


def audit_candidates():
    # Only the known public project roots may enter a new source archive.
    allowed_roots = {"backend", "frontend", "infra", "scripts", "security", ".github", "evaluation", "docs"}
    allowed_files = {"README.md", "LICENSE", "THIRD_PARTY.md", "compose.yaml", ".gitignore", ".dockerignore", ".gitattributes", ".env.example"}
    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    secrets = secret_values()
    for name in filter(None, files):
        path = ROOT / name
        if not path.exists():
            continue
        if Path(name).parts[0] not in allowed_roots and name not in allowed_files:
            raise ValueError("Unexpected public file; review before packaging: " + name)
        if path.is_symlink() or getattr(path,'is_junction',lambda:False)() or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in path.parents if p.is_relative_to(ROOT)):
            raise ValueError("Source symlinks are not permitted")
        check_payload(name, path.read_bytes(), secrets)
    return secrets


def audit_tree(tree, expected_source):
    secrets = secret_values()
    payloads = {}
    with tarfile.open(fileobj=io.BytesIO(git('archive','--format=tar',tree)), mode='r:') as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError('Archive links or special entries are not permitted')
            payload = archive.extractfile(member).read()
            check_payload(member.name,payload,secrets)
            path=Path(member.name)
            if path.parts[0] not in {'backend','frontend','infra','scripts','security','.github','evaluation','docs'} and member.name not in {'README.md','LICENSE','THIRD_PARTY.md','compose.yaml','.gitignore','.dockerignore','.gitattributes','.env.example'}:
                raise ValueError('Unexpected staged archive path: '+member.name)
            payloads[member.name]=payload
    digest=hashlib.sha256()
    roots={'backend','frontend','infra','scripts','security','.github','evaluation'}
    root_files={'compose.yaml','.dockerignore','.env.example','.gitignore','.gitattributes'}
    for name,payload in sorted(payloads.items()):
        path=Path(name)
        included=name in root_files or (path.parts[0] in roots and not set(path.parts[:-1]) & SKIP and path.parts[:2] != ('evaluation','results') and not any(p.endswith('.egg-info') for p in path.parts[:-1]) and path.suffix not in {'.pyc','.log','.tsbuildinfo'} and path.name != '.coverage')
        if included:
            digest.update(name.encode()+b'\0')
            digest.update(payload.replace(b'\r\n',b'\n') if b'\0' not in payload else payload)
    if digest.hexdigest() != expected_source:
        raise ValueError('Staged source fingerprint does not match verified source')
    return tree


def package(result, *, checkpoint=False):
    if fingerprint() != result['source_sha256']:
        raise ValueError('Source changed after readiness; repeat finalization')
    identities = git("log", "--format=%an|%ae|%cn|%ce").decode().splitlines()
    if not identities or any(identity != IDENTITY for identity in identities) or re.search(rb"co-authored-by:|\bcodex\b", git("log", "--format=%B"), re.I):
        raise ValueError("Commit attribution audit failed")
    secrets = audit_candidates()
    # Stage only after all candidate files passed the credential/scope audit.
    subprocess.run(["git", "add", "--all"], cwd=ROOT, check=True)
    tree = git("write-tree").decode().strip()
    audit_tree(tree,result['source_sha256'])
    if fingerprint() != result['source_sha256']:
        raise ValueError('Source changed during staging; no archive generated')
    target = ROOT.parent / ("quarry-checkpoint.zip" if checkpoint else "quarry-source.zip")
    subprocess.run(["git", "archive", "--format=zip", "--prefix=quarry/", "--output", str(target), tree], cwd=ROOT, check=True)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("Archive CRC failure")
        for name in archive.namelist():
            if not name.endswith("/"):
                check_payload(name.removeprefix("quarry/"), archive.read(name), secrets)
        # Every reported input hash must survive Git's text normalization.
        for report_name in ("mathematical-audit.json", "isolated-mathematical-audit.json"):
            evidence = json.loads(archive.read("quarry/evaluation/results/" + report_name))
            for name, expected in evidence.get("input_sha256", {}).items():
                relative = name if name.startswith("results/") or name in {"cases.json", "corpus.json", "manifest.json"} else "results/" + name
                if hashlib.sha256(archive.read("quarry/evaluation/" + relative)).hexdigest() != expected:
                    raise ValueError("Published evidence hash mismatch: " + name)
    manifest = {"status": result["status"], "archive": target.name, "sha256": hashlib.file_digest(target.open("rb"), "sha256").hexdigest(), "source_sha256": result["source_sha256"], "staged_tree": tree, "base_commit": git("rev-parse", "HEAD").decode().strip(), "new_commit_created": False, "published": False, "legacy_completed": result["legacy_completed"], "isolated_completed": result["isolated_completed"], "secret_audit": "passed", "attribution_audit": "passed"}
    output = ROOT.parent / ("quarry-checkpoint-delivery.json" if checkpoint else "quarry-delivery.json")
    output.write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return manifest


def run(*, checkpoint=False):
    from manage import compose

    # Canonical report bytes match Git's release representation. Frozen source data
    # remains byte-for-byte unchanged (its .gitattributes entries disable conversion).
    for path in (ROOT / "evaluation/results").rglob("*.json"):
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    compose("--profile", "evaluation", "run", "--rm", "--no-deps", "evaluate", "python", "-m", "quarry.metric_audit", "--export-judges")
    compose("--profile", "evaluation", "run", "--rm", "--no-deps", "evaluate", "python", "-m", "quarry.campaign_audit", "--export-judges")
    result = readiness()
    render(result)
    if result["status"] != "complete" and not checkpoint:
        raise SystemExit("Release incomplete; inspect docs/RELEASE_STATUS.md. No final source archive or publication was produced.")
    print(json.dumps(package(result, checkpoint=checkpoint), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", action="store_true")
    run(checkpoint=parser.parse_args().checkpoint)
