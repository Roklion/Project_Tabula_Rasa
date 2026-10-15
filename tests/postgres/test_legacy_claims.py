from dataclasses import replace

import pytest
from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.postgres.control_plane import PostgresIdentityRepository
from tabula_rasa.infrastructure.postgres.legacy_claims import LegacyClaim, PostgresLegacyClaims
from tabula_rasa.infrastructure.postgres.identity import database_identity
from tabula_rasa.infrastructure.postgres.composition import create_postgres_export_service
from tabula_rasa.infrastructure.postgres.cutover import PostgresCutoverController
from tests.postgres.test_cutover import loaded, REHEARSAL_EVIDENCE, status
from tests.postgres.test_identity import verified

APPROVAL = 'a' * 64


def claim_for(database, profile, org, user, *, entity_id=None):
    entity_id = entity_id or profile
    cutover = status(database, entity_id)
    with database.transaction(read_only=True) as connection:
        binding = connection.scalar(text('SELECT id FROM identity_bindings WHERE user_id=:user'), {'user': user.id})
    return LegacyClaim(entity_id, profile, 'workbook-' + profile, org, user.id, binding,
        database_identity(database), cutover['run_id'], cutover['acceptance_sha256'], 'folder-' + profile)


def apply_claim(database, claim):
    repo = PostgresLegacyClaims(database)
    preview = repo.claim(claim)
    return repo.claim(claim, apply=True, expected_plan=preview['plan_sha256'], approval_sha256=APPROVAL)


def test_existing_two_profile_claim_preserves_every_ledger_id_acceptance_and_restart_access(database):
    from tests.postgres.test_identity_http import client_for
    identity = PostgresIdentityRepository(database)
    claims = []
    controller = PostgresCutoverController(database)
    originals = {}
    for profile in ('alpha', 'beta'):
        entity_id = 'retained-alpha-id' if profile == 'alpha' else profile
        if entity_id != profile:
            from tabula_rasa.infrastructure.sheets_migration import snapshot_from_values
            from tabula_rasa.migration.documents import enrich_snapshot
            from tabula_rasa.migration.model import Binding
            from tabula_rasa.migration.planning import build_plan
            from tabula_rasa.infrastructure.postgres.migration import PostgresMigrationRunner
            from tests.migration_support import complete_plan
            _, values, documents = complete_plan(profile)
            snapshot = snapshot_from_values(Binding(profile, 'workbook-' + profile, entity_id), values)
            plan = build_plan(enrich_snapshot(snapshot, entity_name='Synthetic ' + profile,
                document_scope='folder-' + profile, documents=documents, inventory_complete=True))
            PostgresMigrationRunner(database, secondary=True).execute(plan, dry_run=False)
        else:
            plan = loaded(database, profile)
        controller.prepare(plan, mode='rehearsal', evidence=REHEARSAL_EVIDENCE)
        controller.activate(plan.snapshot.binding)
        user = identity.resolve_user(verified(profile))
        org = identity.create_organization(user.id, profile)
        claim = claim_for(database, profile, org, user, entity_id=entity_id)
        claims.append(claim)
        originals[profile] = (create_postgres_export_service(database, entity_id).export(), status(database, entity_id))
        assert identity.allowed_entities(user.id) == ()
        preview = PostgresLegacyClaims(database).claim(claim)
        assert not preview['applied'] and identity.allowed_entities(user.id) == ()
        assert apply_claim(database, claim)['applied']
        assert apply_claim(database, claim)['already_claimed']
        assert [item.entity_id for item in identity.allowed_entities(user.id)] == [entity_id]
        assert create_postgres_export_service(database, entity_id).export()['domains'] == originals[profile][0]['domains']
        assert status(database, entity_id) == originals[profile][1]
    for _restart in range(2):
        client, auth, factory = client_for(database)
        with client:
            for claim in claims:
                raw, _ = auth.sessions.issue(verified(claim.profile_key))
                client.cookies.set(auth.session_cookie, raw)
                assert client.get('/api/v1/session').json()['entity']['id'] == claim.entity_id
                assert client.get('/api/v1/entities').json()['items'] == [
                    {'id': claim.entity_id, 'name': 'Synthetic ' + claim.profile_key}]
                foreign = next(item.entity_id for item in claims if item.entity_id != claim.entity_id)
                assert client.get('/api/v1/entities/' + foreign + '/accounts').status_code == 403
                assert client.get('/api/v1/entities/' + foreign + '/documents/known/content').status_code == 403
            factory.assert_not_called()
    assert status(database, claims[0].entity_id) == originals['alpha'][1]


def test_preflight_and_apply_refuse_exact_target_identity_owner_and_evidence_mismatch(database):
    identity = PostgresIdentityRepository(database)
    plan = loaded(database)
    controller = PostgresCutoverController(database)
    controller.prepare(plan, mode='rehearsal', evidence=REHEARSAL_EVIDENCE)
    user, other = identity.resolve_user(verified()), identity.resolve_user(verified('other'))
    org, foreign = identity.create_organization(user.id, 'A'), identity.create_organization(other.id, 'B')
    claim = claim_for(database, 'alpha', org, user)
    repo = PostgresLegacyClaims(database)
    for field, value in {'profile_key': 'beta', 'workbook_key': 'workbook-beta', 'entity_id': 'beta',
                         'database_sha256': '0' * 64, 'owner_id': other.id, 'identity_binding_id': 'foreign',
                         'organization_id': foreign, 'run_id': 'unknown', 'acceptance_sha256': '0' * 64,
                         'document_scope': 'folder-beta'}.items():
        with pytest.raises(IdentityError):
            repo.claim(replace(claim, **{field: value}))
    for expected, approval in [(None, APPROVAL), ('0' * 64, APPROVAL), (repo.claim(claim)['plan_sha256'], None)]:
        with pytest.raises(IdentityError):
            repo.claim(claim, apply=True, expected_plan=expected, approval_sha256=approval)
    assert identity.allowed_entities(user.id) == ()
    # A different already-owned org fails closed, even when both users are known.
    identity.bind_entity(foreign, 'alpha')
    with pytest.raises(IdentityError):
        apply_claim(database, claim)
    assert status(database)['state'] == 'prepared'


def test_claim_application_rolls_back_as_one_control_plane_transaction(database):
    identity = PostgresIdentityRepository(database)
    plan = loaded(database)
    PostgresCutoverController(database).prepare(plan, mode='rehearsal', evidence=REHEARSAL_EVIDENCE)
    user = identity.resolve_user(verified())
    org = identity.create_organization(user.id, 'A')
    claim = claim_for(database, 'alpha', org, user)
    with pytest.raises(RuntimeError):
        with database.transaction():
            apply_claim(database, claim)
            raise RuntimeError('uncommitted operator transaction')
    assert identity.allowed_entities(user.id) == ()
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text('SELECT count(*) FROM legacy_entity_claims')) == 0
    assert status(database)['state'] == 'prepared'
