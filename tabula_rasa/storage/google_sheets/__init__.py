"""Stable public facade for Google Sheets persistence."""

from .base import (
    _StoredRow,
)
from .client import Credentials, _GoogleSheetsStorageClient, gspread
from .errors import (
    StorageAuthenticationError,
    StorageConflictError,
    StorageError,
    StorageInitializationError,
    StorageNotFoundError,
    StorageUnavailableError,
    StorageValidationError,
    StorageWorkbookAccessError,
    _mutation_guidance,
)
from .accounts import AccountsMixin
from .assets import ASSET_TYPES, AssetsMixin
from .backup import BackupMixin
from .mileage import MileageMixin
from .mixed_use import _MixedUseMixin
from .payees import PayeesMixin
from .receipts import ReceiptsMixin
from .schema import (
    ACCOUNT_CLASSIFICATIONS,
    ACCOUNT_TYPES,
    BACKUP_FORMAT_VERSION,
    WORKBOOK_FORMAT_VERSION,
    CATEGORY_KINDS,
    DEFAULT_ACCOUNTS,
    DEFAULT_CATEGORIES,
    FIXED_TYPE_CLASSIFICATIONS,
    MIXED_USE_WORKSHEET_HEADERS,
    SHEETS_READONLY_SCOPE,
    SHEETS_SCOPE,
    TRANSACTION_KINDS,
    WORKSHEET_HEADERS,
)
from .validation import (
    _clean_text,
    _normalize_tag_ids,
    _utc_now,
    decode_receipt_references,
    mixed_use_ledger_description,
    normalize_payee_name,
    normalize_tag_name,
)
from .transactions import TransactionsMixin
from .tags import TagsMixin


class GoogleSheetsStorage(
    _GoogleSheetsStorageClient,
    AccountsMixin,
    AssetsMixin,
    PayeesMixin,
    TagsMixin,
    TransactionsMixin,
    _MixedUseMixin,
    ReceiptsMixin,
    MileageMixin,
    BackupMixin,
):
    """Operator facade for format-13 source, backup and receipt recovery."""


__all__ = [
    "GoogleSheetsStorage",
    "ASSET_TYPES",
    "StorageError",
    "StorageUnavailableError",
    "StorageAuthenticationError",
    "StorageWorkbookAccessError",
    "StorageInitializationError",
    "StorageValidationError",
    "StorageConflictError",
    "StorageNotFoundError",
    "decode_receipt_references",
    "normalize_payee_name",
    "normalize_tag_name",
    "mixed_use_ledger_description",
    "WORKSHEET_HEADERS",
    "MIXED_USE_WORKSHEET_HEADERS",
    "SHEETS_SCOPE",
    "SHEETS_READONLY_SCOPE",
    "BACKUP_FORMAT_VERSION",
    "WORKBOOK_FORMAT_VERSION",
    "ACCOUNT_TYPES",
    "ACCOUNT_CLASSIFICATIONS",
    "FIXED_TYPE_CLASSIFICATIONS",
    "CATEGORY_KINDS",
    "TRANSACTION_KINDS",
    "DEFAULT_ACCOUNTS",
    "DEFAULT_CATEGORIES",
    "_StoredRow",
    "_mutation_guidance",
    "_clean_text",
    "_normalize_tag_ids",
    "_utc_now",
    "Credentials",
    "gspread",
]
