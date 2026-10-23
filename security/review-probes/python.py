"""Independent AI component probe: local temporary HTTP server only, no application/database."""

import http.server
import json
import pathlib
import subprocess
import threading
import time

from component_loader import isolated_function, module_namespace

root = pathlib.Path(__file__).resolve().parents[2]
commit = "9e7833d6ae90c27c0d5338da22855524bc4047bd"
source = subprocess.check_output(
    ["git", "show", commit + ":backend/quarry/network.py"],
    text=True,
    cwd=root,
    encoding="utf-8",
)
space = module_namespace(source)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", "8")
        self.end_headers()
        for _ in range(8):
            self.wfile.write(b"x")
            self.wfile.flush()
            time.sleep(0.05)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
original = space["PinnedHTTP"]


class LocalPinned(original):
    def __init__(self, host, address, port, tls):
        super().__init__("127.0.0.1", "127.0.0.1", server.server_port, False)
        self.timeout = 0.1


space["PinnedHTTP"] = LocalPinned
space["public_addresses"] = lambda *args: ["8.8.8.8"]
started = time.monotonic()
body, _, _ = space["fetch_public"]("http://public.example/")
elapsed = time.monotonic() - started
server.shutdown()
server.server_close()
tool_source = subprocess.check_output(
    ["git", "show", commit + ":backend/quarry/tools.py"],
    text=True,
    cwd=root,
    encoding="utf-8",
)
called = []
globals_ = {
    "fetch_public": lambda _: (
        b"%PDF-safe-probe",
        "application/pdf",
        "https://public.example/",
    ),
    "extract": lambda body, media: (
        called.append({"media": media, "in_process": True}) or "probe text"
    ),
    "source": lambda *args: {"kind": args[-1]},
}
globals_["execute"] = isolated_function(tool_source, "execute", globals_)
assert globals_["execute"]("fetch_url", "https://public.example/", True) == [
    {"kind": "web"}
]
result = {
    "reviewed_commit": commit,
    "probe": "original Python functions with local loopback server / inert parser spy; no external network or database",
    "network": {
        "socket_inactivity_timeout_seconds": 0.1,
        "observed_total_seconds": round(elapsed, 3),
        "received_bytes": len(body),
        "exceeds_inactivity_timeout": elapsed > 0.3,
    },
    "parser_calls": called,
}
(root / "evaluation/results/independent-review-python.json").write_text(
    json.dumps(result, indent=2)
)
print(json.dumps(result))
