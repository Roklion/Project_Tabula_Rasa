from tabula_rasa.page_renderers.transactions.payee_selector import (
    resolve_payee_selection,
)


def test_resolve_payee_selection_returns_inline_name_for_unknown_value() -> None:
    payee_id, new_name = resolve_payee_selection(
        "New vendor",
        [{"id": "vendor", "name": "Existing vendor"}],
        ["", "vendor"],
    )

    assert payee_id == ""
    assert new_name == "New vendor"


def test_resolve_payee_selection_matches_existing_name_case_insensitively() -> None:
    payee_id, new_name = resolve_payee_selection(
        " existing vendor ",
        [{"id": "vendor", "name": "Existing vendor"}],
        ["", "vendor"],
    )

    assert payee_id == "vendor"
    assert new_name == ""


def test_resolve_payee_selection_keeps_blank_as_no_payee() -> None:
    assert resolve_payee_selection(
        "   ",
        [{"id": "vendor", "name": "Existing vendor"}],
        ["", "vendor"],
    ) == ("", "")
