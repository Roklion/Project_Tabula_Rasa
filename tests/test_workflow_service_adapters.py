"""The three workflow ports share each selected profile's current Sheets facade."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from tabula_rasa.composition import create_sheets_application
from tabula_rasa.errors import StorageConflictError
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import profile_config
from tests.fakes import FakeWorkbook
from tests.test_workflow_services import asset_data, mixed_data, schedule_data


def test_production_workflow_graph_and_mutations_are_isolated_between_profiles():
    storages = {key: GoogleSheetsStorage(FakeWorkbook()) for key in ("north", "south")}
    profiles = {
        key: profile_config(name=key.title(), spreadsheet_id=key) for key in storages
    }
    with patch.object(
        GoogleSheetsStorage,
        "from_secrets",
        side_effect=lambda secrets: storages[secrets["spreadsheet_id"]],
    ):
        graphs = {
            key: create_sheets_application(
                key, {"business_profiles": profiles}
            ).services
            for key in storages
        }
    for key, graph in graphs.items():
        assert graph.assets._repository._storage is storages[key]
        assert graph.recurring._repository._storage is storages[key]
        assert graph.mixed_use._repository._storage is storages[key]
        assert graph.recurring._transactions is graph.transactions
        assert graph.recurring._mixed_use is graph.mixed_use
        assert graph.mixed_use._transactions is graph.transactions
        assert graph.assets._journals is graph.journals
        graph.ledger.ensure_defaults()
        graph.accounts.create("Offset", "Other", classification="Asset")
    asset_records = {}
    mixed_records = {}
    for key, graph in graphs.items():
        accounts = {record["name"]: record["id"] for record in graph.accounts.list()}
        category = storages[key].list_categories("Expense")[0]["id"]
        asset_records[key] = graph.assets.create(
            asset_id="same-asset",
            **{
                **asset_data(),
                "depreciation_expense_account_id": category,
                "accumulated_depreciation_account_id": accounts["Offset"],
            },
        )
        mixed_records[key] = graph.mixed_use.create(
            **mixed_data(account_id=accounts["Cash"], category_id=category)
        )
        graph.recurring.create(
            **schedule_data(account_id=accounts["Cash"], category_id=category)
        )
    south_before = deepcopy(graphs["south"].transactions.list())
    graphs["north"].assets.post_due(
        "same-asset", "2026-01-31", expected=asset_records["north"]
    )
    graphs["north"].recurring.reconcile(as_of="2026-01-31")
    updated = graphs["north"].mixed_use.update(
        "source", expected=mixed_records["north"], business_use_percentage="50"
    )
    with pytest.raises(StorageConflictError):
        graphs["north"].mixed_use.delete("source", expected=mixed_records["north"])
    graphs["north"].mixed_use.delete("source", expected=updated)
    assert graphs["south"].transactions.list() == south_before
    assert len(graphs["south"].mixed_use.list()) == 1
    assert (
        graphs["south"].recurring.get("schedule")["latest_current_occurrence_date"]
        == ""
    )
    assert (
        len(
            graphs["south"].assets.post_due(
                "same-asset", "2026-01-31", expected=asset_records["south"]
            )
        )
        == 1
    )
    assert (
        len(graphs["south"].recurring.reconcile(as_of="2026-01-31")["generated"]) == 1
    )
