from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError, VerifiedIdentity, capabilities
from tabula_rasa.infrastructure.postgres.control_plane import PostgresIdentityRepository
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
from alembic import command
from tabula_rasa.infrastructure.postgres.migrations import migration_config, upgrade
from tests.postgres._support import entity


def verified(subject='alice', issuer='https://id.example.test', now=None):
    return VerifiedIdentity(issuer, subject, 'shared@example.test', 'Synthetic', now or datetime.now(timezone.utc))


def setup(database):
    repo = PostgresIdentityRepository(database)
    alice, bob = repo.resolve_user(verified()), repo.resolve_user(verified('bob'))
    a, b = repo.create_organization(alice.id, 'A'), repo.create_organization(bob.id, 'B')
    with database.transaction() as connection:
        entity(connection, 'alpha')
        entity(connection, 'beta')
    repo.bind_entity(a, 'alpha')
    repo.bind_entity(b, 'beta')
    return repo, alice, bob, a, b


def test_forward_upgrade_preserves_canonical_entities_and_does_not_claim_them(empty_database):
    with empty_database.engine.begin() as connection:
        command.upgrade(migration_config(connection), '0005_bookkeeping_cutover')
    with empty_database.transaction() as connection:
        entity(connection)
        original = dict(connection.execute(text('SELECT * FROM business_entities')).mappings().one())
    upgrade(empty_database)
    with empty_database.transaction() as connection:
        assert dict(connection.execute(text('SELECT * FROM business_entities')).mappings().one()) == original
        assert connection.scalar(text('SELECT count(*) FROM organization_entities')) == 0
    repo = PostgresIdentityRepository(empty_database)
    user = repo.resolve_user(verified())
    assert repo.allowed_entities(user.id) == ()


def test_exact_binding_not_email_and_two_organization_isolation(database):
    repo, alice, bob, a, b = setup(database)
    assert repo.resolve_user(verified()).id == alice.id
    assert alice.id != bob.id != repo.resolve_user(verified(issuer='https://other.example.test')).id
    assert [item.entity_id for item in repo.allowed_entities(alice.id)] == ['alpha']
    assert [item.entity_id for item in repo.allowed_entities(bob.id)] == ['beta']
    with pytest.raises(IdentityError):
        repo.bind_entity(b, 'alpha')
    repo.set_membership(a, bob.id, 'read_only')
    assert len(repo.allowed_entities(bob.id)) == 2
    repo.set_membership(a, bob.id, 'read_only', active=False)
    assert [item.entity_id for item in repo.allowed_entities(bob.id)] == ['beta']
    assert 'bookkeeping:write' not in capabilities('read_only')
    assert 'recovery:authorize' not in capabilities('admin')
    assert not capabilities('unknown')


def test_last_active_owner_guards_all_state_paths(database):
    repo, alice, bob, a, _ = setup(database)
    for operation in (lambda: repo.set_membership(a, alice.id, 'admin'),
                      lambda: repo.set_membership(a, alice.id, 'owner', active=False),
                      lambda: repo.set_user_state(alice.id, 'disabled')):
        with pytest.raises(IdentityError) as caught:
            operation()
        assert caught.value.code == 'invariant'
    repo.set_membership(a, bob.id, 'owner')
    repo.set_user_state(alice.id, 'disabled')
    assert not repo.allowed_entities(alice.id)
    repo.set_organization_state(a, 'suspended')
    repo.set_membership(a, bob.id, 'admin')
    with pytest.raises(IdentityError):
        repo.set_organization_state(a, 'active')


