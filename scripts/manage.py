"""Portable, standard-library-only Docker orchestrator. Application code runs in containers."""
import argparse
import getpass
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def docker():
    found = shutil.which("docker")
    if not found and sys.platform == "win32":
        candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop/resources/bin/docker.exe",
                      Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")]
        found = next((str(p) for p in candidates if p.exists()), None)
    if not found:
        raise SystemExit("Install Docker Desktop, select Linux containers, and start it. Then run this command again.")
    os.environ["PATH"] = str(Path(found).parent) + os.pathsep + os.environ.get("PATH", "")
    return found


def run(args, *, capture=False, check=True):
    result = subprocess.run(args, cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                            capture_output=capture, check=False)
    if check and result.returncode:
        if capture:
            print(redact(result.stderr))
        raise SystemExit(result.returncode)
    return result


def compose(*args, **kwargs):
    return run([docker(), "compose", *args], **kwargs)


def read_env():
    target = ROOT / ".env"
    return dict(line.split("=", 1) for line in target.read_text().splitlines()
                if line and not line.startswith("#") and "=" in line) if target.exists() else {}


def write_env(values):
    target = ROOT / ".env"
    target.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o600)


def configure():
    if (ROOT / ".env").exists():
        values = read_env()
        if not values.get("QUARRY_PROXY_SECRET"):
            values["QUARRY_PROXY_SECRET"] = secrets.token_hex(32)
            write_env(values)
        return
    values = read_env_template()
    password = secrets.token_hex(24)
    values.update(POSTGRES_PASSWORD=password,
                  QUARRY_DATABASE_URL=f"postgresql+psycopg://quarry_runtime:{secrets.token_hex(24)}@postgres:5432/quarry",
                  QUARRY_QDRANT_API_KEY=secrets.token_hex(32),
                  QUARRY_S3_ACCESS_KEY="quarry" + secrets.token_hex(8),
                  QUARRY_S3_SECRET_KEY=secrets.token_hex(32),
                  QUARRY_SESSION_SECRET=secrets.token_hex(48), SEARXNG_SECRET=secrets.token_hex(32))
    values["QUARRY_PROXY_SECRET"] = secrets.token_hex(32)
    write_env(values)
    print("Created ignored local configuration with random secrets. Paid providers are disabled.")


def read_env_template():
    return dict(line.split("=", 1) for line in (ROOT / ".env.example").read_text().splitlines()
                if line and not line.startswith("#") and "=" in line)


def redact(value):
    for key, secret in read_env().items():
        if len(secret) >= 12 and any(term in key for term in ["KEY", "SECRET", "PASSWORD", "DATABASE_URL"]):
            value = value.replace(secret, "[redacted]")
    return re.sub(r"(?:gsk_|sk-|gho_)[A-Za-z0-9_-]{12,}", "[redacted]", value)


def doctor():
    run([docker(), "info", "--format", "Docker engine: {{.ServerVersion}}"])
    compose("version")


def up():
    doctor()
    configure()
    (ROOT / "evaluation/results").mkdir(parents=True, exist_ok=True)
    compose("config", "--quiet")
    compose('build','api','web','objectstore','gateway','postgres','qdrant','searxng','mailpit')
    from migrate_storage import migrate
    migrate()
    compose("up", "--build", "--detach", "--wait", "--wait-timeout", "900")
    print("\nQuarry is ready: http://localhost:3000")
    if read_env().get("QUARRY_DEMO_SEED") == "true":
        print("Use 'Explore sample workspace'. Sample indexing may continue briefly in the background.")


def test_database():
    result = compose("exec", "-T", "postgres", "psql", "-U", "quarry", "-d", "postgres",
                     "-tAc", "SELECT 1 FROM pg_database WHERE datname='quarry_test'", capture=True)
    if result.stdout.strip() != "1":
        compose("exec", "-T", "postgres", "createdb", "-U", "quarry", "quarry_test")


@contextmanager
def verification_lock():
    folder=ROOT/'.runtime'
    folder.mkdir(exist_ok=True)
    with (folder/'verify.lock').open('a+b') as handle:
        handle.seek(0,2)
        if handle.tell()==0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise SystemExit('Another verification is active in this checkout. Wait for it to finish.') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def verify():
    with verification_lock():
        verify_locked()


