from alembic import command
import pytest

from tabula_rasa.deployment import staging_maintenance as maintenance
from tabula_rasa.infrastructure.postgres.migrations import migration_config
from tests.postgres.core_support import seed_core, expense


def test_reviewed_bridge_preserves_existing_two_business_records(empty_database, monkeypatch):
    database = empty_database
    # Reproduce the retained immutable candidate, not today's migration head.
    monkeypatch.setattr(maintenance, 'head_revision', lambda: maintenance.TARGET)
    def candidate_upgrade(database):
        with database.engine.begin() as connection:
            command.upgrade(migration_config(connection), maintenance.TARGET)
    monkeypatch.setattr(maintenance, 'upgrade', candidate_upgrade)
    with database.engine.begin() as connection:
        command.upgrade(migration_config(connection), maintenance.SOURCE)
    alpha, beta = seed_core(database)
    records = [alpha.transactions.create(transaction_id='existing-a', **expense()),
               beta.transactions.create(transaction_id='existing-b', **expense(amount='22.22'))]
    monkeypatch.setattr(maintenance, 'open_alpha_database', lambda env: database)
    # Keep the fixture pool for the post-upgrade reads; real command disposes it.
    real_dispose = database.dispose
    monkeypatch.setattr(database, 'dispose', lambda: None)
    try:
        result = maintenance.migrate({**maintenance.SCOPE, 'MAINTENANCE_RECOVERY_SHA256': '1' * 64,
                                      'TABULA_RASA_RELEASE_ID': maintenance.RELEASE})
        assert result['target_schema'] == maintenance.TARGET
        assert alpha.transactions.list() == [records[0]]
        assert beta.transactions.list() == [records[1]]
        assert alpha.periods.list() == beta.periods.list() == {'enabled': False, 'items': []}
        with pytest.raises(ValueError):
            maintenance.migrate({**maintenance.SCOPE, 'MAINTENANCE_RECOVERY_SHA256': '1' * 64,
                                 'TABULA_RASA_RELEASE_ID': maintenance.RELEASE})
    finally:
        real_dispose()
