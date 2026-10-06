"""Simple Ledger commands using domain rules and profile-local neutral ports."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any
from uuid import uuid4

from tabula_rasa.accounting_postings import accounting_postings
from tabula_rasa.errors import StorageValidationError
from tabula_rasa.ledger_validation import iso_date
from tabula_rasa.reference_data import clean_text
from tabula_rasa.transaction import (
    prepare_transaction,
    utc_now,
    reject_derived_transaction,
    validate_transaction_create,
    validate_transaction_update,
)

from .accounting_contracts import (
    TransactionReferences,
    TransactionRepository,
    TransactionRecord,
)
from .contracts import ExpectedRecord
from .reference_data import PayeeService, TagService


class TransactionService:
    """Own transaction preparation without service-side retries or stale reads."""

    def __init__(
        self,
        repository: TransactionRepository,
        *,
        payees: PayeeService,
        tags: TagService,
    ) -> None:
        self._repository = repository
        self._payees = payees
        self._tags = tags

    def prepare_workspace(self) -> None:
        """Let the backend batch related reads without exposing its schema."""
        self._repository.prepare_workspace()

    def list(
        self,
        *,
        start: date | str | None = None,
        end: date | str | None = None,
        kind: str | None = None,
        account_ids: Iterable[str] | None = None,
        fresh: bool = False,
    ) -> list[TransactionRecord]:
        if kind is not None:
            kind = clean_text(kind, "Transaction kind", required=True).title()
            if kind not in {"Income", "Expense", "Transfer"}:
                raise StorageValidationError("Unknown transaction kind")
        return self._repository.list(
            start=iso_date(start) if start is not None else None,
            end=iso_date(end) if end is not None else None,
            kind=kind,
            account_ids=account_ids,
            fresh=fresh,
        )

    def create(
        self, *, transaction_id: str | None = None, **data: Any
    ) -> TransactionRecord:
        transaction_id = (
            clean_text(transaction_id, "Transaction ID", required=True)
            if transaction_id is not None
            else str(uuid4())
        )
        validate_transaction_create(data)
        data = dict(data)
        if data.get("receipt_references") in (None, ""):
            data["receipt_references"] = []
        created_at = utc_now()

        def build(references: TransactionReferences, current):
            return self._prepare(
                data, references, transaction_id, created_at=created_at
            )

        return self._repository.create(transaction_id, build=build)

    def _prepare(self, data, references, transaction_id, *, created_at, original=None):
        return prepare_transaction(
            data,
            transaction_id=transaction_id,
            created_at=created_at,
            accounts=references.accounts,
            categories=references.categories,
            payees=references.payees,
            tags=references.tags,
            create_payee=self._payees.create,
            create_tag=self._tags.create,
            original_transaction=original,
        )

    def prepare_source_projection(self, data, references, **options):
        """Apply transaction rules inside a source repository's fresh mutation.

        Source workflows own provenance and persist paired records; their
        bookkeeping projection still uses this service and the shared rules.
        """
        return prepare_transaction(
            data,
            accounts=references.accounts,
            categories=references.categories,
            payees=references.payees,
            tags=references.tags,
            create_payee=self._payees.create,
            create_tag=self._tags.create,
            **options,
        )

    def create_occurrence(self, *, transaction_id, expected_schedule=None, **data):
        """Create a source-owned recurring occurrence with a stable identity."""
        from tabula_rasa.ledger_validation import validate_recurring_provenance

        validate_recurring_provenance(data, "Recurring occurrence")
        if (
            data.get("kind") != "Expense"
            or data.get("recurring_source_kind") != "transaction"
            or data.get("recurring_occurrence_type") not in {"initial", "generated"}
            or not data.get("recurring_schedule_id")
        ):
            raise StorageValidationError("Recurring occurrence provenance is invalid")
        identity = clean_text(transaction_id, "Transaction ID", required=True)
        data = {**data, "receipt_references": []}
        created_at = utc_now()
        create = getattr(self._repository, 'create_occurrence', None)
        options = {} if create is None else {
            'schedule_id': data['recurring_schedule_id'], 'expected_schedule': expected_schedule,
        }
        return (create or self._repository.create)(
            identity,
            build=lambda references, current: self._prepare(
                data, references, identity, created_at=created_at
            ),
            **options,
        )

    def update(
        self,
        transaction_id: str,
        *,
        expected: ExpectedRecord | None = None,
        **changes: Any,
    ) -> TransactionRecord:
        transaction_id = clean_text(transaction_id, "Transaction ID", required=True)
        changes = dict(changes)

        def build(references: TransactionReferences, current):
            reject_derived_transaction(current)
            validate_transaction_update(current, changes)
            base = dict(current)
            base.pop("payee", None)  # Resolved display name is not command input.
            merged = {**base, **changes}
            return self._prepare(
                merged,
                references,
                transaction_id,
                created_at=current["created_at"],
                original=current,
            )

        return self._repository.update(transaction_id, expected=expected, build=build)

    def delete(
        self, transaction_id: str, *, expected: ExpectedRecord | None = None
    ) -> None:
        return self._repository.delete(
            clean_text(transaction_id, "Transaction ID", required=True),
            expected=expected,
        )

    def bulk_update(
        self,
        transaction_ids: Sequence[str],
        *,
        expected: Sequence[ExpectedRecord],
        changes: Mapping[str, Any],
    ) -> dict[str, str]:
        return self._repository.bulk_update(
            transaction_ids, expected=expected, changes=changes
        )

    def bulk_delete(
        self, transaction_ids: Sequence[str], *, expected: Sequence[ExpectedRecord]
    ) -> dict[str, str]:
        return self._repository.bulk_delete(transaction_ids, expected=expected)

    def postings(self, **filters) -> list[dict[str, Any]]:
        """Translate Simple Ledger records with the existing accounting owner."""
        return list(accounting_postings(self.list(**filters)))
