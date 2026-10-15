"""Operator-only preflight/apply of approved existing entity ownership.

No ledger import, authority activation, identity creation or implicit owner grant.
"""
from dataclasses import asdict, dataclass
import re

from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.migration.model import digest
from .control_plane import identity_operation
from .identity import database_identity


@dataclass(frozen=True)
class LegacyClaim:
    entity_id: str
    profile_key: str
    workbook_key: str
    organization_id: str
    owner_id: str
    identity_binding_id: str
    database_sha256: str
    run_id: str
    acceptance_sha256: str
    document_scope: str


class PostgresLegacyClaims:
    def __init__(self, database):
        self.database = database

    def claim(self, claim, *, apply=False, expected_plan=None, approval_sha256=None):
        if (not isinstance(claim, LegacyClaim)
                or any(not isinstance(value, str) or (key != 'document_scope' and not value.strip())
                       for key, value in asdict(claim).items())
                or claim.database_sha256 != database_identity(self.database)):
            raise IdentityError('forbidden')
        plan_sha = digest(asdict(claim))
        if apply and (expected_plan != plan_sha or not isinstance(approval_sha256, str)
                      or not re.fullmatch('[0-9a-f]{64}', approval_sha256)):
            raise IdentityError('forbidden')
        with identity_operation(self.database, read_only=not apply) as connection:
            if apply:
                # Same entity lock as the accepted cutover; serializes claims/ledger boundary.
                connection.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:id,258))'),
                                   {'id': claim.entity_id})
            owner = connection.scalar(text("""SELECT b.id FROM identity_bindings b
                JOIN identity_users u ON u.id=b.user_id AND u.state='active'
                JOIN memberships m ON m.user_id=u.id AND m.state='active' AND m.role='owner'
                JOIN organizations o ON o.id=m.organization_id AND o.state='active'
                WHERE b.id=:binding AND u.id=:owner AND o.id=:org"""),
                {'binding': claim.identity_binding_id, 'owner': claim.owner_id, 'org': claim.organization_id})
            cutover = connection.execute(text("""SELECT * FROM bookkeeping_cutovers
                WHERE entity_id=:id""" + (' FOR UPDATE' if apply else '')),
                {'id': claim.entity_id}).mappings().first()
            if (owner is None or cutover is None or cutover['state'] not in {'prepared', 'postgres'}
                    or cutover['source_profile_key'] != claim.profile_key
                    or cutover['source_workbook_key'] != claim.workbook_key
                    or cutover['run_id'] != claim.run_id or cutover['acceptance_sha256'] != claim.acceptance_sha256
                    or cutover['evidence'].get('document_scope_sha256') != digest(claim.document_scope)):
                raise IdentityError('forbidden')
            binding = connection.execute(text('SELECT * FROM organization_entities WHERE entity_id=:id'),
                                         {'id': claim.entity_id}).mappings().first()
            existing = connection.execute(text('SELECT * FROM legacy_entity_claims WHERE entity_id=:id'),
                                          {'id': claim.entity_id}).mappings().first()
            if binding and (binding['organization_id'] != claim.organization_id or binding['state'] != 'active'):
                raise IdentityError('forbidden')
            if existing and (existing['binding_sha256'] != plan_sha or existing['owner_id'] != claim.owner_id
                             or apply and existing['approval_sha256'] != approval_sha256):
                raise IdentityError('forbidden')
            duplicate = connection.scalar(text('SELECT entity_id FROM legacy_entity_claims WHERE profile_key=:profile AND entity_id<>:id'),
                {'profile': claim.profile_key, 'id': claim.entity_id})
            if duplicate:
                raise IdentityError('forbidden')
            if apply and existing is None:
                if binding is None:
                    connection.execute(text('INSERT INTO organization_entities(entity_id,organization_id) VALUES (:id,:org)'),
                                       {'id': claim.entity_id, 'org': claim.organization_id})
                connection.execute(text("""INSERT INTO legacy_entity_claims
                    (entity_id,organization_id,profile_key,owner_id,identity_binding_id,approval_sha256,binding_sha256)
                    VALUES (:id,:org,:profile,:owner,:binding,:approval,:plan)"""),
                    {'id': claim.entity_id, 'org': claim.organization_id, 'profile': claim.profile_key,
                     'owner': claim.owner_id, 'binding': claim.identity_binding_id,
                     'approval': approval_sha256, 'plan': plan_sha})
            return {'plan_sha256': plan_sha, 'applied': apply, 'already_claimed': existing is not None}
