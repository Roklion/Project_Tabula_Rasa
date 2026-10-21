"""Explicit 0014 -> 0015 maintenance; ordinary promotion stays head-only."""
import argparse
import json
import os
import re

from tabula_rasa.deployment import release
from tabula_rasa.deployment.smoke import access_mode
from tabula_rasa.infrastructure.postgres.hosted import open_alpha_database
from tabula_rasa.infrastructure.postgres.migrations import head_revision, upgrade

SOURCE = '0014_document_locations'
TARGET = '0015_support_controls'
SERVICES = {
    'development': ('srv-db45ejjtqb8s73e536a0', 'https://tabula-rasa-development.onrender.com'),
    'staging': ('srv-db45q43bc2fs73aniv1g', 'https://tabula-rasa-staging.onrender.com'),
}


def recovery_checkpoint(environ):
    checkpoint = environ.get('MAINTENANCE_RECOVERY_SHA256', '')
    if not isinstance(checkpoint, str) or not re.fullmatch('[0-9a-f]{64}', checkpoint) or checkpoint == '0' * 64:
        raise ValueError('An operator-verified private recovery checkpoint record is required.')
    return checkpoint


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


def validate_scope(environ):
    environment = environ.get('TABULA_RASA_ENVIRONMENT')
    if environment not in SERVICES:
        raise ValueError('Only reviewed development/staging services are supported.')
    service, origin = SERVICES[environment]
    if (environ.get('GITHUB_REPOSITORY') != 'Roklion/Project_Tabula_Rasa'
            or environ.get('GITHUB_REF') != 'refs/heads/main'
            or environ.get('RENDER_SERVICE_ID') != service
            or environ.get('TABULA_RASA_PUBLIC_ORIGIN') != origin
            or not re.fullmatch('[0-9a-f]{40}', environ.get('GITHUB_SHA', ''))
            or not re.fullmatch('[0-9a-f]{64}', environ.get('TABULA_RASA_DEPLOY_DATABASE_SHA256', ''))):
        raise ValueError('Maintenance scope does not match the reviewed service.')
    mode = access_mode(environ, require_alpha_credentials=False)
    if environment == 'staging' and mode != 'named_user':
        raise ValueError('Staging must retain named-user mode.')
    release.immutable_digest(environ.get('IMAGE', ''),
                             'ghcr.io/roklion/project_tabula_rasa/commercial')
    operation = environ.get('MAINTENANCE_OPERATION')
    if operation not in {'inspect', 'upgrade'}:
        raise ValueError('Select inspect or upgrade explicitly.')
    if operation == 'upgrade':
        if environ.get('MAINTENANCE_APPROVAL') != '0014_to_0015':
            raise ValueError('Explicit transition approval is required.')
        recovery_checkpoint(environ)
    return operation


def preflight(environ, *, metadata=None, verify=None, read=None):
    operation = validate_scope(environ)
    image = environ['IMAGE']
    candidate = (metadata or release.image_metadata)(image, image.split('@')[0])
    if candidate['release'] != environ['GITHUB_SHA'] or candidate['schema'] != TARGET:
        raise ValueError('Use this workflow revision\'s tested schema-0015 image.')
    (verify or release.validated_main)(candidate['release'], environ)
    read = read or release.api
    if operation == 'upgrade':
        suspended_service(environ, read=read)
    else:
        service = read('/services/' + environ['RENDER_SERVICE_ID'], environ['RENDER_API_KEY'])
        if service.get('id') != environ['RENDER_SERVICE_ID']:
            raise ValueError('Unexpected service.')
    return {'status': 'preflight_passed', 'environment': environ['TABULA_RASA_ENVIRONMENT'],
            'release': candidate['release'], 'source_schema': SOURCE, 'target_schema': TARGET,
            'operation': operation}


def execute(environ):
    operation = validate_scope(environ)
    if environ.get('TABULA_RASA_RELEASE_ID') != environ['GITHUB_SHA'] or head_revision() != TARGET:
        raise ValueError('Execute inside the exact verified workflow-revision image.')
    database = open_alpha_database(environ)
    try:
        before = database.health()
        if not before.get('connected') or before.get('revision') not in {SOURCE, TARGET}:
            raise ValueError('Unexpected database schema; inspect the binding privately.')
        if operation == 'inspect':
            return {'status': 'schema_inspected', 'environment': environ['TABULA_RASA_ENVIRONMENT'],
                    'schema': before['revision']}
        if before['revision'] != SOURCE:
            raise ValueError('Source is not 0014; do not retry an already applied upgrade.')
        upgrade(database)
        after = database.health()
        if not after.get('connected') or after.get('revision') != TARGET:
            raise ValueError('Upgrade health unconfirmed; keep the service suspended.')
        return {'status': 'schema_upgraded', 'environment': environ['TABULA_RASA_ENVIRONMENT'],
                'source_schema': SOURCE, 'target_schema': TARGET,
                'checkpoint_sha256': recovery_checkpoint(environ)}
    finally:
        database.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['preflight', 'execute'])
    args = parser.parse_args()
    try:
        result = preflight(dict(os.environ)) if args.command == 'preflight' else execute(dict(os.environ))
    except Exception:
        raise SystemExit('Support-schema maintenance stopped. Inspect binding, checkpoint, pause and schema; do not retry blindly.') from None
    print(json.dumps(result))


if __name__ == '__main__':
    main()
