from __future__ import annotations

from tabula_rasa.page_renderers.transactions.ledger import _selection_ids


def test_bulk_selection_maps_visible_rows_to_stable_ids_only() -> None:
    assert _selection_ids(["newest", "middle", "oldest"], [2, 0, 99]) == (
        "oldest",
        "newest",
    )
