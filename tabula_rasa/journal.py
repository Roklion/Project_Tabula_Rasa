"""Pure validation for balanced multi-line journal postings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.reference_data import as_bool as _as_bool, clean_text as _clean_text


_CENT = Decimal("0.01")
JOURNAL_SIDES = {"Debit", "Credit"}
JOURNAL_TARGET_TYPES = {"account", "category"}


class JournalValidationError(ValueError):
    """Raised when a journal cannot be normalized without losing intent."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _editor_amount(posting: Mapping[str, Any], side: str) -> Any:
    for key in (side.casefold(), side):
        if key in posting:
            return posting.get(key)
    return ""


def _has_value(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def _has_editor_amount(value: Any) -> bool:
    if not _has_value(value):
        return False
    try:
        amount = Decimal(str(value).strip())
        # A signaling NaN raises InvalidOperation when compared. Treat every
        # non-finite input as populated so _amount can reject it with the
        # stable journal validation message instead of exposing decimal's raw
        # exception.
        return not amount.is_finite() or amount != 0
    except (InvalidOperation, ValueError):
        return True


def _is_blank_placeholder(posting: Mapping[str, Any]) -> bool:
    """Ignore stable editor metadata while deciding whether a row is blank."""
    meaningful_fields = (
        "target_type",
        "target_id",
        "side",
        "amount",
        "payee_id",
        "description",
    )
    return not any(_has_value(posting.get(field)) for field in meaningful_fields) and not any(
        _has_editor_amount(posting.get(field))
        for field in ("debit", "Debit", "credit", "Credit")
    )


def _amount(value: Any) -> str:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise JournalValidationError("Journal amount must be numeric") from None
    if not amount.is_finite() or amount <= 0:
        raise JournalValidationError("Journal amount must be greater than zero")
    amount = amount.quantize(_CENT)
    if amount <= 0:
        raise JournalValidationError(
            "Journal amount must be at least one cent after rounding"
        )
    return format(amount, "f")


def normalize_journal_postings(
    postings: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return ordered canonical postings or raise ``JournalValidationError``.

    Canonical callers may provide ``side`` and ``amount``. The journal editor
    may instead provide separate ``debit`` and ``credit`` values. Completely
    blank editor placeholders are ignored; every populated row must be valid.
    """
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for posting in postings:
        if not isinstance(posting, Mapping):
            raise JournalValidationError("Each journal posting must be a record")
        if _is_blank_placeholder(posting):
            continue

        posting_id = _text(posting.get("id"))
        if not posting_id:
            raise JournalValidationError("Each journal posting requires a stable ID")
        if posting_id in seen_ids:
            raise JournalValidationError("Journal posting IDs must be unique")
        seen_ids.add(posting_id)

        target_type = _text(posting.get("target_type")).casefold()
        if target_type not in JOURNAL_TARGET_TYPES:
            raise JournalValidationError(
                "Journal target type must be account or category"
            )
        target_id = _text(posting.get("target_id"))
        if not target_id:
            raise JournalValidationError("Each journal posting requires a target")

        debit = _editor_amount(posting, "Debit")
        credit = _editor_amount(posting, "Credit")
        has_debit = _has_editor_amount(debit)
        has_credit = _has_editor_amount(credit)
        canonical_side = _text(posting.get("side")).title()
        canonical_amount = posting.get("amount")
        has_canonical_side = bool(canonical_side)
        has_canonical_amount = _has_value(canonical_amount)

        if (has_debit or has_credit) and (
            has_canonical_side or has_canonical_amount
        ):
            raise JournalValidationError(
                "Use either Debit/Credit columns or Side/Amount for a posting"
            )
        if has_debit or has_credit:
            if has_debit and has_credit:
                raise JournalValidationError(
                    "A journal posting cannot contain both a debit and a credit"
                )
            side = "Debit" if has_debit else "Credit"
            raw_amount = debit if has_debit else credit
        else:
            if not has_canonical_side or not has_canonical_amount:
                raise JournalValidationError(
                    "Each journal posting requires one debit or credit amount"
                )
            side = canonical_side
            raw_amount = canonical_amount

        if side not in JOURNAL_SIDES:
            raise JournalValidationError("Journal side must be Debit or Credit")

        normalized.append(
            {
                "id": posting_id,
                "position": len(normalized) + 1,
                "target_type": target_type,
                "target_id": target_id,
                "side": side,
                "amount": _amount(raw_amount),
                "payee_id": _text(posting.get("payee_id")),
                "description": _text(posting.get("description")),
            }
        )

    if len(normalized) < 2:
        raise JournalValidationError(
            "A journal entry requires at least two complete postings"
        )

    debits = sum(
        (Decimal(posting["amount"]) for posting in normalized if posting["side"] == "Debit"),
        Decimal("0.00"),
    )
    credits = sum(
        (Decimal(posting["amount"]) for posting in normalized if posting["side"] == "Credit"),
        Decimal("0.00"),
    )
    if debits == 0 or credits == 0:
        raise JournalValidationError(
            "A journal entry requires at least one debit and one credit"
        )
    if debits != credits:
        raise JournalValidationError("Journal debits and credits must balance")

    return normalized


__all__ = [
    "JOURNAL_SIDES",
    "JOURNAL_TARGET_TYPES",
    "JournalValidationError",
    "normalize_journal_postings",
    "normalize_journal_input",
    "prepare_journal_postings",
]


def prepare_journal_postings(
    entry_id: str,
    postings: Iterable[Mapping[str, Any]],
    *,
    accounts: Mapping[str, Mapping[str, Any]],
    categories: Mapping[str, Mapping[str, Any]],
    payees: Mapping[str, Mapping[str, Any]],
    original_entry: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    source_postings = list(postings)
    normalized = normalize_journal_input(entry_id, source_postings)
    original_postings = {
        str(posting.get("id", "")): posting
        for posting in (original_entry or {}).get("postings", ())
    }
    prepared: list[dict[str, Any]] = []
    for posting in normalized:
        posting_id = posting["id"]
        original = original_postings.get(posting_id, {})
        target_type = posting["target_type"]
        target_id = posting["target_id"]
        if target_type == "account":
            account = accounts.get(target_id)
            if account is None:
                raise StorageValidationError("Journal account does not exist")
            same_historical_target = (
                original.get("target_type") == "account"
                and original.get("target_id") == target_id
            )
            if not _as_bool(account.get("active"), "Account active") and not same_historical_target:
                raise StorageValidationError("Journal account is inactive")
        elif target_id not in categories:
            raise StorageValidationError("Journal category does not exist")

        payee_id = posting["payee_id"]
        if payee_id:
            payee = payees.get(payee_id)
            if payee is None:
                raise StorageValidationError("Journal payee does not exist")
            same_historical_payee = original.get("payee_id") == payee_id
            if not _as_bool(payee.get("active"), "Payee active") and not same_historical_payee:
                raise StorageValidationError("Journal payee is inactive")
        prepared.append({**posting, "parent_entry_id": entry_id})
    return prepared



def normalize_journal_input(entry_id: str, postings: Iterable[Mapping[str, Any]]):
    postings = list(postings)
    try:
        normalized = normalize_journal_postings(postings)
    except JournalValidationError as error:
        raise StorageValidationError(str(error)) from error
    if any(
        _clean_text(posting.get("parent_entry_id"), "Journal parent entry ID") not in {"", entry_id}
        for posting in postings
    ):
        raise StorageValidationError("Journal posting belongs to a different parent entry")
    return normalized