def test_durable_session_epochs_expiry_and_subject_revocation(database):
    repo, alice, bob, a, _ = setup(database)
    now = [datetime.now(timezone.utc)]
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64, clock=lambda: now[0])
    sessions.configure()
    raw_a, first = sessions.issue(verified(now=now[0]))
    raw_b, _ = sessions.issue(verified('bob', now=now[0]))
    other_worker = PostgresSessionRepository(database, 'test', 'a' * 64, clock=lambda: now[0])
    assert other_worker.validate(raw_a) == first
    with pytest.raises(IdentityError):
        sessions.select(raw_a, 'beta')
    repo.revoke_user_sessions(alice.id)
    with pytest.raises(IdentityError):
        sessions.validate(raw_a)
    assert sessions.validate(raw_b).user_id == bob.id
    raw_a, _ = sessions.issue(verified(now=now[0]))
    repo.set_membership(a, bob.id, 'owner')
    repo.set_membership(a, alice.id, 'read_only')
    assert sessions.validate(raw_a).selected.role == 'read_only'
    repo.set_membership(a, alice.id, 'read_only', active=False)
    assert sessions.validate(raw_a).selected is None
    now[0] += timedelta(minutes=29)
    sessions.validate(raw_b)  # Polls do not touch idle expiry.
    now[0] += timedelta(minutes=2)
    with pytest.raises(IdentityError):
        sessions.validate(raw_b)
    fresh, _ = sessions.issue(verified('bob', now=now[0]))
    rotated = PostgresSessionRepository(database, 'test', 'b' * 64)
    rotated.configure()
    with pytest.raises(IdentityError):
        rotated.validate(fresh)
    with pytest.raises(IdentityError):
        sessions.validate(fresh)  # Old worker cannot continue on stale config.


def test_single_use_browser_bound_login_and_expiry(database):
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    raw, transaction = sessions.begin_login('/')
    with pytest.raises(IdentityError):
        sessions.consume_login('x' * 43, transaction.state)
    assert sessions.consume_login(raw, transaction.state) == transaction
    with pytest.raises(IdentityError):
        sessions.consume_login(raw, transaction.state)


def test_concurrent_owner_removals_and_callback_consumption(database):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    repo, alice, bob, a, _ = setup(database)
    repo.set_membership(a, bob.id, 'owner')
    barrier = Barrier(2)
    def remove(user):
        barrier.wait(timeout=5)
        try:
            repo.set_membership(a, user, 'admin')
            return 'removed'
        except IdentityError as error:
            return error.code
    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(remove, [alice.id, bob.id]))
    assert results.count('removed') == 1
    assert set(results) <= {'removed', 'invariant', 'concurrent_write'}
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM memberships WHERE organization_id=:org AND role='owner' AND state='active'"), {'org': a}) == 1
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    raw, transaction = sessions.begin_login('/')
    barrier = Barrier(2)
    def consume(_):
        barrier.wait(timeout=5)
        try:
            sessions.consume_login(raw, transaction.state)
            return True
        except IdentityError:
            return False
    with ThreadPoolExecutor(2) as workers:
        assert sum(workers.map(consume, [0, 1])) == 1


def test_foreground_idle_cap_reactivation_and_session_hash_storage(database):
    repo, alice, bob, a, _ = setup(database)
    repo.set_membership(a, bob.id, 'owner')
    now = [datetime.now(timezone.utc)]
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64, clock=lambda: now[0])
    sessions.configure()
    raw, session = sessions.issue(verified(now=now[0]))
    with database.transaction(read_only=True) as connection:
        row = connection.execute(text('SELECT * FROM identity_sessions')).mappings().one()
        assert len(row['credential_hash']) == 64 and raw not in repr(dict(row))
    for _ in range(24):
        now[0] += timedelta(minutes=29)
        sessions.validate(raw, foreground=True)
    now[0] = session.absolute_expires_at
    with pytest.raises(IdentityError):
        sessions.validate(raw, foreground=True)
    raw, _ = sessions.issue(verified(now=now[0]))
    repo.set_user_state(alice.id, 'disabled')
    repo.set_user_state(alice.id, 'active')
    with pytest.raises(IdentityError):
        sessions.validate(raw)
    raw, transaction = sessions.begin_login('/')
    now[0] += timedelta(minutes=6)
    with pytest.raises(IdentityError):
        sessions.consume_login(raw, transaction.state)
