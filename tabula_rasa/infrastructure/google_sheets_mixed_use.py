"""Adapter retaining source/projection batching and uncertain-write recovery."""


class GoogleSheetsMixedUseRepository:
    def __init__(self, storage):
        self._storage = storage

    def list(self, *, fresh=False):
        return self._storage.list_mixed_use_expenses(_force_refresh=fresh)

    def sources(self, *, fresh=False):
        return self._storage.list_mixed_use_expense_sources(_force_refresh=fresh)

    def get(self, source_id, *, fresh=False):
        return self._storage.get_mixed_use_expense(source_id, _force_refresh=fresh)

    def create(self, data, *, build, recurring=False):
        return self._storage.create_mixed_use_expense(
            **data, _build=build, _allow_recurring_provenance=recurring
        )

    def update(self, source_id, changes, *, expected, build):
        return self._storage.edit_mixed_use_expense(
            source_id, **changes, expected_source=expected, _build=build
        )

    def delete(self, source_id, *, expected):
        return self._storage.delete_mixed_use_expense(
            source_id, expected_source=expected
        )

    def link_receipt(self, source_id, *, reference, expected):
        return self._storage.link_mixed_use_receipt(
            source_id, reference=reference, expected_source=expected
        )

    def unlink_receipt(self, source_id, *, file_id, expected):
        return self._storage.unlink_mixed_use_receipt(
            source_id, file_id=file_id, expected_source=expected
        )


def mixed_use_service_for_storage(storage):
    from tabula_rasa.application.mixed_use import MixedUseService
    from tabula_rasa.infrastructure.google_sheets import transaction_service_for_storage
    return MixedUseService(GoogleSheetsMixedUseRepository(storage), transactions=transaction_service_for_storage(storage))
