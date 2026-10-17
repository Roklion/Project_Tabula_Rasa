"""Minimal monthly close/unlock and explicit reversing-entry commands."""

from datetime import date

from tabula_rasa.errors import StorageValidationError
from tabula_rasa.reference_data import clean_text


class PeriodService:
    def __init__(self, repository):
        self._repository = repository

    def list(self):
        return self._repository.list()

    @staticmethod
    def reason(value):
        value = clean_text(value, 'Reason', required=True)
        if len(value) > 1000:
            raise StorageValidationError('Reason must be at most 1000 characters.')
        return value

    def change(self, period_start, *, closed, reason, expected_version):
        try:
            month = date.fromisoformat(str(period_start))
        except ValueError:
            raise StorageValidationError('Supply the first day of an accounting month.') from None
        if month.day != 1 or type(closed) is not bool or type(expected_version) is not int or expected_version < 0:
            raise StorageValidationError('Invalid accounting period command.')
        return self._repository.change(month, closed=closed, reason=self.reason(reason), expected_version=expected_version)

    def reverse(self, original_entry_id, *, correction_id, reversal_entry_id, txn_date, reason, expected):
        return self._repository.reverse(
            clean_text(original_entry_id, 'Entry ID', required=True),
            correction_id=clean_text(correction_id, 'Correction ID', required=True),
            reversal_entry_id=clean_text(reversal_entry_id, 'Reversal ID', required=True),
            txn_date=txn_date, reason=self.reason(reason), expected=expected,
        )
