"""Read-only durable-job inspection and an explicit, payload-free heartbeat.

The existing runner and job CLI remain the only scheduling/execution owners.
Mount this script into the pinned worker image; ordinary HTTP startup never uses it.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.identity import database_identity
from tabula_rasa.infrastructure.postgres.recurring_jobs import DEFINITION, policy
from tabula_rasa.infrastructure.postgres.runtime import Database


MAX_AGE = timedelta(minutes=90)
HEARTBEAT_ENV = 'TABULA_RASA_RECURRING_HEARTBEAT_URL'


def load_config(path):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or set(data) != {
        'database_sha256', 'database_role', 'entity_ids', 'business_time_zone',
    }:
        raise ValueError('Invalid monitor configuration.')
    if not re.fullmatch('[a-f0-9]{64}', str(data['database_sha256'])):
        raise ValueError('Invalid database identity.')
    if not re.fullmatch('[a-z_][a-z0-9_]{0,62}', str(data['database_role'])):
        raise ValueError('Invalid database role.')
    entities = data['entity_ids']
    if (not isinstance(entities, list) or not 1 <= len(entities) <= 20
            or any(not isinstance(entity, str) for entity in entities)
            or len(set(entities)) != len(entities)):
        raise ValueError('Supply distinct explicit entities.')
    for entity in entities:
        UUID(entity)
    ZoneInfo(data['business_time_zone'])
    return data


def assess_entity(entity, selected, definition, jobs, *, expected_zone, now):
    """Classify operational observations without recreating occurrence logic."""
    codes = []
    if selected['authority'] != 'worker':
        codes.append('worker_not_enabled')
    if selected['time_zone'] != expected_zone:
        codes.append('business_zone_mismatch')
    if (not definition or definition['paused'] or definition['interval_seconds'] != 3600
            or definition['job_type'] != 'recurring.dispatch'):
        codes.append('dispatcher_not_enabled')
    if jobs['dead']:
        codes.append('dead_jobs')
    last_dispatch = jobs['last_dispatch']
    if last_dispatch is None or now - last_dispatch > MAX_AGE:
        codes.append('dispatcher_missing_or_stale')
    if jobs['oldest_queued'] is not None and now - jobs['oldest_queued'] > MAX_AGE:
        codes.append('queued_jobs_overdue')
    if jobs['running'] and (jobs['oldest_lease'] is None or now - jobs['oldest_lease'] > MAX_AGE):
        codes.append('running_jobs_unconfirmed')
    return {'entity_id': entity, 'healthy': not codes, 'codes': codes}


def inspect(database, config, *, now=None):
    if database_identity(database) != config['database_sha256']:
        raise ValueError('Database identity differs.')
    with database.transaction(read_only=True) as connection:
        if connection.scalar(text('SELECT current_user')) != config['database_role']:
            raise ValueError('Database role differs.')
    now = now or datetime.now(timezone.utc)
    results = []
    for entity in config['entity_ids']:
        selected = policy(database, entity)
        with database.transaction(read_only=True) as connection:
            definition = connection.execute(text('''SELECT job_type,paused,interval_seconds
                FROM job_definitions WHERE entity_id=:scope AND id=:definition'''),
                {'scope': entity, 'definition': DEFINITION}).mappings().first()
            # Counts cover every retained job, including failures older than a
            # bounded recent-history view. No ledger fields or job payloads are read.
            jobs = connection.execute(text('''SELECT
                count(*) FILTER (WHERE state='dead') AS dead,
                count(*) FILTER (WHERE state='running') AS running,
                min(due_at) FILTER (WHERE state='queued') AS oldest_queued,
                min(lease_until) FILTER (WHERE state='running') AS oldest_lease,
                max(finished_at) FILTER (WHERE job_type='recurring.dispatch'
                    AND state='succeeded') AS last_dispatch
                FROM jobs WHERE entity_id=:scope'''), {'scope': entity}).mappings().one()
        results.append(assess_entity(entity, selected, definition, jobs,
            expected_zone=config['business_time_zone'], now=now))
    return {'status': 'healthy' if all(row['healthy'] for row in results) else 'unhealthy',
            'checked_at_utc': now.isoformat(), 'entities': results}


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise URLError('Heartbeat redirect refused.')


def signal(url, healthy, *, opener=None):
    """Send only the approved heartbeat token; never attach logs or database data."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'incidents.betterstack.com'
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not re.fullmatch(
                r'/api/v1/heartbeat/[A-Za-z0-9_-]{8,256}', parsed.path)):
        raise ValueError('Invalid heartbeat destination.')
    request = Request(url if healthy else url + '/fail', method='GET',
        headers={'User-Agent': 'Tabula-Rasa-Recurring-Monitor'})
    with (opener or build_opener(NoRedirects())).open(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise URLError('Heartbeat not confirmed.')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect approved recurring jobs without generating entries.')
    parser.add_argument('--config', required=True, help='Protected JSON binding metadata; never credentials.')
    parser.add_argument('--notify', action='store_true', help='Send a heartbeat only with prior operator approval.')
    parser.add_argument('--worker-exit-code', type=int, default=0,
                        help='Exit code from the existing bounded runner; nonzero always reports failure.')
    args = parser.parse_args(argv)
    database = None
    try:
        config = load_config(args.config)
        database = Database(DatabaseSettings.from_environment(required=True))
        result = inspect(database, config)
    except Exception:
        # No exception text, URLs, credentials, SQL or provider bodies reach output.
        result = {'status': 'unconfirmed', 'codes': ['inspection_unconfirmed']}
    finally:
        if database is not None:
            database.dispose()
    if args.worker_exit_code:
        result['status'] = 'unhealthy'
        result.setdefault('codes', []).append('worker_command_failed')
    if args.notify:
        try:
            signal(os.environ.get(HEARTBEAT_ENV, ''), result['status'] == 'healthy')
            result['signal'] = 'confirmed'
        except Exception:
            result['signal'] = 'unconfirmed'
    print(json.dumps(result))
    return 0 if result['status'] == 'healthy' and result.get('signal') != 'unconfirmed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
