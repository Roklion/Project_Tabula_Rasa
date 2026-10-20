"""Synthetic isolated restores; these are not managed PITR or NAS device evidence."""

from contextlib import contextmanager
from copy import deepcopy
import os
import re
import subprocess
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

from tabula_rasa.application.entity_export import ExportError
from tabula_rasa.application.identity import IdentityError
from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from tabula_rasa.infrastructure.postgres.audit import AuditContext, audit_context
from tabula_rasa.infrastructure.postgres.audit_recovery import capture_audit_recovery, verify_audit_recovery
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.cutover import database_identity
from tabula_rasa.infrastructure.postgres.imports import PostgresTransactionImportRepository
from tabula_rasa.infrastructure.postgres.migrations import migration_config, upgrade
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError
from tests.postgres.core_support import seed_core, expense
from tests.postgres.document_restore_support import cloned_database
from tests.postgres.secondary_support import schedule
from tests.postgres.test_audit import CAPABILITIES, reader
from tests.postgres.test_import_repository import csv
from tests.postgres.test_jobs import queue, due
from tests.postgres.test_periods import close


def capture(database, scope='alpha'):
    return capture_audit_recovery(database, scope, capabilities=CAPABILITIES)


def verify(database, expected, scope='alpha', **kwargs):
    return verify_audit_recovery(database, scope, expected, capabilities=CAPABILITIES,
        source_database_sha256=expected['source_database_sha256'],
        target_database_sha256=database_identity(database), **kwargs)


def test_restored_history_ids_attribution_period_controls_and_two_entity_scope(database):
    alpha, beta = seed_core(database)
    for scope, services in [('alpha', alpha), ('beta', beta)]:
        with audit_context(database, AuditContext('operator', 'synthetic-'+scope, 'restore-canary', scope)):
            services.transactions.create(transaction_id='same-local-id', **expense())
    close(database, alpha)
    expected = {scope: capture(database, scope) for scope in ('alpha', 'beta')}
    identities = {scope: reader(database, scope).query(limit=1000) for scope in expected}
    with cloned_database(database) as restored:
        statements = []
        def observe(connection, cursor, statement, parameters, context, many):
            statements.append(statement)
        event.listen(restored.engine, 'before_cursor_execute', observe)
        try:
            for scope in expected:
                report = verify(restored, expected[scope], scope)
                assert report['event_count'] == len(identities[scope])
                assert reader(restored, scope).query(limit=1000) == identities[scope]
            assert 'SET TRANSACTION READ ONLY' in statements
            assert not any(s.split()[0].upper() in {'INSERT','UPDATE','DELETE','CREATE','ALTER','DROP','TRUNCATE'} for s in statements)
        finally:
            event.remove(restored.engine, 'before_cursor_execute', observe)
        services = create_postgres_services(restored, 'alpha')
        with pytest.raises(StorageConflictError) as caught:
            services.transactions.create(transaction_id='closed-month', **expense())
        assert caught.value.code == 'period_closed'
        assert verify(restored, expected['alpha'])['status'] == 'matched'  # Sequence gaps after rollback are valid.
        with pytest.raises(ExportError, match='audit_manifest_scope'):
            verify(restored, expected['alpha'], 'beta')


def test_restore_before_and_after_atomic_commit_excludes_later_tail(database):
    alpha, _ = seed_core(database)
    before = capture(database)
    with cloned_database(database) as point_before:
        alpha.transactions.create(transaction_id='commit-boundary', **expense())
        after = capture(database)
        assert verify(point_before, before, later=after)['status'] == 'matched'
        assert create_postgres_services(point_before, 'alpha').transactions.list() == []
        with pytest.raises(ExportError, match='audit_recovery_mismatch'):
            verify(point_before, after)
        with pytest.raises(ExportError, match='audit_pitr_control_unchanged'):
            verify(point_before, before, later=before)
    with cloned_database(database) as point_after:
        assert verify(point_after, after)['status'] == 'matched'
        assert reader(point_after).query(target_type='entries', target_id='commit-boundary')
        with pytest.raises(ExportError, match='audit_pitr_control_unchanged'):
            verify(point_after, after, later=before)


