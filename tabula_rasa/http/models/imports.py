"""Transaction import projections; uploaded source rows never become commands."""

from typing import Literal

from pydantic import Field

from .common import DTO


class TransactionCsvPreview(DTO):
    columns: list[str]
    source_rows: list[dict[str, str]]
    total_rows: int
    errors: list[str] = Field(default_factory=list)


class ImportSummary(DTO):
    ready: int
    duplicates: int
    Income: int
    Expense: int
    Transfer: int
    validation_errors: int
    conversion_errors: int


class ImportAccountProposal(DTO):
    name: str
    type: str
    classification: str
    opening_balance: str = "0.00"


class ImportCategoryProposal(DTO):
    name: str
    kind: str


class QuickBooksImportPreview(TransactionCsvPreview):
    summary: ImportSummary
    errors: list[str]
    conversion_errors: list[str]
    duplicate_rows: list[int]
    new_accounts: list[ImportAccountProposal]
    new_categories: list[ImportCategoryProposal]


class TransactionImportResult(DTO):
    status: Literal["fully_applied"] = "fully_applied"
    imported_count: int
    transaction_ids: list[str]
