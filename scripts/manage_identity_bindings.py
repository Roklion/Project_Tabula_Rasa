"""Operator-only existing-entity claims and encrypted Google connection provisioning.

Dry-run is default. Nothing here imports books, activates authority or changes
legacy profile files. Input JSON and approvals stay private.
"""
import argparse
import json
from pathlib import Path

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.connections import PostgresConnections
from tabula_rasa.infrastructure.postgres.legacy_claims import LegacyClaim, PostgresLegacyClaims
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.migration.model import digest


def read_private(path):
    with Path(path).open('rb') as source:
        content = source.read(65537)
    if len(content) > 65536:
        raise IdentityError('forbidden')
    return json.loads(content)


def stage_connection(database, secrets, payload, *, environment, expected_revision, apply=False, expected_plan=None):
    """Preflight exact payload/managed folder before any metadata mutation."""
    from tabula_rasa.http.connections import google_store
    from tabula_rasa.google_drive import DRIVE_SCOPE
    if (not isinstance(environment, str) or environment not in {'test', 'development', 'staging', 'production'}
            or not secrets or payload.get('environment') != environment or payload.get('provider') != 'google_drive'
            or set(payload) != {'environment', 'provider', 'organization_id', 'entity_id', 'profile_key',
                               'scope_key', 'google_drive_oauth', 'google_drive'}):
        raise IdentityError('forbidden')
    row = dict(entity_id=payload['entity_id'], organization_id=payload['organization_id'],
               provider='google_drive', profile_key=payload['profile_key'], store_scope_key=payload['scope_key'],
               required_scopes=[DRIVE_SCOPE])
    repository = PostgresConnections(database)
    plan = digest({'binding': {key: value for key, value in payload.items()
                              if key not in {'google_drive_oauth', 'google_drive'}},
                   'grant_sha256': digest(payload), 'revision': expected_revision})
    if apply and expected_plan != plan:
        raise IdentityError('forbidden')
    repository.stage(organization_id=row['organization_id'], entity_id=row['entity_id'],
        profile_key=row['profile_key'], scope_key=row['store_scope_key'],
        secret_ref='0' * 32, expected_revision=expected_revision, dry_run=True)
    google_store(row, payload, validate=True)
    if apply:
        reference = secrets.put(payload)
        repository.stage(organization_id=row['organization_id'], entity_id=row['entity_id'],
            profile_key=row['profile_key'], scope_key=row['store_scope_key'],
            secret_ref=reference, expected_revision=expected_revision)
    return {'plan_sha256': plan, 'applied': apply, 'status': 'pending' if apply else 'preflight'}


def main(argv=None):
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['claim', 'connection'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-plan')
    parser.add_argument('--approval-sha256')
    parser.add_argument('--environment', choices=['test', 'development', 'staging', 'production'])
    parser.add_argument('--revision', type=int, default=0)
    args = parser.parse_args(argv)
    if args.operation == 'connection' and args.environment is None:
        parser.error('--environment is required for connection operations')
    database = None
    try:
        payload = read_private(args.input)
        database = Database(DatabaseSettings.from_environment(required=True))
        if args.operation == 'claim':
            result = PostgresLegacyClaims(database).claim(LegacyClaim(**payload), apply=args.apply,
                expected_plan=args.expect_plan, approval_sha256=args.approval_sha256)
        else:
            if args.apply and (not args.approval_sha256 or len(args.approval_sha256) != 64
                               or any(c not in '0123456789abcdef' for c in args.approval_sha256)):
                raise IdentityError('forbidden')
            result = stage_connection(database, ConnectionSecrets.from_environment(dict(os.environ)),
                payload, environment=args.environment, expected_revision=args.revision,
                apply=args.apply, expected_plan=args.expect_plan)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        pass
    finally:
        if database is not None:
            database.dispose()
    print(json.dumps({'error': 'binding_refused', 'action': 'Review exact target, ownership, approval and secret configuration.'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
