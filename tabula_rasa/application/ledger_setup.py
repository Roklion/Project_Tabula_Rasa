"""Application access to ledger setup, independent of the persistence provider."""

from dataclasses import dataclass

from .contracts import LedgerSetupRepository


@dataclass(frozen=True)
class LedgerInfo:
    """Display metadata, without provider handles or credentials."""

    name: str


class LedgerSetupService:
    """Expose the ledger's setup capability through an explicit repository port."""

    def __init__(self, repository: LedgerSetupRepository) -> None:
        self._repository = repository

    def get_info(self) -> LedgerInfo:
        return LedgerInfo(name=self._repository.ledger_name)

    def ensure_defaults(self) -> dict[str, int]:
        return self._repository.ensure_defaults()
