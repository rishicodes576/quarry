import ast
import hashlib
import json
import math
import operator
import re
from urllib.parse import urlencode

import httpx

from quarry.config import settings
from quarry.ingest import isolated_extract
from quarry.network import FetchError, fetch_public


def calculate(expression: str) -> str:
    if len(expression) > 160:
        raise ValueError("Calculation is too long")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 40:
        raise ValueError("Calculation is too complex")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (abs(right) > 12 or abs(left) > 1e6):
                raise ValueError("Exponent exceeds the calculation limit")
            value = operations[type(node.op)](left, right)
        else:
            raise ValueError("Only numbers and arithmetic operators are allowed")
        if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("Result exceeds the calculation limit")
        return value

    try:
        return f"{expression} = {visit(tree.body):.12g}"
    except (ZeroDivisionError, OverflowError) as error:
        raise ValueError("Calculation is undefined or too large") from error


def source(title: str, text: str, url: str, kind: str) -> dict:
    return {
        "title": title[:240],
        "text": text[:2500],
        "source_url": url,
        "kind": kind,
        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
        "page": 1,
        "section": "Public source",
        "score": 0,
    }


def execute(name: str, argument: str, allow_web: bool) -> list[dict]:
    if name == "calculate":
        return [source("Arithmetic result", calculate(argument), "", "calculation")]
    if not allow_web:
        raise ValueError("Public-web tools are disabled for this run")
    if name == "fetch_url":
        body, media, final = fetch_public(argument)
        text = isolated_extract(body, media, final)
        return [source(final, text, final, "web")]
    if name == "wikipedia":
        url = "https://en.wikipedia.org/w/api.php?" + urlencode(
            {
                "action": "query",
                "generator": "search",
                "gsrsearch": argument,
                "gsrlimit": 3,
                "prop": "extracts|info",
                "exintro": 1,
                "explaintext": 1,
                "inprop": "url",
                "format": "json",
                "exchars": 1800,
            }
        )
        body, _, _ = fetch_public(url)
        data = json.loads(body)
        return [
            source(p["title"], p.get("extract", ""), p.get("fullurl", ""), "wikipedia")
            for p in data.get("query", {}).get("pages", {}).values()
            if p.get("extract")
        ]
    if name == "web_search":
        if not settings().searxng_url:
            raise FetchError("Self-hosted web search is not configured")
        with httpx.Client(timeout=12, trust_env=False) as client:
            response = client.get(
                settings().searxng_url.rstrip("/") + "/search",
                params={"q": argument, "format": "json"},
            )
            response.raise_for_status()
            data = response.json()
        results = []
        for result in data.get("results", [])[:3]:
            url = result.get("url", "")
            if not re.match(r"^https?://", url):
                continue
            # Search snippets are labeled as such; fetching full pages requires a separate tool.
            results.append(
                source(result.get("title", url), result.get("content", ""), url, "search_snippet")
            )
        return results
    raise ValueError("Unknown tool")
