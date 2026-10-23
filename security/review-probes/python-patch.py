"""Independent AI component probe: local temporary HTTP server only, no application/database."""

import hashlib
import http.server
import json
import pathlib
import threading
import time

from component_loader import isolated_function, module_namespace

root = pathlib.Path(__file__).resolve().parents[2]
source = (root / "backend/quarry/network.py").read_text(encoding="utf-8")
space = module_namespace(source)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "100")
        self.end_headers()
        try:
            for _ in range(100):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.025)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
original = space["PinnedHTTP"]


class LocalPinned(original):
    def __init__(self, host, address, port, tls):
        super().__init__("127.0.0.1", "127.0.0.1", server.server_port, False)


space["PinnedHTTP"] = LocalPinned
space["public_addresses"] = lambda *args: ["8.8.8.8"]
started = time.monotonic()
error = ""
try:
    space["fetch_public"]("http://public.example/", total_timeout=0.12)
except space["FetchError"] as e:
    error = str(e)
elapsed = time.monotonic() - started
server.shutdown()
server.server_close()
space["public_addresses"] = lambda *args: time.sleep(0.2) or ["8.8.8.8"]
started = time.monotonic()
dns_error = ""
try:
    space["fetch_public"]("http://public.example/", total_timeout=0.04)
except space["FetchError"] as e:
    dns_error = str(e)
dns_elapsed = time.monotonic() - started
space["_DNS_POOL"].shutdown(wait=True)
# Force deadline expiry exactly between resolver return and dispatch registration.
expired_at_handoff = threading.Event()


def expire_on_resolver_return(*_args):
    expired_at_handoff.set()
    return ["8.8.8.8"]


space["resolve_before_deadline"] = expire_on_resolver_return
late_dispatch_blocked = False
try:
    space["_fetch_public"](
        "http://public.example/", 20, time.monotonic() + 1, expired_at_handoff, []
    )
except space["FetchError"]:
    late_dispatch_blocked = True


# Force timer expiry while socket creation returns, before transport registration.
class InertSocket:
    def __init__(self):
        self.closed = False

    def shutdown(self, _how):
        pass

    def close(self):
        self.closed = True


inert_socket = InertSocket()
expired_during_connect = threading.Event()
original_create_connection = space["socket"].create_connection


def connect_and_expire(*_args, **_kwargs):
    expired_during_connect.set()
    return inert_socket


space["socket"].create_connection = connect_and_expire
connection = original("public.example", "8.8.8.8", 80, False)
connection._fetch_deadline = time.monotonic() + 1
connection._fetch_expired = expired_during_connect
late_connect_blocked = False
try:
    connection.connect()
except space["FetchError"]:
    late_connect_blocked = inert_socket.closed
finally:
    space["socket"].create_connection = original_create_connection
tool_source = (root / "backend/quarry/tools.py").read_text(encoding="utf-8")
called = []
globals_ = {
    "fetch_public": lambda _: (
        b"%PDF-safe-probe",
        "application/pdf",
        "https://public.example/",
    ),
    "isolated_extract": lambda body, media, name: (
        called.append({"media": media, "isolation_entry_point": True}) or "probe text"
    ),
    "source": lambda *args: {"kind": args[-1]},
}
globals_["execute"] = isolated_function(tool_source, "execute", globals_)
assert globals_["execute"]("fetch_url", "https://public.example/", True) == [
    {"kind": "web"}
]
result = {
    "probe": "current original Python functions; loopback trickle server / delayed DNS / inert isolated parser spy; no external network or database",
    "network_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "tools_sha256": hashlib.sha256(tool_source.encode()).hexdigest(),
    "trickle": {
        "deadline_seconds": 0.12,
        "elapsed_seconds": round(elapsed, 3),
        "error": error,
    },
    "dns": {
        "deadline_seconds": 0.04,
        "elapsed_seconds": round(dns_elapsed, 3),
        "error": dns_error,
    },
    "parser_calls": called,
    "late_dns_dispatch_blocked": late_dispatch_blocked,
    "late_socket_closed": late_connect_blocked,
}
result["status"] = (
    "passed"
    if error
    and dns_error
    and elapsed < 0.4
    and dns_elapsed < 0.15
    and called
    and late_dispatch_blocked
    and late_connect_blocked
    else "failed"
)
(root / "evaluation/results/independent-review-python-patch.json").write_text(
    json.dumps(result, indent=2)
)
print(json.dumps(result))

raise SystemExit(0 if result["status"] == "passed" else 1)
