"""Closed-form checks and corruption detection for the independent measurement audit."""

import json
from pathlib import Path

import pytest

from quarry.metric_audit import audit, judge_score, quantile, ranks


def test_judge_arithmetic_matches_explicit_binary_verdicts():
    # Relevant at ranks two and three: AP=(1/2+2/3)/2, with Ragas' epsilon.
    close_to = (1 / 2 + 2 / 3) / (2 + 1e-10)
    assert judge_score("context_precision", [{"verdict": v} for v in [0, 1, 1]]) == close_to
    assert judge_score("context_recall", [{"classifications": [{"attributed": v} for v in [1, 0, 1]]}]) == 2 / 3
    assert judge_score("faithfulness", [{"statements": ["atomic claims"]}, {"statements": [{"verdict": v} for v in [1, 0, 0, 1]]}]) == .5
    with pytest.raises(ValueError, match="Non-binary"):
        judge_score("context_precision", [{"verdict": 2}])
    with pytest.raises(ValueError, match="Missing"):
        judge_score("faithfulness", [{"statements": []}])


def test_independent_ranks_and_percentiles_have_known_values():
    result = ranks(["x", "a", "a", "b"], ["a", "b"])
    assert result["ndcg_at_5"] == pytest.approx(.6934264036172708)
    assert result["mrr"] == .5 and result["recall_at_5"] == 1
    assert quantile([40, 20, 10, 30], .95) == pytest.approx(38.5)
    assert ranks(["a"], []) is None


@pytest.mark.parametrize("corruption", ["score", "summaries", "split"])
def test_audit_rejects_tampered_saved_retrieval_matrix(tmp_path, corruption):
    original = Path("/app/evaluation")
    (tmp_path / "results").mkdir()
    for name in ("manifest.json", "cases.json", "corpus.json"):
        (tmp_path / name).write_bytes((original / name).read_bytes())
    result = json.loads((original / "results/retrieval-all.json").read_text())
    if corruption == "score":
        result["rows"][0]["metrics"]["mrr"] = -1
    elif corruption == "summaries":
        result["results"] = []
    else:
        result.update(split="nonexistent", rows=[], results=[])
    (tmp_path / "results/retrieval-all.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="Measurement mismatch|Incorrect retrieval"):
        audit(tmp_path)
