"""Copy retained encrypted grant files into approved shared custody, without rebinding.

Dry-run by default. Never deletes source files, overwrites grants, rotates keys
or changes application connection metadata. Configure the destination URL/key
through private environment injection, never command arguments.
"""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from sqlalchemy import text

from tabula_rasa.application.identity import IdentityError
from tabula_rasa.infrastructure.connection_secrets import ConnectionSecrets
from tabula_rasa.infrastructure.postgres.connection_secrets import PostgresConnectionSecrets
from tabula_rasa.infrastructure.postgres.identity import database_identity
from tabula_rasa.migration.model import digest


def copy_grants(source, destination, environment, *, apply=False, expected_plan=None):
    retained = {}
    for path in sorted(source.directory.glob('*.grant')):
        reference = path.stem
        if not re.fullmatch('[0-9a-f]{32}', reference):
            raise IdentityError('unavailable')
        ciphertext = source._read_ciphertext(reference)
        if len(ciphertext) > 131072:
            raise IdentityError('unavailable')
        payload = json.loads(source._cipher.decrypt(ciphertext))
        if (payload.get('environment') != environment
                or any(not isinstance(payload.get(field), str) or not payload[field]
                       for field in ('organization_id', 'entity_id', 'provider'))):
            raise IdentityError('unavailable')
        # Validate with the destination key before any write; never re-encrypt.
        if destination._cipher.decrypt(ciphertext) != source._cipher.decrypt(ciphertext):
            raise IdentityError('unavailable')
        retained[reference] = ciphertext
    if not retained:
        raise IdentityError('unavailable')
    plan = digest({'source': str(source.directory.resolve()), 'environment': environment,
                   'destination': database_identity(destination),
                   'ciphertext': {ref: sha256(value).hexdigest() for ref, value in retained.items()}})
    if apply and expected_plan != plan:
        raise IdentityError('forbidden')
    copied = 0
    with destination.engine.begin() as connection:
        for reference, ciphertext in retained.items():
            if apply:
                connection.execute(text('INSERT INTO connection_custody.grants (reference,ciphertext) '
                    'VALUES (:reference,:ciphertext) ON CONFLICT (reference) DO NOTHING'),
                    {'reference': reference, 'ciphertext': ciphertext})
            existing = connection.scalar(text('SELECT ciphertext FROM connection_custody.grants '
                'WHERE reference=:reference'), {'reference': reference})
            if existing is not None:
                if bytes(existing) != ciphertext:
                    raise IdentityError('conflict')
                copied += 1
    return {'plan_sha256': plan, 'source_count': len(retained),
            'matching_destination_count': copied, 'applied': apply}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--environment', choices=['test', 'development', 'staging', 'production'], required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expect-plan')
    args = parser.parse_args(argv)
    try:
        key = os.environ.get('TABULA_RASA_CONNECTION_SECRETS_KEY', '')
        source = ConnectionSecrets(args.source, key)
        destination = PostgresConnectionSecrets(
            os.environ.get('TABULA_RASA_CONNECTION_SECRETS_DATABASE_URL', ''), key)
        result = copy_grants(source, destination, args.environment,
                             apply=args.apply, expected_plan=args.expect_plan)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        pass
    print(json.dumps({'error': 'custody_copy_refused',
                      'action': 'Review approved target, source, key, environment and exact plan.'}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
