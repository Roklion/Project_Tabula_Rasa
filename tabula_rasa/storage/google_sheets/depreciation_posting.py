"""Compatibility exports for provider-independent depreciation rules."""
from tabula_rasa.depreciation_posting import (
    DEPRECIATION_SOURCE_TYPE, asset_schedule, depreciation_entry_id,
    validate_depreciation_accounts, validate_depreciation_history,
)

__all__ = ["DEPRECIATION_SOURCE_TYPE", "asset_schedule", "depreciation_entry_id",
           "validate_depreciation_accounts", "validate_depreciation_history"]
