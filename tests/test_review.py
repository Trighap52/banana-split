import pytest

from banana_split import cli
from banana_split.config import Config
from banana_split.domain import Diff, Plan, SuggestedCommit
from banana_split.planner import run_split
from banana_split.review import review_plan


@pytest.fixture
def plan():
    return Plan(
        diff=Diff(base_commit="base", target_commit="target"),
        suggested_commits=[SuggestedCommit("c1", "Example", None, [], ["h1"])],
    )


@pytest.mark.parametrize("rename", [False, True])
@pytest.mark.parametrize("exception", [KeyboardInterrupt(), EOFError()])
def test_cancellation_during_review_never_applies(plan, monkeypatch, rename, exception):
    monkeypatch.setattr("banana_split.planner.build_plan", lambda config: plan)
    monkeypatch.setattr("banana_split.review.sys.stdin.isatty", lambda: True)
    applied = []
    monkeypatch.setattr("banana_split.planner.apply_plan", lambda *args: applied.append(args))
    count = 0

    def answer(prompt):
        nonlocal count
        count += 1
        if rename and count == 1:
            return "y"
        raise exception

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main([]) == 130
    assert applied == []


def test_review_summary_is_visible_without_logging(plan, monkeypatch, capsys):
    monkeypatch.setattr("banana_split.review.sys.stdin.isatty", lambda: False)
    review_plan(plan)
    out = capsys.readouterr().out
    assert "Plan contains 1" in out
    assert "Example" in out


def test_dry_run_never_prompts_on_tty(plan, monkeypatch):
    monkeypatch.setattr("banana_split.planner.build_plan", lambda config: plan)
    monkeypatch.setattr("banana_split.review.sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("dry-run must not prompt"))
    run_split(Config(dry_run=True))
