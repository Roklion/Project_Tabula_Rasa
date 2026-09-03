from __future__ import annotations

from unittest.mock import Mock

import streamlit as st

from tabula_rasa.page_renderers.tag_selector import (
    ADD_NEW_TAG,
    inline_tag_name_error,
    render_tag_selector,
    schedule_tag_selector_reset,
)
from tabula_rasa.page_renderers.transactions.ledger import _copyable_tag_ids


def test_tag_selector_keeps_each_selection_and_exposes_inline_creation(monkeypatch) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", state)
    multiselect = Mock(return_value=[ADD_NEW_TAG, "project", "internal"])
    text_input = Mock(return_value="Client work")
    monkeypatch.setattr(st, "multiselect", multiselect)
    monkeypatch.setattr(st, "text_input", text_input)

    selected, new_name = render_tag_selector(
        [
            {"id": "project", "name": "Project", "active": "TRUE"},
            {"id": "internal", "name": "Internal", "active": "TRUE"},
        ],
        label="Tags",
        key="tags",
    )

    assert selected == ["project", "internal"]
    assert new_name == "Client work"
    assert state["tags"] == []
    assert multiselect.call_args.args[1] == [ADD_NEW_TAG, "project", "internal"]
    text_input.assert_called_once()


def test_tag_selector_accepts_a_typed_new_name_when_search_hides_sentinel(monkeypatch) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", state)
    multiselect = Mock(return_value=["project", "Client work"])
    monkeypatch.setattr(st, "multiselect", multiselect)

    selected, new_name = render_tag_selector(
        [{"id": "project", "name": "Project", "active": "TRUE"}],
        label="Tags",
        key="tags",
    )

    assert selected == ["project"]
    assert new_name == "Client work"
    assert multiselect.call_args.kwargs["accept_new_options"] is True


def test_tag_selector_preserves_an_inactive_association_for_normal_edit(monkeypatch) -> None:
    state: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "multiselect", lambda _label, options, **_kwargs: options[1:])

    selected, new_name = render_tag_selector(
        [
            {"id": "active", "name": "Active", "active": "TRUE"},
            {"id": "old", "name": "Old", "active": "FALSE"},
        ],
        label="Edit tags",
        key="edit-tags",
        selected_ids=["old"],
        preserve_inactive_ids=["old"],
    )

    assert selected == ["active", "old"]
    assert new_name is None
    assert state["edit-tags"] == ["old"]


def test_tag_selector_resets_after_confirmed_inline_creation(monkeypatch) -> None:
    state: dict[str, object] = {
        "edit-tags": [ADD_NEW_TAG],
        "edit-tags__new_name": "New tag",
    }
    monkeypatch.setattr(st, "session_state", state)
    monkeypatch.setattr(st, "multiselect", Mock(return_value=[]))
    text_input = Mock(return_value="")
    monkeypatch.setattr(st, "text_input", text_input)

    schedule_tag_selector_reset("edit-tags")
    selected, new_name = render_tag_selector(
        [{"id": "new", "name": "New tag", "active": "TRUE"}],
        label="Edit tags",
        key="edit-tags",
    )

    assert selected == []
    assert new_name is None
    assert state["edit-tags"] == []
    assert "edit-tags__new_name" not in state
    text_input.assert_not_called()


def test_blank_inline_tag_name_is_rejected_before_storage_write() -> None:
    assert inline_tag_name_error("") == "Enter a Tag name before saving."
    assert inline_tag_name_error("   ") == "Enter a Tag name before saving."
    assert inline_tag_name_error(None) is None
    assert inline_tag_name_error("Project") is None


def test_inline_tag_selector_label_cannot_be_saved_as_a_tag_name() -> None:
    message = "Choose a different Tag name; this selector label is reserved."

    assert inline_tag_name_error(ADD_NEW_TAG) == message
    assert inline_tag_name_error("Add new tag") == message


def test_copy_drops_inactive_source_tags() -> None:
    assert _copyable_tag_ids(
        [
            {"id": "active", "name": "Active", "active": "TRUE"},
            {"id": "old", "name": "Old", "active": "FALSE"},
        ],
        ["active", "old", "active"],
    ) == ["active"]