def test_lost_response_then_restore_and_duplicate_retry_preserves_event_ids(database, monkeypatch):
    alpha, _ = seed_core(database)
    original = database.transaction
    lost = False
    @contextmanager
    def lose_once(**kwargs):
        nonlocal lost
        outer = database._operation.get() is None and not lost and not kwargs.get('read_only')
        with original(**kwargs) as connection:
            yield connection
        if outer:
            lost = True
            raise DatabaseError('unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(database, 'transaction', lose_once)
        with pytest.raises(StorageError):
            alpha.transactions.create(transaction_id='lost-response', **expense())
    expected = capture(database)
    with cloned_database(database) as restored:
        services = create_postgres_services(restored, 'alpha')
        with pytest.raises(StorageConflictError):
            services.transactions.create(transaction_id='lost-response', **expense())
        assert len(reader(restored).query(target_type='entries', target_id='lost-response')) == 1
        assert verify(restored, expected)['status'] == 'matched'


def test_partial_import_and_independent_worker_replay_after_restore(database):
    alpha, _ = seed_core(database)
    first, rejected = [csv()], [csv(Account='missing', Reference='chunk-2')]
    repo = PostgresTransactionImportRepository(database, 'alpha')
    chunks = [repo.identity('csv', values) for values in (first, rejected)]
    alpha.imports.import_csv(first)
    with pytest.raises(StorageValidationError):
        alpha.imports.import_csv(rejected)
    alpha.recurring.create(schedule_id='monthly', **schedule())
    def reconcile(participant, execution):
        return create_postgres_services(participant, execution.entity_id).recurring.reconcile(as_of='2026-02-01')
    def committed_then_failed(participant, execution):
        reconcile(participant, execution)
        raise DatabaseError('unavailable')
    worker = queue(database, handler=committed_then_failed, independent=True)
    identity = worker.enqueue('test.post', 'replay-after-restore')
    assert worker.tick() is False
    expected = capture(database)
    events = reader(database).query(limit=1000)
    with cloned_database(database) as restored:
        assert verify(restored, expected)['status'] == 'matched'
        services = create_postgres_services(restored, 'alpha')
        services.imports.import_csv(first)
        due(restored, identity)
        assert queue(restored, handler=reconcile, independent=True).tick() is True
        assert reader(restored).query(limit=1000) == events
        assert verify(restored, expected)['status'] == 'matched'
        assert reader(restored).import_status(chunks)['status'] == 'partial'
        assert reader(restored, 'beta').import_status(chunks)['status'] == 'unconfirmed'


@pytest.mark.parametrize('damage', ['earlier-event','actor','entity','watermark','baseline','ledger',
                                   'trigger','policy','function','sequence','constraint'])
def test_incomplete_or_mismatched_restores_are_rejected(database, damage):
    alpha, _ = seed_core(database)
    made = alpha.transactions.create(transaction_id='history', **expense())
    alpha.transactions.update('history', expected=made, amount='20')
    expected = capture(database)
    with cloned_database(database) as restored:
        # Deliberate DBA-only damage on a fresh disposable target. Never a repair
        # method; proves rejection even if a latest-state scan alone still matches.
        with restored.engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role='replica'"))
            query = {
                'earlier-event': "DELETE FROM audit_events WHERE entity_id='alpha' AND target_type='entries' AND action='create'",
                'actor': "UPDATE audit_events SET actor_id='wrong-synthetic-actor' WHERE entity_id='alpha'",
                'entity': "UPDATE audit_events SET entity_id='beta' WHERE entity_id='alpha' AND target_type='entries'",
                'watermark': "UPDATE audit_activation SET activated_at=activated_at-interval '1 day'",
                'baseline': "INSERT INTO audit_baseline VALUES ('alpha','entries','{\"id\":\"invented\"}','bad','pre_activation_unavailable')",
                'ledger': "UPDATE entries SET description='mismatched snapshot' WHERE entity_id='alpha'",
                'trigger': 'ALTER TABLE entries DISABLE TRIGGER audit_capture',
                'policy': 'DROP POLICY scoped_audit_read ON audit_events',
                'function': "CREATE OR REPLACE FUNCTION audit_summary(value jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS 'SELECT value'",
                'sequence': "SELECT setval('audit_events_sequence_seq',1,false)",
                'constraint': 'ALTER TABLE audit_events DROP CONSTRAINT audit_events_pkey',
            }[damage]
            connection.execute(text(query))
        if damage in {'earlier-event', 'actor', 'watermark', 'trigger', 'policy', 'function', 'sequence', 'constraint'}:
            assert reader(restored).verify()['status'] == 'matched'
        with pytest.raises(ExportError):
            verify(restored, expected)


def test_preactivation_restore_is_unavailable_and_forward_upgrade_preserves_archive(empty_database):
    database = empty_database
    with database.engine.begin() as connection:
        command.upgrade(migration_config(connection), '0011_control_plane_join')
    alpha, _ = seed_core(database)
    alpha.transactions.create(transaction_id='old', **expense())
    with cloned_database(database) as old:
        with pytest.raises(ExportError, match='audit_history_unavailable'):
            capture(old)
    with database.engine.begin() as connection:
        command.upgrade(migration_config(connection), '0013_accounting_controls')
    alpha.transactions.create(transaction_id='new', **expense())
    expected = capture(database)
    events, boundary = reader(database).query(), reader(database).boundary()
    with cloned_database(database) as restored:
        assert verify(restored, expected)['history_status'] == 'pre_activation_unavailable'
        upgrade(restored)
        assert reader(restored).query() == events and reader(restored).boundary() == boundary
        assert reader(restored).verify()['mismatches'] == 0
        # Upgrading first is never evidence of the original restored revision.
        with pytest.raises(ExportError, match='audit_recovery_mismatch'):
            verify(restored, expected)


def test_manifest_authorization_endpoint_and_checksum_fail_closed(database):
    seed_core(database)
    with pytest.raises(IdentityError):
        capture_audit_recovery(database, 'alpha', capabilities=frozenset({'bookkeeping:read','bookkeeping:export'}))
    expected = capture(database)
    with pytest.raises(ExportError, match='recovery_target'):
        verify(database, expected)
    broken = deepcopy(expected)
    broken['state']['events']['count'] += 1
    with pytest.raises(ExportError, match='audit_manifest_invalid'):
        verify(database, broken)


def test_history_comparison_preserves_exact_financial_json_precision(database):
    alpha, _ = seed_core(database)
    alpha.transactions.create(transaction_id='precision', **expense(amount='9007199254740992.01'))
    expected = capture(database)
    with cloned_database(database) as restored:
        with restored.engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role='replica'"))
            connection.execute(text("""UPDATE audit_events SET after_summary=jsonb_set(
                after_summary,'{amount}','9007199254740992.02'::jsonb)
                WHERE entity_id='alpha' AND target_type='entries'"""))
        assert reader(restored).verify()['status'] == 'matched'
        with pytest.raises(ExportError, match='audit_recovery_mismatch'):
            verify(restored, expected)


def test_restored_nonowner_inspector_uses_same_snapshot_and_rls_scope(database):
    alpha, beta = seed_core(database)
    for services in (alpha, beta):
        services.transactions.create(transaction_id='same-id', **expense())
    role = 'audit_restore_' + uuid4().hex
    with database.engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE ROLE "{role}" NOLOGIN')
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA public TO "{role}"')
        connection.exec_driver_sql(f'GRANT SELECT ON ALL TABLES IN SCHEMA public TO "{role}"')
        connection.exec_driver_sql(f'GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
    try:
        expected = {scope: capture(database, scope) for scope in ('alpha', 'beta')}
        with cloned_database(database) as restored:
            def inspector(connection):
                connection.exec_driver_sql(f'SET LOCAL ROLE "{role}"')
            event.listen(restored.engine, 'begin', inspector)
            try:
                for scope in expected:
                    assert verify(restored, expected[scope], scope)['event_count'] == expected[scope]['state']['events']['count']
                    with reader(restored, scope).operation() as connection:
                        assert connection.scalar(text('SELECT current_user')) == role
                        assert set(connection.execute(text('SELECT entity_id FROM audit_events')).scalars()) == {scope}
            finally:
                event.remove(restored.engine, 'begin', inspector)
    finally:
        with database.engine.begin() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY "{role}"')
            connection.exec_driver_sql(f'DROP ROLE "{role}"')


def test_equivalent_explicit_and_default_sequence_acls_compare_equal(database):
    seed_core(database)
    before = capture(database)
    with database.engine.begin() as connection:
        # Converts a NULL ACL into its explicit equivalent without changing
        # effective sequence privileges. Logical restores may do the reverse.
        connection.execute(text('REVOKE ALL ON SEQUENCE audit_events_sequence_seq FROM PUBLIC'))
    assert capture(database)['state'] == before['state']


@pytest.mark.parametrize('drift', ['policy','extra-policy','trigger-events','trigger-keys'])
def test_drifted_source_protections_cannot_be_blessed_as_an_oracle(database, drift):
    seed_core(database)
    with database.engine.begin() as connection:
        if drift == 'policy':
            connection.execute(text('ALTER POLICY scoped_audit_read ON audit_events USING (true)'))
        elif drift == 'extra-policy':
            connection.execute(text('CREATE POLICY unrestricted ON audit_events FOR SELECT USING (true)'))
        else:
            connection.execute(text('DROP TRIGGER audit_capture ON entries'))
            operations, key = ('INSERT', 'id') if drift == 'trigger-events' else ('INSERT OR UPDATE OR DELETE', 'entity_id')
            connection.execute(text(f'''CREATE CONSTRAINT TRIGGER audit_capture AFTER {operations} ON entries
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION capture_bookkeeping_audit('{key}')'''))
    assert reader(database).verify()['status'] == 'matched'
    with pytest.raises(ExportError, match='audit_schema_incomplete'):
        capture(database)


@pytest.mark.parametrize('function', ['audit_immutable','audit_insert_guard','audit_summary',
                                     'audit_row_digest','capture_bookkeeping_audit','capture-search-path'])
def test_source_function_drift_is_checked_against_frozen_migration_definitions(database, function):
    alpha, _ = seed_core(database)
    original = alpha.transactions.create(transaction_id='older-event', **expense())
    alpha.transactions.update('older-event', expected=original, amount='20')
    with database.engine.begin() as connection:
        sql = {
            'audit_immutable': "CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN OLD; END'",
            'audit_insert_guard': "CREATE OR REPLACE FUNCTION audit_insert_guard() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'",
            'audit_summary': "CREATE OR REPLACE FUNCTION audit_summary(value jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS 'SELECT value'",
            'audit_row_digest': "CREATE OR REPLACE FUNCTION audit_row_digest(value jsonb,table_name text) RETURNS text LANGUAGE sql IMMUTABLE AS $$SELECT 'wrong'::text$$",
            'capture_bookkeeping_audit': "CREATE OR REPLACE FUNCTION capture_bookkeeping_audit() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public,pg_temp AS 'BEGIN RETURN NULL; END'",
            'capture-search-path': 'ALTER FUNCTION capture_bookkeeping_audit() SET search_path=pg_temp,public',
        }[function]
        connection.execute(text(sql))
        if function == 'audit_immutable':
            # Same-name no-op protection permits this deletion. A latest-event
            # scan still matches, so function validation must reject capture.
            connection.execute(text("DELETE FROM audit_events WHERE target_type='entries' AND action='create'"))
    if function == 'audit_immutable':
        assert reader(database).verify()['status'] == 'matched'
    with pytest.raises(ExportError, match='audit_schema_incomplete'):
        capture(database)


@pytest.mark.parametrize('drift', ['period-function', 'correction-function', 'authority-function',
                                  'missing-period-trigger', 'disabled-period-trigger'])
def test_source_period_and_correction_guards_are_required_before_capture(database, drift):
    alpha, _ = seed_core(database)
    alpha.transactions.create(transaction_id='closed-month', **expense())
    close(database, alpha)
    query = {
        'period-function': "CREATE OR REPLACE FUNCTION guard_accounting_period() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'",
        'correction-function': "CREATE OR REPLACE FUNCTION guard_entry_correction() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'",
        'authority-function': "CREATE OR REPLACE FUNCTION require_period_authority(scope text, action text) RETURNS void LANGUAGE plpgsql AS 'BEGIN RETURN; END'",
        'missing-period-trigger': 'DROP TRIGGER accounting_period_guard ON entries',
        'disabled-period-trigger': 'ALTER TABLE postings DISABLE TRIGGER accounting_period_guard',
    }[drift]
    with database.engine.begin() as connection:
        connection.execute(text(query))
    assert reader(database).verify()['status'] == 'matched'
    with pytest.raises(ExportError, match='audit_schema_incomplete'):
        capture(database)


@pytest.mark.parametrize('drift', ['rls', 'read-policy', 'insert-policy', 'extra-policy', 'immutable'])
def test_source_support_history_protections_are_required_before_capture(database, drift):
    seed_core(database)
    query = {
        'rls': 'ALTER TABLE support_actions DISABLE ROW LEVEL SECURITY',
        'read-policy': 'ALTER POLICY scoped_support_read ON support_actions USING (true)',
        'insert-policy': 'ALTER POLICY scoped_support_insert ON support_actions WITH CHECK (true)',
        'extra-policy': 'CREATE POLICY unrestricted ON support_actions FOR SELECT USING (true)',
        'immutable': 'DROP TRIGGER immutable ON support_actions',
    }[drift]
    with database.engine.begin() as connection:
        connection.execute(text(query))
    assert reader(database).verify()['status'] == 'matched'
    with pytest.raises(ExportError, match='audit_schema_incomplete'):
        capture(database)


def test_initial_revision_reports_preaudit_history_unavailable(empty_database):
    with empty_database.engine.begin() as connection:
        command.upgrade(migration_config(connection), '0001_initial')
    with pytest.raises(ExportError, match='audit_history_unavailable'):
        capture(empty_database)


def test_real_pg_dump_restore_retains_audit_archive(database):
    """Use the same pg_dump -Fc / pg_restore path as #294, with real SQL.

    CI explicitly passes its disposable PostgreSQL service ID. No application
    secret or existing database is selected; fixtures own source and new target.
    """
    container = os.environ.get('TABULA_RASA_TEST_PG_CONTAINER', '')
    if not container:
        pytest.skip('Set TABULA_RASA_TEST_PG_CONTAINER to the disposable PostgreSQL service for the archive drill.')
    assert re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]*', container)
    original = database.engine.url.database
    assert re.fullmatch('tabula_test_[0-9a-f]{32}', original)
    alpha, beta = seed_core(database)
    for services in (alpha, beta):
        made = services.transactions.create(transaction_id='same-id', **expense())
        services.transactions.update('same-id', expected=made, amount='20')
    expected = {scope: capture(database, scope) for scope in ('alpha', 'beta')}
    source_events = {scope: reader(database, scope).query(limit=1000) for scope in expected}
    username = database.engine.url.username
    prefix = ['docker', 'exec', '-i', container]
    dump = subprocess.run([*prefix, 'pg_dump', '-U', username, '-Fc', '-d', original],
                          check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60).stdout
    name = 'tabula_restore_' + uuid4().hex
    admin = create_engine(database.engine.url.set(database='postgres'), isolation_level='AUTOCOMMIT',
                          poolclass=NullPool, hide_parameters=True)
    created = False
    restored = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        subprocess.run([*prefix, 'pg_restore', '-U', username, '--single-transaction', '--exit-on-error', '-d', name],
                       input=dump, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        restored = Database(DatabaseSettings(database.engine.url.set(database=name)))
        from tabula_rasa.infrastructure.postgres.audit_recovery import _inventory
        with database.transaction(read_only=True) as source_connection, restored.transaction(read_only=True) as target_connection:
            source_inventory = _inventory(source_connection, '0015_support_controls')
            target_inventory = _inventory(target_connection, '0015_support_controls')
            for key in source_inventory:
                assert target_inventory[key] == source_inventory[key], key
        for scope in expected:
            assert verify(restored, expected[scope], scope)['status'] == 'matched'
            assert reader(restored, scope).query(limit=1000) == source_events[scope]
    finally:
        if restored is not None:
            restored.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()
