from __future__ import annotations

from types import SimpleNamespace

from tabula_rasa.page_renderers.transactions import table_selection


class _TableHarness:
    def __init__(self) -> None:
        self.session_state: dict[str, object] = {}
        self.callback = None
        self.table_key = ""

    def dataframe(self, _frame, **kwargs) -> None:
        assert kwargs["selection_mode"] == "single-row"
        self.callback = kwargs["on_select"]
        self.table_key = kwargs["key"]

    def choose_row(self, row: int) -> None:
        self.session_state[self.table_key] = SimpleNamespace(
            selection=SimpleNamespace(rows=[row])
        )
        self.callback()


def test_management_selection_uses_stable_ids_and_clears_stale_scope(monkeypatch) -> None:
    ui = _TableHarness()
    monkeypatch.setattr(table_selection, "st", ui)
    first = [{"id": "a", "name": "Alpha"}, {"id": "b", "name": "Beta"}]

    def render(records, profile="north") -> str:
        return table_selection.selected_table_record(
            records,
            [row["id"] for row in records],
            profile_key=profile,
            surface="managed_payee",
            records=records,
            clear_on_change=(f"edit_target_{profile}",),
        )

    assert render(first) == ""
    ui.choose_row(1)
    assert render(first) == "b"
    ui.session_state["edit_target_north"] = "b"
    first_key = ui.table_key

    reordered = [first[1], first[0]]
    assert render(reordered) == ""
    assert ui.table_key != first_key
    assert "edit_target_north" not in ui.session_state
    ui.choose_row(0)
    assert render(reordered) == "b"

    assert render([{"id": "s", "name": "South"}], "south") == ""
    ui.choose_row(0)
    assert render([{"id": "s", "name": "South"}], "south") == "s"
    assert render(reordered) == ""


def test_management_selection_clears_when_record_disappears(monkeypatch) -> None:
    ui = _TableHarness()
    monkeypatch.setattr(table_selection, "st", ui)
    records = [{"id": "a", "name": "Alpha"}]
    assert table_selection.selected_table_record(
        records, ["a"], profile_key="north", surface="recurring_schedule", records=records
    ) == ""
    ui.choose_row(0)
    assert table_selection.selected_table_record(
        records, ["a"], profile_key="north", surface="recurring_schedule", records=records
    ) == "a"
    table_selection.clear_selected_table_record(
        profile_key="north", surface="recurring_schedule"
    )
    assert table_selection.selected_table_record(
        [{"id": "b", "name": "Beta"}], ["b"],
        profile_key="north", surface="recurring_schedule",
        records=[{"id": "b", "name": "Beta"}],
    ) == ""
