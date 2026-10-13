from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError, VerifiedIdentity, capabilities
from tabula_rasa.infrastructure.postgres.control_plane import PostgresIdentityRepository
from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository, credential_hash
from tabula_rasa.infrastructure.postgres.runtime import DatabaseError
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


def test_login_metadata_does_not_wait_for_unrelated_organization_lock(empty_database):
    database = empty_database
    with database.engine.begin() as connection:
        command.upgrade(migration_config(connection), '0007_identity_sessions')
    repo, alice, bob, a, b = setup(database)
    with database.engine.begin() as holding:
        holding.execute(text('SELECT id FROM organizations WHERE id=:org FOR UPDATE'), {'org': a})
        with pytest.raises(DatabaseError) as caught:
            with database.transaction() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
                repo.resolve_user(verified())
        assert caught.value.code == 'unavailable'
    upgrade(database)
    # A separate administrative transaction owns A's organization lock. Metadata
    # login must still complete; state changes must keep owner serialization.
    with database.engine.connect() as holding:
        transaction = holding.begin()
        try:
            holding.execute(text('SELECT id FROM organizations WHERE id=:org FOR UPDATE'), {'org': a})
            with database.transaction() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
                assert repo.resolve_user(verified()).id == alice.id
                assert repo.resolve_user(verified('bob')).id == bob.id
            with pytest.raises(DatabaseError) as caught:
                with database.transaction() as connection:
                    connection.execute(text("SET LOCAL lock_timeout = '500ms'"))
                    connection.execute(text("UPDATE identity_users SET state='disabled' WHERE id=:user"), {'user': alice.id})
            # DatabaseError's safe code; no driver exception or private SQL.
            assert caught.value.code == 'unavailable'
        finally:
            transaction.rollback()
    assert [item.organization_id for item in repo.allowed_entities(alice.id)] == [a]
    assert [item.organization_id for item in repo.allowed_entities(bob.id)] == [b]


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
    with pytest.raises(IdentityError):
        rotated.configure()  # Runtime startup cannot authorize a rotation.
    assert sessions.validate(fresh).user_id == bob.id
    assert rotated.rotate_configuration(1) == 2
    rotated.configure()
    with pytest.raises(IdentityError):
        sessions.configure()  # An old deployment restart cannot reverse it.
    with pytest.raises(IdentityError):
        sessions.rotate_configuration(1)  # Nor can a stale operator command.
    rotated.configure()
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT epoch FROM identity_environments WHERE environment='test'")) == 2
    with pytest.raises(IdentityError):
        rotated.validate(fresh)
    with pytest.raises(IdentityError):
        sessions.validate(fresh)  # Old worker cannot continue on stale config.


def test_explicit_rotation_preserves_other_environment_and_rejects_stale_operator(database):
    setup(database)
    original = PostgresSessionRepository(database, 'test', 'a' * 64)
    other = PostgresSessionRepository(database, 'staging', 'b' * 64)
    original.configure()
    other.configure()
    old_session, _ = original.issue(verified())
    foreign_session, foreign = other.issue(verified('bob'))
    pending, transaction = original.begin_login('/')
    rotated = PostgresSessionRepository(database, 'test', 'c' * 64)
    assert rotated.rotate_configuration(1) == 2
    new_session, new = rotated.issue(verified())
    for operation in (original.configure, lambda: original.issue(verified()),
                      lambda: rotated.validate(old_session),
                      lambda: rotated.consume_login(pending, transaction.state),
                      lambda: original.rotate_configuration(1),
                      lambda: rotated.rotate_configuration(2)):
        with pytest.raises(IdentityError):
            operation()
    assert rotated.validate(new_session) == new
    assert other.validate(foreign_session) == foreign
    other.configure()
    with database.transaction(read_only=True) as connection:
        assert dict(connection.execute(text('SELECT environment,epoch FROM identity_environments')).all()) == {
            'test': 2, 'staging': 1}


def test_session_retention_preserves_active_users_and_other_environments(database):
    setup(database)
    now = [datetime.now(timezone.utc)]
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64, clock=lambda: now[0])
    other = PostgresSessionRepository(database, 'staging', 'b' * 64, clock=lambda: now[0])
    sessions.configure()
    other.configure()
    expired, _ = sessions.issue(verified(now=now[0]))
    foreign, _ = other.issue(verified(now=now[0]))
    now[0] += timedelta(minutes=30)
    active, _ = sessions.issue(verified('bob', now=now[0]))
    revoked, _ = sessions.issue(verified(now=now[0]))
    replacement, _ = sessions.issue(verified(now=now[0]), previous=revoked)
    absolute, _ = sessions.issue(verified(now=now[0]))
    with database.transaction() as connection:
        connection.execute(text('''UPDATE identity_sessions SET absolute_expires_at=:expiry,
            idle_expires_at=:expiry WHERE credential_hash=:hash'''),
            {'expiry': now[0] + timedelta(seconds=1), 'hash': credential_hash(absolute)})
    now[0] += timedelta(seconds=1)
    sessions.issue(verified(now=now[0]))
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM identity_sessions')) == 4
        assert connection.scalar(text("SELECT count(*) FROM identity_sessions WHERE environment='staging'")) == 1
    assert sessions.validate(active).selected.entity_id == 'beta'
    assert sessions.validate(replacement).selected.entity_id == 'alpha'
    for raw in (expired, revoked, absolute):
        with pytest.raises(IdentityError) as caught:
            sessions.validate(raw)
        assert caught.value.code == 'unauthorized'
    with pytest.raises(IdentityError):
        other.validate(foreign)  # Retained foreign row still cannot authorize.


