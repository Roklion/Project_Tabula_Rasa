from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.app_support import SCENARIO_ENVIRONMENT

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIO = Path(__file__).with_name("_app_google_workflow_scenario.py")
CSV_REPORTING_SCENARIO = Path(__file__).with_name("_app_csv_reporting_scenario.py")
RECEIPT_UNLINK_SCENARIO = Path(__file__).with_name(
    "_app_receipt_unlink_scenario.py"
)
RECEIPT_CREATE_SCENARIO = Path(__file__).with_name(
    "_app_receipt_create_scenario.py"
)
RECEIPT_CREATE_GUARDS_SCENARIO = Path(__file__).with_name(
    "_app_receipt_create_guards_scenario.py"
)
HIERARCHY_SCENARIO = Path(__file__).with_name(
    "_app_hierarchy_workflow_scenario.py"
)
BULK_SCENARIO = Path(__file__).with_name("_app_transaction_bulk_scenario.py")
BULK_EDITOR_SCENARIO = Path(__file__).with_name(
    "_app_transaction_bulk_editor_scenario.py"
)


class TestAppGoogleWorkflow:
    def _run_scenario(self, scenario: Path, case_name: str) -> None:
        scenario_environment = os.environ.copy()
        scenario_environment.update(SCENARIO_ENVIRONMENT)
        existing_pythonpath = scenario_environment.get("PYTHONPATH")
        scenario_environment["PYTHONPATH"] = (
            f"{PROJECT_ROOT}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else str(PROJECT_ROOT)
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
        ), (
            f"Scenario {case_name} failed:\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    @pytest.mark.parametrize(
        ("scenario", "case_name"),
        [
            (SCENARIO, "account_category_transaction_edit_delete"),
            (CSV_REPORTING_SCENARIO, "csv_duplicate_validation_reporting"),
            (RECEIPT_UNLINK_SCENARIO, "receipt_unlink_guards"),
            (RECEIPT_CREATE_SCENARIO, "receipt_create_recovery"),
            (RECEIPT_CREATE_GUARDS_SCENARIO, "receipt_create_prewrite_guards"),
            (HIERARCHY_SCENARIO, "hierarchy_profile_isolation"),
            (BULK_SCENARIO, "transaction_bulk_profile_isolation"),
            (BULK_EDITOR_SCENARIO, "transaction_bulk_editor_fields"),
        ],
        ids=[
            "account_category_transaction_edit_delete",
            "csv_duplicate_validation_reporting",
            "receipt_unlink_guards",
            "receipt_create_recovery",
            "receipt_create_prewrite_guards",
            "hierarchy_profile_isolation",
            "transaction_bulk_profile_isolation",
            "transaction_bulk_editor_fields",
        ],
    )
    def test_app_scenario(self, scenario: Path, case_name: str) -> None:
        self._run_scenario(scenario, case_name)
