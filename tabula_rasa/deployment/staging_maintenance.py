"""Explicit staging schema bridge; ordinary promotion remains head-only."""
import argparse
import json
import os
import re

from tabula_rasa.deployment import release
from tabula_rasa.infrastructure.postgres.hosted import open_alpha_database
from tabula_rasa.infrastructure.postgres.migrations import head_revision, upgrade

IMAGE = ('ghcr.io/roklion/project_tabula_rasa/commercial@'
         'sha256:4bb275f4dc8475bc08ee45d32b3648d4fc33f03c823e3cf3a0c001a9a9bf0c3d')
RELEASE = 'ea8c2de39a171a4010c821edc8648dbf241cd3dd'
SOURCE = '0012_operations'
TARGET = '0014_document_locations'
SCOPE = {
    'GITHUB_REPOSITORY': 'Roklion/Project_Tabula_Rasa',
    'TABULA_RASA_ENVIRONMENT': 'staging',
    'TABULA_RASA_ACCESS_MODE': 'named_user',
    'TABULA_RASA_PUBLIC_ORIGIN': 'https://tabula-rasa-staging.onrender.com',
    'TABULA_RASA_DEPLOY_DATABASE_SHA256': '9451a03e02784a45a587b9606ce0f040e84f6cb1edc297836813c1aa1e4752d1',
    'RENDER_SERVICE_ID': 'srv-db45q43bc2fs73aniv1g',
    'MAINTENANCE_APPROVAL': '0012_to_0014',
    'IMAGE': IMAGE,
}


def recovery_checkpoint(environ):
    checkpoint = environ.get('MAINTENANCE_RECOVERY_SHA256', '')
    if not isinstance(checkpoint, str) or not re.fullmatch('[0-9a-f]{64}', checkpoint) or checkpoint == '0' * 64:
        raise ValueError('An operator-verified private recovery checkpoint record is required.')
    return checkpoint


def validate_scope(environ):
    if any(environ.get(key) != expected for key, expected in SCOPE.items()):
        raise ValueError('Maintenance scope does not match the reviewed staging bridge.')
    return recovery_checkpoint(environ)


def suspended_service(environ, *, read=None):
    read = read or release.api
    service = environ['RENDER_SERVICE_ID']
    token = environ['RENDER_API_KEY']
    state = read('/services/' + service, token)
    if state.get('id') != service or state.get('suspended') != 'suspended':
        raise ValueError('The exact service must remain suspended during maintenance.')
    deployments = read('/services/' + service + '/deploys?limit=100', token)
    pending = {'created', 'queued', 'build_in_progress', 'update_in_progress', 'pre_deploy_in_progress'}
    if any(item['deploy']['status'] in pending for item in deployments):
        raise ValueError('A deployment is in progress; inspect before maintenance.')


def preflight(environ, *, metadata=None, verify=None, read=None):
    checkpoint = validate_scope(environ)
    candidate = (metadata or release.image_metadata)(IMAGE, IMAGE.split('@')[0])
    if candidate['release'] != RELEASE or candidate['schema'] != TARGET:
        raise ValueError('Candidate does not match the reviewed release and schema.')
    (verify or release.validated_main)(RELEASE, environ)
    suspended_service(environ, read=read)
    return {'status': 'preflight_passed', 'image': IMAGE, 'release': RELEASE,
            'source_schema': SOURCE, 'target_schema': TARGET, 'checkpoint_sha256': checkpoint}


def migrate(environ):
    checkpoint = validate_scope(environ)
    # This command is mounted into the approved immutable candidate, not run in
    # the GitHub runner's source environment. The image owns the migration chain.
    if environ.get('TABULA_RASA_RELEASE_ID') != RELEASE or head_revision() != TARGET:
        raise ValueError('Migration must run inside the reviewed candidate image.')
    database = open_alpha_database(environ)
    try:
        before = database.health()
        if not before.get('connected') or before.get('revision') != SOURCE:
            raise ValueError('Expected source schema differs; inspect instead of retrying.')
        upgrade(database)
        after = database.health()
        if not after.get('connected') or after.get('revision') != TARGET:
            raise ValueError('Target schema health is not confirmed; keep staging suspended.')
    finally:
        database.dispose()
    return {'status': 'schema_upgraded', 'release': RELEASE, 'source_schema': SOURCE,
            'target_schema': TARGET, 'checkpoint_sha256': checkpoint}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight', 'upgrade'])
    args = parser.parse_args()
    try:
        result = preflight(dict(os.environ)) if args.command == 'preflight' else migrate(dict(os.environ))
    except Exception:
        raise SystemExit('Staging maintenance stopped. Inspect checkpoint, pause, binding and schema; do not retry blindly.') from None
    print(json.dumps(result))


if __name__ == '__main__':
    main()
