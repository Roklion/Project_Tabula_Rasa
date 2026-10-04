"""Assemble application services from explicit, persistence-neutral contracts."""

from dataclasses import dataclass

from .contracts import LedgerSetupRepository
from .documents import DocumentStore, ReceiptRepository, ReceiptService
from .ledger_setup import LedgerSetupService
from .mileage import MileageService
from .mileage_contracts import MileageRepository
from .reporting import ReportingService
from .reporting_contracts import LedgerQueryRepository
from .contracts import (
    AccountRepository,
    PayeeRepository,
    TagRepository,
)
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
    reporting: ReportingService | None = None
    receipts: ReceiptService | None = None
    mileage: MileageService | None = None


def assemble_application_services(
    profile_key: str,
    *,
    ledger_repository: LedgerSetupRepository,
    reporting_repository: LedgerQueryRepository | None = None,
    receipt_repository: ReceiptRepository | None = None,
    document_store: DocumentStore | None = None,
    mileage_repository: MileageRepository | None = None,
    account_repository: AccountRepository | None = None,
    payee_repository: PayeeRepository | None = None,
    tag_repository: TagRepository | None = None,
) -> ApplicationServices:
    """Compose the service graph without constructing infrastructure clients."""
    if not isinstance(profile_key, str) or not profile_key.strip():
        raise ValueError("Application services require a selected business profile.")
    if (receipt_repository is None) != (document_store is None):
        raise ValueError("Receipt services require both metadata and document storage.")
    return ApplicationServices(
        profile_key=profile_key,
        ledger=LedgerSetupService(ledger_repository),
        reporting=(
            ReportingService(reporting_repository)
            if reporting_repository is not None else None
        ),
        receipts=(
            ReceiptService(profile_key, receipt_repository, document_store)
            if receipt_repository is not None and document_store is not None else None
        ),
        mileage=(
            MileageService(mileage_repository)
            if mileage_repository is not None else None
        ),
        accounts=AccountService(account_repository)
        if account_repository is not None
        else None,
        payees=PayeeService(payee_repository) if payee_repository is not None else None,
        tags=TagService(tag_repository) if tag_repository is not None else None,
    )
