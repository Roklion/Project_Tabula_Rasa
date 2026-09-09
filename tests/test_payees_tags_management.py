from __future__ import annotations

from pathlib import Path

from tests.app_support import authenticated_app, navigate_to
from tests.fakes import FakeWorkbook
from tabula_rasa.storage import GoogleSheetsStorage

def test_transactions_exposes_profile_local_management_tab() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook())
    with authenticated_app(storage=storage) as app:
        navigate_to(app, "Transactions")
        management = next(tab for tab in app.tabs if tab.label == "Payees & Tags")
        labels = [getattr(node, "label", "") for node in management]
        assert "Payees" in labels
        assert "Tags" in labels
        assert "New payee name" in labels
        assert "New tag name" in labels
        assert any(
            "Business profile:" in str(node.value)
            for node in app.caption
        )


def test_management_display_uses_prefetched_cached_rows() -> None:
    renderer_source = Path(
        "tabula_rasa/page_renderers/transactions/renderer.py"
    ).read_text(encoding="utf-8")
    management_source = Path(
        "tabula_rasa/page_renderers/transactions/payees_tags.py"
    ).read_text(encoding="utf-8")
    assert '"MixedUseExpenses"' in renderer_source
    assert '"Mileage"' in renderer_source
    assert "list_mixed_use_expense_sources()" in management_source
    assert "list_transactions()" in management_source
    assert "list_mileage_trips()" in management_source
    assert management_source.count("context.storage.list_transactions()") == 1
    assert "list_mixed_use_expenses(_force_refresh=True)" not in management_source
    assert "list_mileage_trips(_force_refresh=True)" not in management_source
    assert "list_payees(active_only=False, _force_refresh=True)" not in management_source
    assert "list_tags(active_only=False, _force_refresh=True)" not in management_source


def test_management_destructive_controls_scope_acknowledgement_and_style_hooks() -> None:
    management_source = Path(
        "tabula_rasa/page_renderers/transactions/payees_tags.py"
    ).read_text(encoding="utf-8")
    assert "managed_merge_payee_ack_{context.profile_key}_{target_id}_" in management_source
    assert "managed_merge_tag_ack_{context.profile_key}_{target_id}_" in management_source
    assert "managed_remove_payee_ack_{context.profile_key}_{remove_id}" in management_source
    assert "managed_remove_tag_ack_{context.profile_key}_{remove_id}" in management_source
    assert "disabled=is_referenced" in management_source
    assert management_source.count('str(item["active"]).upper() == "TRUE"') == 2
    assert 'key="destructive_managed_payee_remove"' in management_source
    assert 'key="destructive_managed_tag_remove"' in management_source
