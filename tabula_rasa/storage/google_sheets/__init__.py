"""Stable public facade for Google Sheets persistence."""

from .base import (
    _MIXED_USE_CREATE_LOCK,
    _PAYEE_WRITE_LOCK,
    _TAG_WRITE_LOCK,
    _StoredRow,
    _active_ledger_mutation_lock,
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
from .backup import BackupMixin
from .managed import _ManagedMixin
from .mileage import MileageMixin
from .mixed_use import _MixedUseMixin
from .receipts import ReceiptsMixin
from .schema import (
    ACCOUNT_CLASSIFICATIONS,
    ACCOUNT_TYPES,
    BACKUP_FORMAT_VERSION,
    CATEGORY_KINDS,
    DEFAULT_ACCOUNTS,
    DEFAULT_CATEGORIES,
    FIXED_TYPE_CLASSIFICATIONS,
    LEGACY_TAGS_WORKBOOK_HEADERS,
    MIXED_USE_WORKSHEET_HEADERS,
    PRE_MIXED_USE_WORKSHEET_HEADERS,
    PRE_PAYEE_WORKSHEET_HEADERS,
    SHEETS_READONLY_SCOPE,
    SHEETS_SCOPE,
    TRANSACTION_KINDS,
    VERSION_3_WORKSHEET_HEADERS,
    VERSION_5_WORKSHEET_HEADERS,
    VERSION_6_WORKSHEET_HEADERS,
    VERSION_7_WORKSHEET_HEADERS,
    WORKSHEET_HEADERS,
)
from .validation import (
    _clean_text,
    _legacy_payee_id,
    _looks_like_historical_workbook,
    _looks_like_partial_blank_workbook,
    _utc_now,
    _validate_hierarchy_records,
    _validate_payee_records,
    decode_receipt_references,
    mixed_use_ledger_description,
    normalize_payee_name,
    normalize_tag_name,
)
from .transactions import TransactionsMixin


class GoogleSheetsStorage(
    _GoogleSheetsStorageClient,
    AccountsMixin,
    _ManagedMixin,
    TransactionsMixin,
    _MixedUseMixin,
    ReceiptsMixin,
    MileageMixin,
    BackupMixin,
):
    """Compatibility facade preserving the existing storage API."""


__all__ = [
    "GoogleSheetsStorage",
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
    "PRE_MIXED_USE_WORKSHEET_HEADERS",
    "SHEETS_SCOPE",
    "SHEETS_READONLY_SCOPE",
    "BACKUP_FORMAT_VERSION",
    "ACCOUNT_TYPES",
    "ACCOUNT_CLASSIFICATIONS",
    "FIXED_TYPE_CLASSIFICATIONS",
    "CATEGORY_KINDS",
    "TRANSACTION_KINDS",
    "DEFAULT_ACCOUNTS",
    "DEFAULT_CATEGORIES",
    "LEGACY_TAGS_WORKBOOK_HEADERS",
    "PRE_PAYEE_WORKSHEET_HEADERS",
    "VERSION_3_WORKSHEET_HEADERS",
    "VERSION_5_WORKSHEET_HEADERS",
    "VERSION_6_WORKSHEET_HEADERS",
    "VERSION_7_WORKSHEET_HEADERS",
    "_MIXED_USE_CREATE_LOCK",
    "_PAYEE_WRITE_LOCK",
    "_TAG_WRITE_LOCK",
    "_StoredRow",
    "_active_ledger_mutation_lock",
    "_mutation_guidance",
    "_clean_text",
    "_legacy_payee_id",
    "_looks_like_historical_workbook",
    "_looks_like_partial_blank_workbook",
    "_utc_now",
    "_validate_hierarchy_records",
    "_validate_payee_records",
    "Credentials",
    "gspread",
]
