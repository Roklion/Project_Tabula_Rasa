"""Verify retained connection references against separately recovered custody.

Run only with explicitly approved private database/key injection. This command
does not contact providers or change either database.
"""
import argparse
import json
import os

from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.connection_secrets import PostgresConnectionSecrets
from tabula_rasa.infrastructure.postgres.identity import database_identity
from tabula_rasa.infrastructure.postgres.runtime import Database
from tabula_rasa.migration.model import digest


def verify_references(database, custody):
    with database.transaction(read_only=True) as connection:
        rows = connection.execute(text("""
            SELECT entity_id, organization_id, provider, secret_ref, profile_key,
                   store_scope_key, revision, false AS oauth_request
            FROM external_connections
            UNION ALL
            SELECT entity_id, organization_id, 'google_drive', secret_ref, NULL,
                   NULL, expected_revision, true
            FROM drive_oauth_requests
            ORDER BY oauth_request, entity_id, provider
        """)).mappings().all()

    for row in rows:
        payload = custody.get(row['secret_ref'], environment='staging', entity_id=row['entity_id'],
                              organization_id=row['organization_id'], provider=row['provider'])
        if row['oauth_request']:
            if not isinstance(payload.get('verifier'), str) or not payload['verifier']:
                raise IdentityError('unavailable')
        elif payload.get('profile_key') != row['profile_key'] or payload.get('scope_key') != row['store_scope_key']:
            raise IdentityError('unavailable')
    return {'verified': len(rows), 'references_sha256': digest([dict(row) for row in rows])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger-sha256', required=True)
    parser.add_argument('--custody-sha256', required=True)
    args = parser.parse_args(argv)
    database = None
    try:
        database = Database(DatabaseSettings.from_environment(required=True))
        custody = PostgresConnectionSecrets(os.environ['TABULA_RASA_CONNECTION_SECRETS_DATABASE_URL'],
                                            os.environ['TABULA_RASA_CONNECTION_SECRETS_KEY'])
        if (args.ledger_sha256 == args.custody_sha256
                or database_identity(database) != args.ledger_sha256
                or database_identity(custody) != args.custody_sha256):
            raise IdentityError('unavailable')
        print(json.dumps(verify_references(database, custody), sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'status': 'failed', 'code': 'custody_reference_verification_failed'}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
