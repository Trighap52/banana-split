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
                    "expected_dependency_pairs": 20,
                    "satisfied_dependency_pairs": 17,
                },
                "cases": [
                    {"name": "case-a", "status": "success", "tree_equal": True},
                ],
            }
        )
    )

    proc = _run_gate(report_path, "--min-tree-equal", "1.0", "--min-dependency-order", "0.8")
    assert proc.returncode == 0
    assert "dependency_pairs=17/20" in proc.stdout
    assert "Quality gates passed." in proc.stdout


def test_check_eval_report_prints_failing_cases_for_tree_equality(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tree_equal_success_rate": 0.8,
                    "dependency_order_satisfaction": 0.85,
                    "expected_dependency_pairs": 20,
                    "satisfied_dependency_pairs": 17,
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


def test_check_eval_report_fails_dependency_order_threshold(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tree_equal_success_rate": 1.0,
                    "dependency_order_satisfaction": 0.75,
                    "expected_dependency_pairs": 20,
                    "satisfied_dependency_pairs": 15,
                },
                "cases": [
                    {"name": "case-a", "status": "success", "tree_equal": True},
                ],
            }
        )
    )

    proc = _run_gate(report_path, "--min-tree-equal", "1.0", "--min-dependency-order", "0.8")
    assert proc.returncode == 1
    assert "dependency_order_satisfaction below threshold" in proc.stdout


def test_check_eval_report_requires_dependency_metric_when_gate_enabled(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "summary": {
                    "tree_equal_success_rate": 1.0,
                },
                "cases": [
                    {"name": "case-a", "status": "success", "tree_equal": True},
                ],
            }
        )
    )

    proc = _run_gate(report_path, "--min-dependency-order", "0.8")
    assert proc.returncode == 1
    assert "does not include dependency_order_satisfaction" in proc.stderr


def test_gate_rejects_inflated_rate_that_excludes_planning_failures(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({'summary': {'total_cases': 2, 'successful_cases': 1,
                                          'tree_equal_success_rate': 1.0},
                               'cases': [{'name': 'ok', 'status': 'success', 'tree_equal': True},
                                         {'name': 'missing', 'status': 'plan_build_failed', 'tree_equal': False}]}))
    result = _run_gate(path)
    assert result.returncode == 1
    assert 'successful_cases=1/2' in result.stdout
    assert 'tree_equal_success_rate=0.500' in result.stdout
    assert 'missing (plan_build_failed)' in result.stdout


def test_gate_rejects_nonfinite_metrics(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({'summary': {'tree_equal_success_rate': float('nan')},
                               'cases': [{'status': 'success', 'tree_equal': True}]}))
    assert _run_gate(path).returncode != 0


def test_gate_rejects_zero_dependency_evidence(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({'summary': {'tree_equal_success_rate': 1.0,
                                          'dependency_order_satisfaction': 1.0,
                                          'expected_dependency_pairs': 0, 'satisfied_dependency_pairs': 0},
                               'cases': [{'status': 'success', 'tree_equal': True}]}))
    result = _run_gate(path, '--min-dependency-order', '0.8')
    assert result.returncode == 1
    assert 'non-zero evaluated dependency pairs' in result.stderr
