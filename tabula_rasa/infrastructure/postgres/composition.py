"""Opt-in core service graph; production authority selection belongs to #258."""

from tabula_rasa.application.services import assemble_application_services
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
    return assemble_application_services(
        entity_id, ledger_repository=ledger,
        account_repository=PostgresAccountRepository(database, entity_id),
        category_repository=PostgresCategoryRepository(database, entity_id),
        payee_repository=PostgresPayeeRepository(database, entity_id),
        tag_repository=PostgresTagRepository(database, entity_id),
        transaction_repository=PostgresTransactionRepository(database, entity_id),
        journal_repository=PostgresJournalRepository(database, entity_id),
    )
