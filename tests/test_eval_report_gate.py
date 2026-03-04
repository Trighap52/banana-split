import json
import subprocess
import sys
from pathlib import Path


def _run_gate(report_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[1] / "scripts" / "check_eval_report.py"
    return subprocess.run(
        [sys.executable, str(script), str(report_path), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_check_eval_report_passes_when_thresholds_are_met(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tree_equal_success_rate": 1.0,
                    "dependency_order_satisfaction": 0.85,
                },
                "cases": [
                    {"name": "case-a", "status": "success", "tree_equal": True},
                ],
            }
        )
    )

    proc = _run_gate(report_path, "--min-tree-equal", "1.0")
    assert proc.returncode == 0
    assert "Quality gates passed." in proc.stdout


def test_check_eval_report_prints_failing_cases_for_tree_equality(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tree_equal_success_rate": 0.8,
                    "dependency_order_satisfaction": 0.85,
                },
                "cases": [
                    {
                        "name": "case-b",
                        "status": "apply_failed",
                        "tree_equal": False,
                        "error": "patch does not apply",
                    },
                    {"name": "case-c", "status": "success", "tree_equal": True},
                ],
            }
        )
    )

    proc = _run_gate(report_path, "--min-tree-equal", "1.0")
    assert proc.returncode == 1
    assert "Failing cases:" in proc.stdout
    assert "case-b (apply_failed): patch does not apply" in proc.stdout
    assert "tree_equal_success_rate below threshold" in proc.stdout
