from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = Path(__file__).with_name("_app_google_workflow_scenario.py")
CSV_REPORTING_SCENARIO = Path(__file__).with_name("_app_csv_reporting_scenario.py")
RECEIPT_DELETE_SCENARIO = Path(__file__).with_name(
    "_app_receipt_delete_scenario.py"
)


class TestAppGoogleWorkflow:
    def _run_scenario(self, scenario: Path) -> None:
        scenario_environment = os.environ.copy()
        scenario_environment.update(
            {
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
            }
        )
        result = subprocess.run(
            [sys.executable, str(scenario)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=scenario_environment,
        )
        assert (
            result.returncode == 0
        ), f"Scenario failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"

    def test_account_category_transaction_edit_and_delete_workflow(self) -> None:
        self._run_scenario(SCENARIO)

    def test_csv_duplicate_validation_and_report_totals(self) -> None:
        self._run_scenario(CSV_REPORTING_SCENARIO)

    def test_receipt_delete_confirmation_failure_and_success(self) -> None:
        self._run_scenario(RECEIPT_DELETE_SCENARIO)
