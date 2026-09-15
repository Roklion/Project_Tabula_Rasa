"""Streamlit integration scenario for the Phase-A Assets workflow."""

from __future__ import annotations

import json

from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import authenticated_app, by_key, by_label, navigate_to
from tests.fakes import FakeWorkbook


def run() -> None:
    storage = GoogleSheetsStorage(FakeWorkbook(), sleeper=lambda _: None)
    expense = storage.create_category("Depreciation", "Expense")
    offset = storage.create_account("Accumulated depreciation", "Other", classification="Asset")
    with authenticated_app(storage) as app:
        navigate_to(app, "Assets")
        by_label(app.text_input, "Asset name").input("Quarterly laptop")
        by_label(app.selectbox, "Depreciation expense account").select(expense["id"])
        by_label(app.selectbox, "Accumulated depreciation account").select(offset["id"])
        by_label(app.number_input, "Cost basis").set_value(1200.0)
        by_label(app.number_input, "Useful life (quarters)").set_value(4)
        by_key(app.button, "save_new_asset").click().run()

        assets = storage.list_assets()
        assert len(assets) == 1
        asset = assets[0]
        assert asset["name"] == "Quarterly laptop"
        assert asset["useful_life_quarters"] == "4"

        by_key(
            app.button,
            f"calculate_asset_schedule_test_{asset['id']}",
        ).click().run()
        assert any(
            "Quarter" in list(frame.value.columns)
            and "Remaining book value" in list(frame.value.columns)
            for frame in app.dataframe
        )

        by_label(app.text_input, "Reason").input("Imported prior quarter")
        by_label(app.number_input, "Depreciation amount").set_value(250.0)
        by_key(
            app.button,
            f"save_asset_override_test_{asset['id']}",
        ).click().run()

        overridden = storage.list_assets()[0]
        overrides = json.loads(overridden["schedule_overrides"])
        assert overrides["1"] == {
            "amount": "250.00",
            "reason": "Imported prior quarter",
        }
        app.run()
        assert not any(
            button.key == f"delete_asset_{asset['id']}" for button in app.button
        )
        assert any(
            "saved depreciation history cannot be deleted" in str(message.value)
            for message in app.info
        )
        assert storage.list_transactions() == []  # Calculation/overrides never post.
        by_key(app.button, f"post_depreciation_test_{asset['id']}").click().run()
        rows = storage.list_transactions()
        assert len(rows) == 1
        assert rows[0]["amount"] == "250.00"
        assert not app.exception
        app.run()
        assert len(storage.list_transactions()) == 1
        assert any("Posted depreciation history is read-only" in str(message.value) for message in app.info)
        schedule = next(frame.value for frame in app.dataframe if "Posting status" in frame.value.columns)
        assert schedule.iloc[0]["Posting status"] == "Posted"
        assert schedule.iloc[0]["Ledger entry ID"] == rows[0]["id"]
        by_key(app.button, f"post_depreciation_test_{asset['id']}").click().run()
        assert len(storage.list_transactions()) == 1
        navigate_to(app, "Transactions")
        app.session_state["edit_transaction_id"] = rows[0]["id"]
        app.run()
        assert any("managed from Assets" in str(message.value) for message in app.info)
        assert not app.exception



if __name__ == "__main__":
    run()
