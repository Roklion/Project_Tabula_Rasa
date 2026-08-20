from __future__ import annotations

import importlib
from unittest.mock import patch

import streamlit as st

from tabula_rasa.page_renderers import reports


def test_reports_module_import_does_not_render_or_bootstrap() -> None:
    with (
        patch.object(st, "markdown") as markdown,
        patch.object(st, "error") as error,
        patch.object(st, "secrets", create=True) as secrets,
    ):
        imported = importlib.reload(reports)

    assert imported.render_reports is not None
    markdown.assert_not_called()
    error.assert_not_called()
    secrets.assert_not_called()


def test_reports_context_requires_selected_profile_and_storage() -> None:
    storage = object()

    def report_storage_error(error: object) -> None:
        del error

    context = reports.ReportsContext(
        "north", storage, report_storage_error  # type: ignore[arg-type]
    )

    assert context.profile_key == "north"
    assert context.storage is storage
    assert context.report_storage_error is report_storage_error


def test_statement_frame_preserves_balance_sheet_columns_and_current_earnings() -> None:
    frame = reports._statement_frame(
        [
            {
                "id": "equity",
                "name": "Owner equity",
                "type": "Equity",
                "parent_id": "",
                "direct_balance": 10.0,
                "rollup_balance": 10.0,
            }
        ],
        current_earnings=5.0,
    )

    assert list(frame.columns) == ["Account", "Type", "Balance"]
    assert frame.to_dict("records") == [
        {"Account": "Owner equity", "Type": "Equity", "Balance": 10.0},
        {"Account": "Current earnings", "Type": "Calculated", "Balance": 5.0},
    ]
