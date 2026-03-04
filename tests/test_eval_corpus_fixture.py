import json
from pathlib import Path


def test_eval_corpus_v1_fixture_meets_baseline_constraints():
    corpus_path = Path("examples/eval_corpus_v1.json")
    raw = json.loads(corpus_path.read_text())

    assert isinstance(raw, dict)
    cases = raw.get("cases")
    assert isinstance(cases, list)
    assert len(cases) >= 20

    for case in cases:
        assert isinstance(case, dict)
        for field in ["name", "repo_url", "branch", "target", "rationale"]:
            assert isinstance(case.get(field), str) and case[field].strip()
        depth = case.get("clone_depth", 200)
        assert isinstance(depth, int) and depth > 0

    test_first_count = sum(
        1 for case in cases if "test-first diff order" in case["rationale"].lower()
    )
    assert test_first_count >= 5
