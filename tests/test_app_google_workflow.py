from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = Path(__file__).with_name("_app_google_workflow_scenario.py")
CSV_REPORTING_SCENARIO = Path(__file__).with_name("_app_csv_reporting_scenario.py")


class AppGoogleWorkflowTests(unittest.TestCase):
    def _run_scenario(self, scenario: Path) -> None:
        result = subprocess.run(
            [sys.executable, str(scenario)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"Scenario failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}",
        )

    def test_account_category_transaction_edit_and_delete_workflow(self) -> None:
        self._run_scenario(SCENARIO)

    def test_csv_duplicate_validation_and_report_totals(self) -> None:
        self._run_scenario(CSV_REPORTING_SCENARIO)


if __name__ == "__main__":
    unittest.main()
