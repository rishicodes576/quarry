"""Executable exploit-negative checks for the separately built optional evaluator."""

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

POISON = []


def mark():
    POISON.append("unsafe cache object executed")


class Poison:
    def __reduce__(self):
        return mark, ()


def denied(action):
    try:
        action()
    except ValueError:
        return
    raise RuntimeError("An excluded evaluator capability was unexpectedly available")


def main():
    manifest = json.loads(Path("/usr/local/share/quarry/eval-hardening.json").read_text())
    for item in manifest["files"]:
        if hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest() != item["patched_sha256"]:
            raise RuntimeError("Evaluator mitigation source hash mismatch")
    from ragas.metrics.collections.multi_modal_faithfulness import util

    with (
        patch(
            "requests.get", side_effect=AssertionError("Network access must not occur")
        ) as network,
        patch("builtins.open", side_effect=AssertionError("File access must not occur")) as files,
    ):
        denied(lambda: util._try_process_url("http://169.254.169.254/latest/meta-data/"))
        denied(lambda: util._try_process_local_file("/etc/passwd"))
        denied(lambda: util.process_image_to_base64("http://127.0.0.1/private.png"))
        network.assert_not_called()
        files.assert_not_called()
    from diskcache import Cache

    with tempfile.TemporaryDirectory() as directory:
        with Cache(directory) as cache:
            cache["safe"] = "plain string"
            if cache["safe"] != "plain string":
                raise RuntimeError("Safe primitive cache behavior failed")
            cache["small"] = Poison()
            cache["large"] = {"object": Poison(), "padding": "x" * 50000}
            denied(lambda: cache["small"])
            denied(lambda: cache["large"])
            cache[Poison()] = "key deserialization probe"
            denied(lambda: list(cache))
    if POISON:
        raise RuntimeError("A cache payload executed")
    print(
        json.dumps(
            {
                "status": "passed",
                "policy": manifest["policy"],
                "advisories": manifest["advisories"],
                "checks": [
                    "source hashes",
                    "blocked metadata URL",
                    "blocked local file",
                    "blocked multimodal entry",
                    "blocked inline pickle",
                    "blocked file pickle",
                    "blocked key pickle",
                    "safe primitive cache",
                ],
                "network_calls": 0,
                "files": manifest["files"],
            }
        )
    )


if __name__ == "__main__":
    main()