def verify_locked():
    from release import coverage_gate, fingerprint

    doctor()
    test_database()
    steps = [
        ["--profile", "test", "build", "tests", "browser-tests"],
        ["--profile", "test", "run", "--rm", "--no-deps", "tests", "alembic", "upgrade", "head"],
        ["--profile", "test", "run", "--rm", "--no-deps", "tests", "ruff", "check", "."],
        ["--profile", "test", "run", "--rm", "--no-deps", "tests", "alembic", "check"],
        ["--profile", "test", "run", "--rm", "--no-deps", "tests", "python", "-m", "quarry.contract"],
        ["--profile", "test", "run", "--rm", "--no-deps", "tests"],
        ["--profile", "test", "run", "--rm", "--no-deps", "browser-tests"],
    ]
    report = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "source_sha256": fingerprint(), "steps": [], "paid_calls": 0}
    failure = False
    for arguments in steps:
        started = time.monotonic()
        result = compose(*arguments, check=False, capture=True)
        output = redact(result.stdout + result.stderr)
        print(output[-12000:])
        report["steps"].append({"command": ["docker", "compose", *arguments],
                                "exit_code": result.returncode,
                                "seconds": round(time.monotonic() - started, 2), "output": output})
        if result.returncode:
            failure = True
            break
    if not failure:
        report['critical_coverage'] = coverage_gate()
        failure = report['critical_coverage']['status'] != 'passed'
    report["status"] = "failed" if failure else "passed"
    (ROOT / "evaluation/results/verification.json").write_text(json.dumps(report, indent=2))
    scan()
    if failure:
        raise SystemExit("Verification failed. See evaluation/results/verification.json")
    print("Functional checks passed. Public release additionally requires a current clean security scan; see the audit report.")


def scan():
    ignored = {".git", "node_modules", ".next", "__pycache__", "data", ".runtime"}
    bad = []
    patterns = [re.compile(r"(?:gsk_|sk-proj-|gho_)[A-Za-z0-9_-]{20,}"),
                re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")]
    for folder, directories, files in os.walk(ROOT):
        directories[:] = [d for d in directories if d not in ignored]
        for name in files:
            path = Path(folder) / name
            if name.startswith(".env") or path.suffix.lower() in {".png", ".zip", ".pdf"}:
                continue
            if path.stat().st_size > 3_000_000:
                continue
            value = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern.search(value) for pattern in patterns):
                bad.append(str(path.relative_to(ROOT)))
    if bad:
        raise SystemExit("Secret scan failed in: " + ", ".join(bad))
    print("Source secret scan passed.")


