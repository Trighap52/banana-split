from banana_split import cli


def test_cli_eval_mode_runs_harness(monkeypatch):
    calls = {"run": 0, "print": 0, "write": 0}
    report = {
        "summary": {
            "total_cases": 1,
            "successful_cases": 1,
        }
    }

    def fake_run_evaluation(*, corpus_path, use_ai, verbosity):
        calls["run"] += 1
        assert corpus_path == "corpus.json"
        assert use_ai is False
        assert verbosity == 0
        return report

    def fake_print(summary_report):
        calls["print"] += 1
        assert summary_report is report

    def fake_write(summary_report, output_path):
        calls["write"] += 1
        assert summary_report is report
        assert output_path == "out.json"

    monkeypatch.setattr("banana_split.cli.run_evaluation", fake_run_evaluation)
    monkeypatch.setattr("banana_split.cli.print_evaluation_summary", fake_print)
    monkeypatch.setattr("banana_split.cli.write_evaluation_report", fake_write)

    exit_code = cli.main(["--eval-corpus", "corpus.json", "--eval-output", "out.json"])
    assert exit_code == 0
    assert calls == {"run": 1, "print": 1, "write": 1}


def test_cli_eval_mode_strict_failure_exit(monkeypatch):
    report = {
        "summary": {
            "total_cases": 2,
            "successful_cases": 1,
        }
    }
    monkeypatch.setattr("banana_split.cli.run_evaluation", lambda **kwargs: report)
    monkeypatch.setattr("banana_split.cli.print_evaluation_summary", lambda *args, **kwargs: None)
    monkeypatch.setattr("banana_split.cli.write_evaluation_report", lambda *args, **kwargs: None)

    exit_code = cli.main(["--eval-corpus", "corpus.json", "--eval-fail-on-case-failure"])
    assert exit_code == 2
