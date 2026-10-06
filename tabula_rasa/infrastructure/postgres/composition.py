"""Opt-in entity service graph; production authority selection belongs to #258."""

from dataclasses import replace

from tabula_rasa.application.recurring import RecurringService
from tabula_rasa.application.services import assemble_application_services
from .assets import PostgresAssetRepository
from .mixed_use import PostgresMixedUseRepository
from .recurring import PostgresRecurringRepository
from .accounting import PostgresTransactionRepository, PostgresJournalRepository
from .reference_data import (
    PostgresLedgerSetupRepository, PostgresAccountRepository, PostgresCategoryRepository,
    PostgresPayeeRepository, PostgresTagRepository,
)


def create_postgres_services(database, entity_id):
    """Compose one explicit entity using the shared infrastructure operation.

    The caller resolves authorized entity context and owns database lifecycle.
    This does not activate a backend, create an entity or migrate its schema.
    """
    ledger = PostgresLedgerSetupRepository(database, entity_id)
    ledger.ledger_name  # Reject an unknown entity before returning a service graph.
    services = assemble_application_services(
        entity_id, ledger_repository=ledger,
        account_repository=PostgresAccountRepository(database, entity_id),
        category_repository=PostgresCategoryRepository(database, entity_id),
        payee_repository=PostgresPayeeRepository(database, entity_id),
        tag_repository=PostgresTagRepository(database, entity_id),
        transaction_repository=PostgresTransactionRepository(database, entity_id),
        journal_repository=PostgresJournalRepository(database, entity_id),
        asset_repository=PostgresAssetRepository(database, entity_id),
        mixed_use_repository=PostgresMixedUseRepository(database, entity_id),
    )
    # Initial creation/conversion uses these same service preparation owners;
    # reconciliation generates through the same transaction/mixed services.
    recurring = PostgresRecurringRepository(
        database, entity_id, transactions=services.transactions, mixed_use=services.mixed_use,
    )
    return replace(services, recurring=RecurringService(recurring,
                   transactions=services.transactions, mixed_use=services.mixed_use))
