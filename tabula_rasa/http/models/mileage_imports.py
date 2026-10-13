"""Allowlisted QuickBooks mileage preparation, separate from financial imports."""

from .common import DTO


class MileageImportSummary(DTO):
    ready: int
    duplicates: int
    personal_skipped: int
    unreviewed_skipped: int


class MileageImportRow(DTO):
    trip_date: str
    miles: str
    vehicle: str
    start_location: str
    destination: str
    business_purpose: str
    notes: str


class MileageImportPreview(DTO):
    summary: MileageImportSummary
    rows: list[MileageImportRow]
    source_rows: list[dict[str, str]]
    errors: list[str]
    duplicate_rows: list[int]
    personal_rows: list[int]
    unreviewed_rows: list[int]


class MileageImportResult(DTO):
    imported: int
    ids: list[str]
