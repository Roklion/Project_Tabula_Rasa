from __future__ import annotations

import pytest

from tabula_rasa.hierarchy import (
    eligible_parent_ids,
    hierarchy_paths,
    HierarchyValidationError,
    ordered_hierarchy,
    validate_two_level_hierarchy,
)


def account(
    item_id: str,
    *,
    parent_id: str = "",
    classification: str = "Asset",
) -> dict[str, str]:
    return {
        "id": item_id,
        "parent_id": parent_id,
        "classification": classification,
    }


@pytest.mark.parametrize(
    "records",
    [
        [account("a", parent_id="missing")],
        [account("a", parent_id="a")],
        [account("a", parent_id="b"), account("b", parent_id="a")],
        [
            account("a", parent_id="b"),
            account("b", parent_id="c"),
            account("c", parent_id="a"),
        ],
        [
            account("a", parent_id="b"),
            account("b", parent_id="c"),
            account("c"),
        ],
        [
            account("a", parent_id="b"),
            account("b", classification="Liability"),
        ],
        [account("a"), account("a")],
    ],
)
def test_invalid_two_level_account_graphs_are_rejected(
    records: list[dict[str, str]],
) -> None:
    with pytest.raises(HierarchyValidationError):
        validate_two_level_hierarchy(
            records,
            compatibility_field="classification",
            item_label="Account",
        )


def test_valid_two_level_graph_accepts_multiple_children() -> None:
    validate_two_level_hierarchy(
        [
            account("parent"),
            account("child-1", parent_id="parent"),
            account("child-2", parent_id="parent"),
        ],
        compatibility_field="classification",
        item_label="Account",
    )


def test_hierarchy_display_and_parent_choices_are_two_level_and_compatible() -> None:
    items = [
        {**account("asset"), "name": "Assets"},
        {**account("cash", parent_id="asset"), "name": "Cash"},
        {
            **account("liability", classification="Liability"),
            "name": "Liabilities",
        },
    ]

    assert hierarchy_paths(items) == {
        "asset": "Assets",
        "cash": "Assets › Cash",
        "liability": "Liabilities",
    }
    assert [item["id"] for item in ordered_hierarchy(items)] == [
        "asset",
        "cash",
        "liability",
    ]
    assert eligible_parent_ids(
        items,
        compatibility_field="classification",
        compatibility_value="Asset",
        item_id="cash",
    ) == ["asset"]


def test_none_parent_ids_are_treated_as_layer_one() -> None:
    items = [
        {
            **account("asset"),
            "name": "Assets",
            "parent_id": None,
        },
        {**account("cash", parent_id="asset"), "name": "Cash"},
    ]

    assert hierarchy_paths(items) == {
        "asset": "Assets",
        "cash": "Assets › Cash",
    }
    assert [item["id"] for item in ordered_hierarchy(items)] == [
        "asset",
        "cash",
    ]
    assert eligible_parent_ids(
        items,
        compatibility_field="classification",
        compatibility_value="Asset",
    ) == ["asset"]
    validate_two_level_hierarchy(
        items,
        compatibility_field="classification",
        item_label="Account",
    )


def test_empty_id_sentinel_is_not_used_as_a_parent() -> None:
    items = [
        {
            "id": "",
            "name": "Uncategorized",
            "parent_id": "",
            "kind": "Expense",
        },
        {
            "id": "travel",
            "name": "Travel",
            "parent_id": "",
            "kind": "Expense",
        },
    ]

    assert hierarchy_paths(items) == {
        "": "Uncategorized",
        "travel": "Travel",
    }


def test_missing_ids_are_not_offered_as_parents() -> None:
    items = [
        {
            "name": None,
            "parent_id": "",
            "classification": "Asset",
        },
        {
            "id": "asset",
            "name": None,
            "parent_id": "",
            "classification": "Asset",
        },
    ]

    assert hierarchy_paths(items) == {"": "", "asset": ""}
    assert eligible_parent_ids(
        items,
        compatibility_field="classification",
        compatibility_value="Asset",
    ) == ["asset"]


def test_ordered_hierarchy_keeps_orphaned_items_visible() -> None:
    items = [
        {**account("root"), "name": "Root"},
        {**account("orphan", parent_id="missing"), "name": "Orphan"},
    ]

    assert [item["id"] for item in ordered_hierarchy(items)] == [
        "orphan",
        "root",
    ]


def test_ordered_hierarchy_keeps_cyclic_items_visible() -> None:
    items = [
        {**account("a", parent_id="b"), "name": "Alpha"},
        {**account("b", parent_id="a"), "name": "Beta"},
    ]

    assert [item["id"] for item in ordered_hierarchy(items)] == ["a", "b"]


def test_ordered_hierarchy_sorts_none_names_as_empty_strings() -> None:
    items = [
        {**account("named"), "name": "Alpha"},
        {**account("unnamed"), "name": None},
    ]

    assert [item["id"] for item in ordered_hierarchy(items)] == [
        "unnamed",
        "named",
    ]
