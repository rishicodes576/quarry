"""Load trusted repository components for inert, independent review probes.

Callers supply only a hard-coded local module or immutable Git baseline. Neither
uploaded content nor command-line-selected source is accepted by these probes.
"""

import ast
import importlib.util
import pathlib
import tempfile
from types import CodeType, FunctionType


def module_namespace(source: str) -> dict:
    """Use the standard module loader without importing application services."""
    repository = pathlib.Path(__file__).resolve().parents[2]
    scratch = (repository / ".runtime" / "review-probes").resolve()
    if not scratch.is_relative_to(repository):
        raise RuntimeError("Review scratch directory escaped its repository")
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="component-", dir=scratch) as folder:
        path = pathlib.Path(folder) / "reviewed_component.py"
        path.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("reviewed_component", path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Review module loader is unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return vars(module)


def isolated_function(source: str, name: str, inert_globals: dict):
    """Construct the actual trusted function with reviewer-owned inert globals."""
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    compiled = compile(
        ast.Module(body=[function], type_ignores=[]), "reviewed_function.py", "exec"
    )
    code = next(
        value
        for value in compiled.co_consts
        if isinstance(value, CodeType) and value.co_name == name
    )
    return FunctionType(code, inert_globals)
