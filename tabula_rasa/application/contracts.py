"""Small ports owned by the application capabilities that consume them."""

from typing import Protocol


class LedgerSetupRepository(Protocol):
    """The current ledger's display identity and supported initial defaults.

    Implementations own persistence and propagate failures without reporting
    success. This initial compatibility port leaves the existing default rules
    in the backend until the reference-data service is extracted.
    """

    @property
    def ledger_name(self) -> str: ...

    def ensure_defaults(self) -> dict[str, int]:
        """Return counts of created accounts/categories, or fail."""
        ...
