"""Real shared ciphertext persistence; no hosted accounts or provider grants."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.postgres.connection_secrets import PostgresConnectionSecrets


@pytest.fixture
def custody(empty_database):
    name = 'tabula_test_custody_' + uuid4().hex
    admin = create_engine(empty_database.engine.url, isolation_level='AUTOCOMMIT', poolclass=NullPool)
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE {name}')
    engine = create_engine(empty_database.engine.url.set(database=name), poolclass=NullPool,
                           hide_parameters=True, echo=False)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql((Path(__file__).resolve().parents[2] /
                                       'deploy/commercial/connection-custody.sql').read_text())
        key = Fernet.generate_key().decode()
        yield engine, key, engine.url.render_as_string(hide_password=False)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE {name}')
        admin.dispose()


def scope(name):
    return dict(environment='staging', organization_id='org-' + name,
                entity_id='entity-' + name, provider='google_drive')


def test_shared_store_survives_recreation_and_isolates_businesses(custody):
    engine, key, url = custody
    first = ConnectionSecrets.from_environment({
        'TABULA_RASA_CONNECTION_SECRETS_DATABASE_URL': url,
        'TABULA_RASA_CONNECTION_SECRETS_KEY': key})
    second = PostgresConnectionSecrets(url, key)
    payloads = [dict(scope(name), refresh_token='synthetic-secret-' + name) for name in ('a', 'b')]
    # Independent worker objects can commit concurrently without replacing grants.
    with ThreadPoolExecutor(max_workers=2) as executor:
        references = list(executor.map(lambda pair: pair[0].put(pair[1]),
                                      zip((first, second), payloads)))
    first.engine.dispose()
    second.engine.dispose()
    restarted = PostgresConnectionSecrets(url, key)
    for reference, payload in zip(references, payloads):
        assert restarted.get(reference, **scope(payload['entity_id'][-1])) == payload
        for field in scope('a'):
            with pytest.raises(IdentityError) as error:
                restarted.get(reference, **{**scope(payload['entity_id'][-1]), field: 'foreign'})
            assert error.value.__context__ is None
    with engine.connect() as connection:
        rows = connection.execute(text('SELECT ciphertext FROM connection_custody.grants')).scalars().all()
        assert all(b'synthetic-secret' not in bytes(row) for row in rows)
    with pytest.raises(IdentityError):
        PostgresConnectionSecrets(url, Fernet.generate_key().decode()).get(references[0], **scope('a'))
    # A PKCE envelope uses precisely the same custody and scope contract.
    verifier_scope = {**scope('a'), 'provider': 'google_drive_oauth_state'}
    verifier = restarted.put(dict(verifier_scope, verifier='synthetic-pkce'))
    assert restarted.get(verifier, **verifier_scope)['verifier'] == 'synthetic-pkce'
    with pytest.raises(IdentityError):
        restarted.get(verifier, **scope('a'))


def test_duplicate_tampered_missing_and_unavailable_are_safe(custody, monkeypatch):
    engine, key, url = custody
    store = PostgresConnectionSecrets(url, key)
    reference = store.put(dict(scope('a'), refresh_token='synthetic-never-echo'))
    monkeypatch.setattr('tabula_rasa.infrastructure.connection_secrets.uuid4',
                        lambda: SimpleNamespace(hex=reference))
    with pytest.raises(IdentityError) as error:
        store.put(dict(scope('b'), refresh_token='replacement'))
    assert error.value.__context__ is None
    assert store.get(reference, **scope('a'))['refresh_token'] == 'synthetic-never-echo'
    for value in ('../path', 'x' * 32, uuid4().hex):
        with pytest.raises(IdentityError) as error:
            store.get(value, **scope('a'))
        assert error.value.__context__ is None
    with engine.begin() as connection:
        connection.execute(text('UPDATE connection_custody.grants SET ciphertext=:ciphertext'),
                           {'ciphertext': b'tampered'})
    with pytest.raises(IdentityError):
        store.get(reference, **scope('a'))
    monkeypatch.setattr(store.engine, 'connect', Mock(side_effect=ValueError('synthetic-never-echo')))
    with pytest.raises(IdentityError) as error:
        store.get(reference, **scope('a'))
    assert error.value.__context__ is None
    assert 'synthetic-never-echo' not in str(error.value)


def test_unprovisioned_store_never_creates_tables(empty_database):
    store = PostgresConnectionSecrets(empty_database.engine.url.render_as_string(hide_password=False),
                                      Fernet.generate_key().decode())
    with pytest.raises(IdentityError):
        store.put(scope('a'))
    with empty_database.engine.connect() as connection:
        assert connection.scalar(text("SELECT to_regclass('connection_custody.grants')")) is None


def test_runtime_role_needs_only_select_insert(custody):
    engine, key, url = custody
    role = 'custody_test_' + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE ROLE {role} LOGIN')
        connection.exec_driver_sql(f'GRANT USAGE ON SCHEMA connection_custody TO {role}')
        connection.exec_driver_sql(f'GRANT SELECT, INSERT ON connection_custody.grants TO {role}')
    store = PostgresConnectionSecrets(engine.url.set(username=role).render_as_string(hide_password=False), key)
    try:
        reference = store.put(scope('a'))
        assert store.get(reference, **scope('a')) == scope('a')
        for sql in ('DELETE FROM connection_custody.grants',
                    "UPDATE connection_custody.grants SET ciphertext='x'::bytea",
                    'CREATE TABLE connection_custody.unauthorized (id int)'):
            with pytest.raises(Exception):
                with store.engine.begin() as connection:
                    connection.exec_driver_sql(sql)
    finally:
        store.engine.dispose()
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP OWNED BY {role}')
            connection.exec_driver_sql(f'DROP ROLE {role}')


def test_customer_consent_can_finish_after_worker_recreation(database, tmp_path, custody):
    from tests.postgres.test_customer_drive_oauth import begin, finish, fixture
    engine, key, url = custody
    repo, manager, client, exchange, alpha, beta, sessions = fixture(database, tmp_path)
    manager.secrets = PostgresConnectionSecrets(url, key)
    for ctx, session in zip((alpha, beta), sessions):
        state = begin(manager, ctx, session)
        manager.secrets.engine.dispose()
        manager.secrets = PostgresConnectionSecrets(url, key)
        assert finish(manager, ctx, session, state, ctx.entity_id)
    references = [manager.repository.grant(ctx)['secret_ref'] for ctx in (alpha, beta)]
    manager.secrets = PostgresConnectionSecrets(url, key)
    for ctx, reference in zip((alpha, beta), references):
        assert manager.secrets.get(reference, environment='test', organization_id=ctx.organization_id,
                                   entity_id=ctx.entity_id, provider='google_drive')['google_drive_oauth']
        assert manager.oauth.status(ctx)['authorization_status'] is None
    with pytest.raises(IdentityError):
        manager.secrets.get(references[0], environment='test', organization_id=beta.organization_id,
                            entity_id=beta.entity_id, provider='google_drive')


def test_copy_is_approved_exact_ciphertext_idempotent_and_never_rebinds(custody, tmp_path):
    from scripts.copy_connection_custody import copy_grants
    engine, key, url = custody
    source = ConnectionSecrets(tmp_path, key)
    destination = PostgresConnectionSecrets(url, key)
    references = [source.put(dict(scope(name), refresh_token='synthetic-' + name)) for name in ('a', 'b')]
    original = {ref: (tmp_path / (ref + '.grant')).read_bytes() for ref in references}
    preview = copy_grants(source, destination, 'staging')
    assert preview['matching_destination_count'] == 0 and not preview['applied']
    with pytest.raises(IdentityError):
        copy_grants(source, destination, 'staging', apply=True, expected_plan='wrong')
    result = copy_grants(source, destination, 'staging', apply=True, expected_plan=preview['plan_sha256'])
    assert result['matching_destination_count'] == 2
    assert copy_grants(source, destination, 'staging', apply=True,
                       expected_plan=preview['plan_sha256']) == result
    for name, ref in zip(('a', 'b'), references):
        assert destination.get(ref, **scope(name))['refresh_token'] == 'synthetic-' + name
        assert destination._read_ciphertext(ref) == original[ref]
        assert (tmp_path / (ref + '.grant')).read_bytes() == original[ref]
    with pytest.raises(IdentityError):
        copy_grants(source, destination, 'production')
    with engine.begin() as connection:
        connection.execute(text('UPDATE connection_custody.grants SET ciphertext=:ciphertext '
                                'WHERE reference=:reference'),
                           {'reference': references[1], 'ciphertext': b'conflicting'})
    with pytest.raises(IdentityError):
        copy_grants(source, destination, 'staging', apply=True, expected_plan=preview['plan_sha256'])
    assert destination._read_ciphertext(references[1]) == b'conflicting'


def test_copy_cli_never_echoes_private_failures(tmp_path, monkeypatch, capsys):
    from scripts.copy_connection_custody import main
    monkeypatch.setenv('TABULA_RASA_CONNECTION_SECRETS_KEY', 'synthetic-never-echo')
    monkeypatch.setenv('TABULA_RASA_CONNECTION_SECRETS_DATABASE_URL', 'synthetic-never-echo')
    assert main(['--source', str(tmp_path), '--environment', 'test']) == 1
    assert 'synthetic-never-echo' not in capsys.readouterr().out
