"""Assemble application services from explicit, persistence-neutral contracts."""

from dataclasses import dataclass

from .contracts import (
    AccountRepository,
    LedgerSetupRepository,
    PayeeRepository,
    TagRepository,
)
from .ledger_setup import LedgerSetupService
from .reference_data import AccountService, PayeeService, TagService


@dataclass(frozen=True)
class ApplicationServices:
    """Services for one explicitly selected business profile.

    The profile key identifies the internal application's configuration scope;
    it is not commercial user authorization. Add domain services as their
    vertical slices are extracted rather than mirroring the storage facade.
    """

    profile_key: str
    ledger: LedgerSetupService
    accounts: AccountService | None = None
    payees: PayeeService | None = None
    tags: TagService | None = None


def assemble_application_services(
    profile_key: str,
    *,
    ledger_repository: LedgerSetupRepository,
    account_repository: AccountRepository | None = None,
    payee_repository: PayeeRepository | None = None,
    tag_repository: TagRepository | None = None,
) -> ApplicationServices:
    """Compose the service graph without constructing infrastructure clients."""
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise ValueError("Application services require a selected business profile.")
    return ApplicationServices(
        profile_key=profile_key,
        ledger=LedgerSetupService(ledger_repository),
        accounts=AccountService(account_repository)
        if account_repository is not None
        else None,
        payees=PayeeService(payee_repository) if payee_repository is not None else None,
        tags=TagService(tag_repository) if tag_repository is not None else None,
    )
