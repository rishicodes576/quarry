import hashlib
import json
from pathlib import Path

from huggingface_hub import snapshot_download

from quarry.config import settings

MODELS = {
    "bm25": {
        "repo": "Qdrant/bm25",
        "revision": "22b8d2af71a76161e18dd432d2cee0eefa66e412",
        "license": "Apache-2.0",
    },
    "dense": {
        "repo": "Qdrant/all-MiniLM-L6-v2-onnx",
        "revision": "d13954661f83248295ba75c1ed411eef3b7b936e",
        "license": "Apache-2.0",
    },
    "reranker": {
        "repo": "Xenova/ms-marco-MiniLM-L-6-v2",
        "revision": "a09144355adeed5f58c8ed011d209bf8ee5a1fec",
        "license": "Apache-2.0",
    },
}


def prepare():
    root = Path(settings().model_cache)
    root.mkdir(parents=True, exist_ok=True)
    cached = verified_manifest(root)
    if cached is not None:
        return cached
    manifest = {}
    for name, spec in MODELS.items():
        directory = root / name
        snapshot_download(
            repo_id=spec["repo"],
            revision=spec["revision"],
            local_dir=str(directory),
            allow_patterns=[
                "*.json",
                "*.txt",
                "model.onnx",
                "onnx/model.onnx",
                "LICENSE*",
                "README.md",
            ],
        )
        files = {}
        for path in directory.rglob("*"):
            if path.is_file() and ".cache" not in path.parts:
                with path.open("rb") as stream:
                    files[str(path.relative_to(directory))] = hashlib.file_digest(
                        stream, "sha256"
                    ).hexdigest()
        manifest[name] = {**spec, "files": files}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def verified_manifest(root):
    try:
        manifest = json.loads((root / "manifest.json").read_text())
        required = {
            "dense": {"model.onnx", "tokenizer.json"},
            "reranker": {"onnx/model.onnx", "tokenizer.json"},
            "bm25": {"english.txt"},
        }
        for name, spec in MODELS.items():
            entry = manifest[name]
            if (
                any(entry[key] != value for key, value in spec.items())
                or not required[name] <= entry["files"].keys()
            ):
                return None
            for filename, expected in entry["files"].items():
                path = (root / name / filename).resolve()
                if not path.is_relative_to((root / name).resolve()):
                    return None
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                        return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        return None


if __name__ == "__main__":
    prepare()