def test_single_use_browser_bound_login_and_expiry(database):
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    raw, transaction = sessions.begin_login('/')
    with pytest.raises(IdentityError):
        sessions.consume_login('x' * 43, transaction.state)
    assert sessions.consume_login(raw, transaction.state) == transaction
    with pytest.raises(IdentityError):
        sessions.consume_login(raw, transaction.state)


def test_login_retention_prunes_only_finished_attempts_in_its_environment(database):
    now = [datetime.now(timezone.utc)]
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64, clock=lambda: now[0])
    other = PostgresSessionRepository(database, 'staging', 'b' * 64, clock=lambda: now[0])
    sessions.configure()
    other.configure()
    expired, expired_transaction = sessions.begin_login('/')
    foreign, foreign_transaction = other.begin_login('/')
    now[0] += timedelta(minutes=5)
    # The expiry boundary is inclusive; another environment is unaffected.
    active, active_transaction = sessions.begin_login('/')
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM identity_login_transactions')) == 2
    consumed, consumed_transaction = sessions.begin_login('/')
    sessions.consume_login(consumed, consumed_transaction.state)
    sessions.begin_login('/onboarding')  # No previous cookie is required to prune.
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM identity_login_transactions')) == 3
        assert connection.scalar(text("SELECT count(*) FROM identity_login_transactions WHERE environment='staging'")) == 1
    for raw, transaction in ((expired, expired_transaction), (consumed, consumed_transaction)):
        with pytest.raises(IdentityError) as caught:
            sessions.consume_login(raw, transaction.state)
        assert caught.value.code == 'unauthorized'
    assert sessions.consume_login(active, active_transaction.state) == active_transaction
    # The other environment's expired row remained stored, but grants no login.
    with pytest.raises(IdentityError):
        other.consume_login(foreign, foreign_transaction.state)


@pytest.mark.parametrize('loss', ['membership', 'organization', 'entity'])
def test_lost_selection_recovers_only_to_remaining_authorized_workspace(database, loss):
    repo, alice, bob, a, b = setup(database)
    repo.set_membership(b, alice.id, 'read_only')
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    raw, _ = sessions.issue(verified())
    original = sessions.select(raw, 'alpha')
    if loss == 'membership':
        repo.set_membership(a, bob.id, 'owner')
        repo.set_membership(a, alice.id, 'owner', active=False)
    elif loss == 'organization':
        repo.set_organization_state(a, 'suspended')
    else:
        with database.transaction() as connection:
            connection.execute(text("UPDATE organization_entities SET state='inactive' WHERE entity_id='alpha'"))
    recovered = sessions.validate(raw)
    assert recovered.selected.entity_id == 'beta'
    assert recovered.selected.organization_id == b and recovered.selected.role == 'read_only'
    assert recovered.cache_id == original.cache_id
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT entity_id FROM identity_sessions')) == 'beta'
    assert sessions.validate(raw).selected == recovered.selected
    assert {item.entity_id for item in repo.allowed_entities(bob.id)} == (
        {'alpha', 'beta'} if loss == 'membership' else {'beta'})
    repo.set_membership(b, alice.id, 'read_only', active=False)
    assert sessions.validate(raw).selected is None


def test_selection_joins_one_connection_and_rejects_foreign_entity(database):
    from sqlalchemy import event
    setup(database)
    sessions = PostgresSessionRepository(database, 'test', 'a' * 64)
    sessions.configure()
    raw, original = sessions.issue(verified())
    checkouts = []
    def checkout(*args):
        checkouts.append(True)
    event.listen(database.engine, 'checkout', checkout)
    try:
        assert sessions.select(raw, 'alpha').selected == original.selected
        assert len(checkouts) == 1
        checkouts.clear()
        with pytest.raises(IdentityError) as caught:
            sessions.select(raw, 'beta')
        assert caught.value.code == 'forbidden'
        assert len(checkouts) == 1
    finally:
        event.remove(database.engine, 'checkout', checkout)
    assert sessions.validate(raw).selected == original.selected


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
