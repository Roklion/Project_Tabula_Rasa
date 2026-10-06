"""Mixed-use allocation workflows using the transaction application boundary."""

from uuid import uuid4

from tabula_rasa.mixed_use_records import prepare_mixed_use_expense
from tabula_rasa.mixed_use import validate_mixed_use_allocation
from tabula_rasa.reference_data import clean_text
from tabula_rasa.transaction import RECURRING_FIELDS
from tabula_rasa.errors import StorageValidationError

from .mixed_use_contracts import MixedUseRepository
from .transactions import TransactionService


class MixedUseService:
    def __init__(
        self, repository: MixedUseRepository, *, transactions: TransactionService
    ):
        self._repository = repository
        self._transactions = transactions

    def list(self, *, fresh=False):
        return self._repository.list(fresh=fresh)

    def sources(self, *, fresh=False):
        return self._repository.sources(fresh=fresh)

    def get(self, source_id, *, fresh=False):
        return self._repository.get(
            clean_text(source_id, "Mixed-use source ID", required=True), fresh=fresh
        )

    def allocation(self, total_expense, business_use_percentage):
        return validate_mixed_use_allocation(total_expense, business_use_percentage)

    def prepare_pair(self, data, references, **options):
        return prepare_mixed_use_expense(
            lambda inputs, **kwargs: self._transactions.prepare_source_projection(
                inputs, references, **kwargs
            ),
            data,
            **options,
        )

    def create(self, **data):
        if any(str(data.get(field) or "").strip() for field in RECURRING_FIELDS):
            raise StorageValidationError(
                "Recurring provenance is reserved for recurring schedule creation"
            )
        return self._create(data, recurring=False)

    def create_occurrence(self, *, expected_schedule=None, **data):
        """Source-owned recurring generation; ordinary creates reject provenance."""
        from tabula_rasa.ledger_validation import validate_recurring_provenance

        validate_recurring_provenance(data, "Recurring mixed-use source")
        if (
            data.get("recurring_source_kind") != "mixed_use"
            or data.get("recurring_occurrence_type") not in {"initial", "generated"}
            or not data.get("recurring_schedule_id")
        ):
            raise StorageValidationError("Recurring occurrence provenance is invalid")
        return self._create(data, recurring=True, expected_schedule=expected_schedule)

    def _create(self, data, *, recurring, expected_schedule=None):
        data = dict(data)
        data["source_id"] = clean_text(
            data.get("source_id", data.get("id")), "Mixed-use source ID"
        ) or str(uuid4())
        data["linked_transaction_id"] = clean_text(
            data.get("linked_transaction_id"), "Linked transaction ID"
        ) or str(uuid4())
        create = getattr(self._repository, "create_occurrence", None) if recurring else None
        if create is not None:
            return create(data, build=self.prepare_pair, expected_schedule=expected_schedule)
        return self._repository.create(
            data, build=self.prepare_pair, recurring=recurring
        )

    def update(self, source_id, *, expected_source=None, expected=None, **changes):
        return self._repository.update(
            clean_text(source_id, "Mixed-use source ID", required=True),
            changes,
            expected=expected_source or expected,
            build=self.prepare_pair,
        )

    def delete(self, source_id, *, expected_source=None, expected=None):
        return self._repository.delete(
            clean_text(source_id, "Mixed-use source ID", required=True),
            expected=expected_source or expected,
        )

    def link_receipt(self, source_id, *, reference, expected_source=None):
        return self._repository.link_receipt(
            source_id, reference=reference, expected=expected_source
        )

    def unlink_receipt(self, source_id, *, file_id, expected_source=None):
        return self._repository.unlink_receipt(
            source_id, file_id=file_id, expected=expected_source
        )
