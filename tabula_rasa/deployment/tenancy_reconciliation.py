"""Explicit private-plan maintenance; no deployment or automatic schema upgrade."""

import argparse
import json
import os
from pathlib import Path

from tabula_rasa.infrastructure.postgres.hosted import open_alpha_database
from tabula_rasa.infrastructure.postgres.tenancy_reconciliation import (
    apply, prepare, readback, write_plan,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'apply', 'readback'])
    parser.add_argument('--plan', type=Path, required=True, help='Absolute operator-private provenance path; never commit/upload it.')
    parser.add_argument('--source-org')
    parser.add_argument('--retained-entity')
    parser.add_argument('--moved-entity')
    parser.add_argument('--owner')
    parser.add_argument('--destination-org', help='Allocate once before prepare; keep it on uncertain commit.')
    parser.add_argument('--recovery-sha256', help='Fingerprint of the independently verified private DB/document recovery record.')
    parser.add_argument('--approval-sha256', help='Exact operator-approved plan fingerprint.')
    parser.add_argument('--writers-drained', action='store_true',
                        help='Operator attests exact staging service suspended and all writers paused for the approved window.')
    args = parser.parse_args()
    database = None
    try:
        environment = dict(os.environ)
        if environment.get('TABULA_RASA_ENVIRONMENT') != 'staging' or not args.plan.is_absolute() or args.plan.is_symlink():
            raise ValueError()
        database = open_alpha_database(environment)
        if args.operation == 'prepare':
            plan = prepare(database, source_org=args.source_org, retained_entity=args.retained_entity,
                           moved_entity=args.moved_entity, owner=args.owner, destination_org=args.destination_org,
                           recovery_sha256=args.recovery_sha256)
            result = {'status': 'plan_prepared', 'plan_sha256': write_plan(args.plan, plan)}
        else:
            if args.plan.stat().st_size > 1024 * 1024:
                raise ValueError()
            plan = json.loads(args.plan.read_text(encoding='utf-8'))
            if args.operation == 'apply':
                status = apply(database, plan, approval=args.approval_sha256, writers_drained=args.writers_drained)
            else:
                status = readback(database, plan, approval=args.approval_sha256)
            result = {'status': status}
    except Exception:
        raise SystemExit('Staging tenancy maintenance stopped. Preserve the private plan/checkpoint; inspect target and outcome before any retry.') from None
    finally:
        if database is not None:
            database.dispose()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
