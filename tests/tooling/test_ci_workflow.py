"""The required CI gate preserves suite coverage and rejects incomplete results."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def workflow() -> dict:
    # BaseLoader preserves the Actions `on` key instead of YAML 1.1's boolean.
    return yaml.load(
        (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def test_ci_runs_for_current_pr_candidates_without_feature_push_duplicates() -> None:
    config = workflow()
    assert config["on"]["pull_request"]["branches"] == ["main"]
    assert set(config["on"]["pull_request"]["types"]) == {
        "opened", "synchronize", "reopened", "ready_for_review",
    }
    assert "paths" not in config["on"]["pull_request"]
    assert config["on"]["push"]["branches"] == ["main"]
    assert config["on"]["merge_group"]["types"] == ["checks_requested"]
    assert config["permissions"] == {"contents": "read"}
    assert config["concurrency"]["cancel-in-progress"] == "true"
    assert "github.event.pull_request.number" in config["concurrency"]["group"]


def test_ci_preserves_complete_python_and_windows_coverage() -> None:
    jobs = workflow()["jobs"]
    python = jobs["python-suite"]
    assert "if" not in python
    assert python["runs-on"].startswith("ubuntu-")
    assert "postgres" in python["services"]
    assert python["env"]["TABULA_RASA_TEST_DATABASE_URL"].startswith(
        "postgresql+psycopg://tabula_test@127.0.0.1:"
    )
    commands = [step["run"] for step in python["steps"] if "run" in step]
    assert "python -m pip install -r requirements-dev.txt" in commands
    assert "ruff check ." in commands
    pytest_commands = [shlex.split(command) for command in commands
                       if command.startswith("python -m pytest")]
    assert len(pytest_commands) == 1
    # No positional test selection, marker filter, keyword filter or deselection.
    assert pytest_commands[0][3:] == ["-ra", "--junitxml=python-results.xml"]

    windows = jobs["windows-tooling"]
    assert windows["runs-on"].startswith("windows-")
    assert "if" not in windows
    setup = next(step for step in windows["steps"]
                 if step.get("uses", "").startswith("actions/setup-python@"))
    assert setup["with"]["python-version"] == "3.12"
    assert any(step.get("run", "").startswith(
        "python -m pytest tests/tooling/test_codex_environment_setup.py "
    ) for step in windows["steps"])

    # The browser job runs the compiled SPA against a disposable DB; it does
    # not repeat the full Python suite or Python lint.
    browser = jobs["browser"]
    assert "postgres" in browser["services"]
    assert not any(step.get("run", "").startswith("python -m pytest -ra") or
                   "ruff check" in step.get("run", "") for step in browser["steps"])
    native = next(step for step in browser["steps"] if step.get("name") == "Run native browser concurrency and core workflow tests")
    assert shlex.split(native['run']) == ['python', '-m', 'pytest',
        'tests/postgres/test_browser_baselines.py', 'tests/postgres/test_browser_workflows.py',
        'tests/postgres/test_browser_quality.py', 'tests/postgres/test_browser_mileage_documents.py',
        'tests/postgres/test_browser_secondary.py',
        'tests/postgres/test_browser_alpha.py',
        '--junitxml=browser-results.xml']
    assert native["env"]["TABULA_RASA_REQUIRE_BROWSER_TESTS"] == "1"
    installs = [step['run'] for step in browser['steps'] if 'playwright install' in step.get('run', '')]
    assert len(installs) == 2
    assert all('chromium firefox webkit' in command for command in installs)
    assert browser["env"]["TABULA_RASA_TEST_DATABASE_URL"].startswith("postgresql+psycopg://")


def test_required_gate_waits_for_all_suites_even_when_a_dependency_fails() -> None:
    jobs = workflow()["jobs"]
    gate = jobs["full-suite"]
    assert gate["name"] == "Full test suite"
    assert gate["if"] == "${{ always() }}"
    assert set(gate["needs"]) == set(jobs) - {"full-suite"}
    assert "continue-on-error" not in gate
    step = gate["steps"][0]
    assert step["shell"] == "bash"
    assert set(step["env"].values()) == {
        "${{ needs." + job + ".result }}" for job in gate["needs"]
    }


def run_gate(results: dict[str, str]) -> subprocess.CompletedProcess[str]:
    step = workflow()["jobs"]["full-suite"]["steps"][0]
    if os.name == "nt":
        # Use Git's shell, never the unrelated Windows/WSL bash launcher.
        git = shutil.which("git")
        assert git is not None, "Git is required by repository tooling tests"
        bash = Path(git).resolve().parents[1] / "bin/bash.exe"
        assert bash.is_file(), "Git for Windows Bash is required"
    else:
        bash = shutil.which("bash")
        assert bash is not None, "Bash is required by the Actions aggregate gate"
    environment = {**os.environ, **results}
    return subprocess.run(
        [str(bash), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        env=environment, capture_output=True, text=True, check=False, timeout=10,
    )


def test_required_gate_accepts_all_successful_suites() -> None:
    result = run_gate(dict.fromkeys(workflow()["jobs"]["full-suite"]["steps"][0]["env"],
                                   "success"))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("job", ["PYTHON_RESULT", "WINDOWS_RESULT", "BROWSER_RESULT"])
@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", ""])
def test_required_gate_rejects_failed_or_incomplete_suite(job: str, conclusion: str) -> None:
    results = dict.fromkeys(workflow()["jobs"]["full-suite"]["steps"][0]["env"], "success")
    results[job] = conclusion
    result = run_gate(results)
    assert result.returncode != 0
