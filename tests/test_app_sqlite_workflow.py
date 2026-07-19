from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = Path(__file__).with_name("_app_sqlite_workflow_scenario.py")


class AppSqliteWorkflowTests(unittest.TestCase):
    def test_account_category_transaction_and_delete_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            environment = os.environ.copy()
            environment["LEDGER_DB_PATH"] = str(
                Path(temporary_directory) / "ledger.db"
            )
            result = subprocess.run(
                [sys.executable, str(SCENARIO)],
                cwd=PROJECT_ROOT,
                env=environment,
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


if __name__ == "__main__":
    unittest.main()
