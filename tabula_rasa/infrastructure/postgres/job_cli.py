"""Bounded, explicit operator invocation; HTTP startup never calls this module."""

import argparse
from datetime import datetime, timezone
import json

from .config import DatabaseSettings
from .jobs import JobQueue, JobRegistry
from .runtime import Database


def operator_registry():
    registry = JobRegistry()

    def probe(database, execution):
        from .composition import create_postgres_services
        create_postgres_services(database, execution.entity_id).ledger.get_info()

    registry.register('ledger.probe', probe)
    return registry


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explicit entity-bound PostgreSQL job operator')
    parser.add_argument('command', choices=['inspect', 'attempts', 'enqueue-probe', 'define-probe',
                                          'tick', 'pause', 'resume', 'cancel', 'retry'])
    parser.add_argument('--entity', required=True)
    parser.add_argument('--service-id', required=True)
    parser.add_argument('--id')
    parser.add_argument('--interval-seconds', type=int, default=3600)
    parser.add_argument('--budget', type=int, default=1)
    parser.add_argument('--allow-mutations', action='store_true')
    args = parser.parse_args(argv)
    if args.command not in {'inspect', 'attempts'} and not args.allow_mutations:
        parser.error('Mutations require --allow-mutations and prior operator environment approval.')
    if args.command in {'attempts', 'enqueue-probe', 'define-probe', 'pause', 'resume', 'cancel', 'retry'} and not args.id:
        parser.error('This command requires --id.')
    if not 1 <= args.budget <= 100:
        parser.error('Budget must be between 1 and 100.')
    database = None
    try:
        database = Database(DatabaseSettings.from_environment(required=True))
        queue = JobQueue(database, args.entity, operator_registry(), service_id=args.service_id)
        if args.command == 'inspect':
            result = queue.diagnostics()
        elif args.command == 'attempts':
            result = queue.attempts(args.id)
        elif args.command == 'enqueue-probe':
            result = {'id': queue.enqueue('ledger.probe', args.id)}
        elif args.command == 'define-probe':
            queue.define(args.id, 'ledger.probe', interval_seconds=args.interval_seconds, first_due=datetime.now(timezone.utc))
            result = {'status': 'defined'}
        elif args.command == 'tick':
            result = {'executed': sum(queue.tick() for _ in range(args.budget))}
        elif args.command in {'pause', 'resume'}:
            queue.pause(args.id, paused=args.command == 'pause')
            result = {'status': args.command}
        else:
            result = {'changed': getattr(queue, args.command)(args.id)}
        print(json.dumps(result, default=str, sort_keys=True))
        return 0
    except Exception:
        # Never expose SQL, DB URLs, handler exception text or bookkeeping data.
        print(json.dumps({'error': 'job_operation_unconfirmed', 'guidance': 'Inspect durable job status before retrying.'}))
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
