"""Least-privilege HTTP support client. No SQL or secret-store credentials needed.

Use a named operator session. Reads are bounded and audited. Administrative
commands preview by default; --confirm-plan explicitly applies the exact plan.
"""
import argparse
from getpass import getpass
import json
from urllib.parse import quote, urlsplit

import requests


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['diagnostics', 'audit', 'revoke_sessions', 'suspend_member', 'suspend_organization'])
    parser.add_argument('--origin', required=True)
    parser.add_argument('--organization', required=True)
    parser.add_argument('--entity', required=True)
    parser.add_argument('--reason', required=True, choices=[
        'incident', 'access_request', 'job_failure', 'migration_failure', 'connection_failure', 'audit_review'])
    parser.add_argument('--target-user')
    parser.add_argument('--confirm-plan')
    parser.add_argument('--since')
    parser.add_argument('--until')
    for field in ('actor-id', 'action', 'source', 'target-type', 'target-id', 'batch-id', 'operation-id'):
        parser.add_argument('--' + field)
    parser.add_argument('--after-sequence', type=int, default=0)
    parser.add_argument('--through-sequence', type=int)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args(argv)
    origin = urlsplit(args.origin)
    if (origin.scheme not in {'https', 'http'} or not origin.hostname
            or origin.scheme == 'http' and origin.hostname not in {'127.0.0.1', 'localhost'}
            or origin.username or origin.password or origin.query or origin.fragment
            or origin.path not in {'', '/'} or not 1 <= args.limit <= 100):
        parser.error('Use an HTTPS application origin (or loopback development) and a limit of 1-100.')
    base = args.origin.rstrip('/')
    try:
        credential = getpass('Named operator session credential (hidden): ')
        csrf = getpass('Session CSRF credential (hidden): ')
        cookie = '__Host-tabula_session' if origin.scheme == 'https' else 'tabula_dev_session'
        payload = {'reason': args.reason}
        endpoint = args.operation
        if args.operation == 'audit':
            payload.update({key: getattr(args, key) for key in (
                'since', 'until', 'actor_id', 'action', 'source', 'target_type', 'target_id',
                'batch_id', 'operation_id', 'after_sequence', 'through_sequence', 'limit') if getattr(args, key) is not None})
        elif args.operation != 'diagnostics':
            endpoint = 'administration'
            payload.update(operation=args.operation, target_user_id=args.target_user, confirm_plan=args.confirm_plan)
        with requests.Session() as client:
            client.trust_env = False
            response = client.post(base + '/api/v1/support/' + quote(args.organization, safe='') + '/'
                + quote(args.entity, safe='') + '/' + endpoint, json=payload,
                cookies={cookie: credential}, headers={'origin': base, 'x-csrf-token': csrf},
                timeout=(5, 30), allow_redirects=False, stream=True)
            # Never print a reverse proxy/provider error body or redirect.
            if response.status_code != 200:
                raise ValueError('Support request refused.')
            content = response.raw.read(1048577, decode_content=True)
            if len(content) > 1048576:
                raise ValueError('Support response exceeds budget.')
            result = json.loads(content)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({'error': 'support_refused', 'action': 'Check session, scope, approval and service health; inspect before retrying.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