def publish(owner):
    from release import fingerprint

    if owner != "rishicodes576":
        raise SystemExit("Publishing is restricted to rishicodes576")
    gh = shutil.which("gh")
    if not gh:
        raise SystemExit("Install GitHub CLI and run gh auth login first")
    login = run([gh, "api", "user", "--jq", ".login"], capture=True).stdout.strip()
    if login != owner:
        raise SystemExit("GitHub authentication does not match the intended owner")
    artifact = ROOT / "evaluation/results/verification.json"
    if not artifact.exists() or json.loads(artifact.read_text())["status"] != "passed":
        raise SystemExit("Run the verification command successfully before publishing")
    if json.loads(artifact.read_text()).get('source_sha256') != fingerprint():
        raise SystemExit('Source changed after verification; rerun verify before publishing')
    security = ROOT/'evaluation/results/security/summary.json'
    if not security.exists() or json.loads(security.read_text()).get('status') != 'passed' or json.loads(security.read_text()).get('source_sha256') != fingerprint():
        raise SystemExit('A current complete security scan must pass before public publishing. Findings are not waived automatically.')
    scan()
    if not (ROOT / ".git").exists():
        run(["git", "init", "-b", "main"])
    run(["git", "config", "--local", "user.name", "Rishab Chetal"])
    run(["git", "config", "--local", "user.email", "rishabchetal@gmail.com"])
    run(["git", "config", "--local", "user.useConfigOnly", "true"])
    for key in ['GIT_AUTHOR_NAME','GIT_AUTHOR_EMAIL','GIT_COMMITTER_NAME','GIT_COMMITTER_EMAIL']:
        os.environ.pop(key, None)
    history = run(["git", "log", "--format=%an|%ae|%cn|%ce%n%B"], capture=True, check=False)
    if history.returncode == 0:
        for line in history.stdout.splitlines():
            if re.search(r"co-authored-by:|\bcodex\b", line, re.I):
                raise SystemExit("Commit attribution audit failed")
            if "|" in line and line != "Rishab Chetal|rishabchetal@gmail.com|Rishab Chetal|rishabchetal@gmail.com":
                raise SystemExit("Unexpected author or committer in history")
    if run([gh, "repo", "view", f"{owner}/quarry"], capture=True, check=False).returncode == 0:
        raise SystemExit("Repository already exists; refusing to overwrite it")
    if run(["git", "remote"], capture=True).stdout.strip():
        raise SystemExit("A remote already exists; refusing to repoint it")
    run(["git", "add", "."])
    if run(["git", "diff", "--cached", "--quiet"], check=False).returncode:
        run(["git", "-c", "commit.gpgsign=false", "commit", "-m", "Build Quarry engineering research workspace"])
    identity = run(['git','log','-1','--format=%an|%ae|%cn|%ce'],capture=True).stdout.strip()
    if identity != 'Rishab Chetal|rishabchetal@gmail.com|Rishab Chetal|rishabchetal@gmail.com':
        raise SystemExit('Final commit attribution audit failed; no repository was created')
    run([gh, "repo", "create", f"{owner}/quarry", "--public", "--source", ".", "--remote", "origin", "--push"])
    print(f"Published https://github.com/{owner}/quarry")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "down", "doctor", "verify", "benchmark", "scan", "configure-groq", "publish", "loadtest", "backup", "restore-test", "create-owner", "retention"])
    parser.add_argument("--owner", default="rishicodes576")
    parser.add_argument("--live", action="store_true", help="Explicitly enable free-key live answer evaluation")
    args = parser.parse_args()
    if args.command == "up":
        up()
    elif args.command == "down":
        compose("down")
    elif args.command == "doctor":
        doctor()
    elif args.command == "verify":
        verify()
    elif args.command == "scan":
        scan()
    elif args.command == "benchmark":
        compose("--profile", "evaluation", "build", "evaluate")
        compose("--profile", "evaluation", "run", "--rm", "--no-deps", "evaluate", "python", "-m", "quarry.benchmark", *(["--live"] if args.live else []))
        if not args.live:
            compose('--profile','evaluation','run','--rm','--no-deps','evaluate','python','-m','quarry.agent_eval')
    elif args.command == "loadtest":
        run([sys.executable, str(ROOT / "scripts/loadtest.py")])
    elif args.command in {"backup", "restore-test"}:
        run([sys.executable,str(ROOT/'scripts/backup.py'),*(['--rehearse'] if args.command=='restore-test' else [])])
    elif args.command == "retention":
        compose('exec','-T','api','python','-m','quarry.admin','retention')
    elif args.command == "create-owner":
        email=input('Owner email: ').strip()
        password=getpass.getpass('Password (15+ characters): ')
        payload=json.dumps({'email':email,'password':password,'workspace':input('Workspace name: ').strip()})
        subprocess.run([docker(),'compose','exec','-T','api','python','-m','quarry.admin','create-owner'],input=payload,text=True,check=True)
    elif args.command == "configure-groq":
        configure()
        if input("Confirm this key belongs to a Groq FREE organization with no billing enabled [yes/no]: ").strip().lower() != "yes":
            raise SystemExit("Configuration cancelled")
        key = getpass.getpass("Groq Free Plan key (hidden): ").strip()
        if not key.startswith("gsk_") or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
            raise SystemExit("Invalid key format")
        values = read_env()
        values.update(GROQ_API_KEY=key, QUARRY_GROQ_FREE_PLAN_CONFIRMED="true")
        write_env(values)
        compose("up", "--detach", "--no-deps", "--force-recreate", "api", "worker")
    else:
        publish(args.owner)


if __name__ == "__main__":
    main()
