"""Assemble application services from explicit, persistence-neutral contracts."""

from dataclasses import dataclass

from .contracts import LedgerSetupRepository
from .ledger_setup import LedgerSetupService


@dataclass(frozen=True)
class ApplicationServices:
    """Services for one explicitly selected business profile.

    The profile key identifies the internal application's configuration scope;
    it is not commercial user authorization. Add domain services as their
    vertical slices are extracted rather than mirroring the storage facade.
    """

    profile_key: str
    ledger: LedgerSetupService


def assemble_application_services(
    profile_key: str,
    *,
    ledger_repository: LedgerSetupRepository,
) -> ApplicationServices:
    """Compose the service graph without constructing infrastructure clients."""
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise ValueError("Application services require a selected business profile.")
    return ApplicationServices(
        profile_key=profile_key,
        ledger=LedgerSetupService(ledger_repository),
    )
