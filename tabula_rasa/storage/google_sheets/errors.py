"""Stable, user-safe errors raised by Google Sheets storage."""

from __future__ import annotations

from tabula_rasa.errors import (
    StorageConflictError,
    StorageError,
    StorageNotFoundError,
    StorageValidationError,
)

class StorageUnavailableError(StorageError):
    """Raised when Google Sheets cannot complete an API operation."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable

def _mutation_guidance(operation: str) -> str:
    """Return the common user-facing guidance for an unconfirmed write."""
    operation_key = operation.casefold()
    if "mixed-use" in operation_key or "mixeduse" in operation_key:
        inspection_area = "Mixed-use expenses and the Transactions ledger"
    elif "payee" in operation_key:
        inspection_area = (
            "Payee management and the Transactions and MixedUseExpenses tables"
        )
    elif "tag" in operation_key:
        inspection_area = (
            "Tag management and the Transactions, Mileage, and MixedUseExpenses tables"
        )
    elif "category" in operation_key:
        inspection_area = "Categories and the Transactions ledger"
    elif "account" in operation_key:
        inspection_area = (
            "Accounts and the Transactions, Mileage, and MixedUseExpenses tables"
        )
    elif "mileage" in operation_key:
        inspection_area = "the Mileage log"
    elif any(keyword in operation_key for keyword in ("bulk", "transaction")):
        inspection_area = "the Transactions ledger"
    elif "receipt" in operation_key:
        inspection_area = "the receipt records and linked ledger rows"
    else:
        inspection_area = "the affected records"
    return (
        f"Google Sheets could not confirm the {operation}. Refresh and inspect "
        f"{inspection_area} before trying again; no success was reported."
    )

class StorageAuthenticationError(StorageUnavailableError):
    """Raised when Google rejects the profile Google OAuth authorization."""

class StorageWorkbookAccessError(StorageUnavailableError):
    """Raised when the configured spreadsheet cannot be opened."""

class StorageInitializationError(StorageUnavailableError):
    """Raised when an accessible workbook cannot be initialized."""

__all__ = [
    "StorageError",
    "StorageUnavailableError",
    "StorageAuthenticationError",
    "StorageWorkbookAccessError",
    "StorageInitializationError",
    "StorageValidationError",
    "StorageConflictError",
    "StorageNotFoundError",
    "_mutation_guidance",
]
