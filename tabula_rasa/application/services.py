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
from .accounting_contracts import TransactionRepository, JournalRepository
from .transactions import TransactionService
from .journals import JournalService


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
    transactions: TransactionService | None = None
    journals: JournalService | None = None


def assemble_application_services(
    profile_key: str,
    *,
    ledger_repository: LedgerSetupRepository,
    account_repository: AccountRepository | None = None,
    payee_repository: PayeeRepository | None = None,
    tag_repository: TagRepository | None = None,
    transaction_repository: TransactionRepository | None = None,
    journal_repository: JournalRepository | None = None,
) -> ApplicationServices:
    """Compose the service graph without constructing infrastructure clients."""
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise ValueError("Application services require a selected business profile.")
    payees = PayeeService(payee_repository) if payee_repository is not None else None
    tags = TagService(tag_repository) if tag_repository is not None else None
    if transaction_repository is not None and (payees is None or tags is None):
        raise ValueError("Transaction services require payee and tag repositories.")
    return ApplicationServices(
        profile_key=profile_key,
        ledger=LedgerSetupService(ledger_repository),
        accounts=AccountService(account_repository)
        if account_repository is not None
        else None,
        payees=payees,
        tags=tags,
        transactions=TransactionService(
            transaction_repository, payees=payees, tags=tags
        )
        if transaction_repository is not None
        else None,
        journals=JournalService(journal_repository)
        if journal_repository is not None
        else None,
    )
