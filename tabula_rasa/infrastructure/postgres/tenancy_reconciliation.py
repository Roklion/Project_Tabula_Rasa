"""Explicit two-business synthetic maintenance, never a runtime conversion."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from psycopg import sql
from sqlalchemy import text

from .identity import database_identity
from .migrations import MIGRATION_ROOT, current_revision

SOURCE = '0015_support_controls'
MUTABLE = ('organizations', 'memberships', 'organization_entities', 'workspace_bootstraps')
REFERENCING = {'workspace_bootstraps', 'identity_sessions', 'external_connections', 'legacy_entity_claims'}


class ReconciliationError(ValueError):
    def __init__(self):
        super().__init__('Reconciliation stopped; inspect the private plan and target without retrying writes.')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def fingerprint(value):
    return sha256(canonical(value).encode()).hexdigest()


def _require(condition):
    if not condition:
        raise ReconciliationError()


def _execute(connection, statement):
    return connection.exec_driver_sql(statement.as_string())


def _tables(connection):
    return connection.execute(text("""SELECT tablename FROM pg_tables
        WHERE schemaname='public' ORDER BY tablename""")).scalars().all()


def _guard(connection):
    row = connection.execute(text("""SELECT pg_get_functiondef(p.oid) AS definition,
        p.prosrc AS body, pg_get_userbyid(p.proowner) AS owner, p.prosecdef,
        current_user AS actor, pg_has_role(current_user,p.proowner,'USAGE') AS owns
        FROM pg_proc p WHERE p.oid='public.guard_identity_change()'::regprocedure""")).mappings().one()
    published = (MIGRATION_ROOT / 'versions/0006_identity_control_plane.sql').read_text()
    expected = published.split('CREATE FUNCTION guard_identity_change()', 1)[1].split('$$', 2)[1]
    _require(row['body'].strip() == expected.strip() and not row['prosecdef'])
    _require(connection.scalar(text("""SELECT count(*) FROM pg_trigger
        WHERE tgrelid='public.organization_entities'::regclass AND tgname='identity_change'
        AND tgfoid='public.guard_identity_change()'::regprocedure AND tgenabled='O'
        AND tgtype=19 AND tgnargs=0 AND tgattr=''::int2vector""")) == 1)
    return dict(row)


def _separate_runtime(connection, role, owner):
    _require(connection.scalar(text("""SELECT EXISTS (SELECT 1 FROM pg_roles
        WHERE rolname=:role AND rolcanlogin AND NOT pg_has_role(oid,CAST(:owner AS regrole),'USAGE'))"""),
        {'role': role, 'owner': owner}))


def _schema(connection):
    # Include ownership/access and definitions; the maintenance exception and
    # temporary FK deferral must leave no durable privilege/schema difference.
    rows = connection.execute(text("""SELECT 'function',p.oid::regprocedure::text,
        pg_get_functiondef(p.oid),p.proowner::text,coalesce(p.proacl::text,'')
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.prokind='f'
        UNION ALL SELECT 'constraint',c.conrelid::regclass::text||':'||c.conname,
        pg_get_constraintdef(c.oid),c.convalidated::text,'' FROM pg_constraint c
        WHERE c.connamespace='public'::regnamespace
        UNION ALL SELECT 'trigger',t.tgrelid::regclass::text||':'||t.tgname,
        pg_get_triggerdef(t.oid),t.tgenabled::text,'' FROM pg_trigger t
        JOIN pg_class c ON c.oid=t.tgrelid WHERE c.relnamespace='public'::regnamespace
        AND NOT t.tgisinternal
        UNION ALL SELECT 'table',c.relname,c.relrowsecurity::text,c.relowner::text,
        coalesce(c.relacl::text,'') FROM pg_class c
        WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'""")).all()
    return fingerprint(sorted([list(row) for row in rows]))


def _snapshot(connection):
    mutable, protected = {}, {}
    for table in _tables(connection):
        if table in MUTABLE:
            rows = _execute(connection, sql.SQL('SELECT row_to_json(t) FROM public.{} t').format(
                sql.Identifier(table))).scalars().all()
            mutable[table] = sorted(rows, key=canonical)
        else:
            # Only hashes leave PostgreSQL; never retain credentials, financial
            # rows, audit payloads or receipt metadata in this private plan.
            protected[table] = _execute(connection, sql.SQL("""SELECT count(*)::text || ':' ||
                encode(sha256(convert_to(coalesce(string_agg(h,'' ORDER BY h),''),'UTF8')),'hex')
                FROM (SELECT encode(sha256(convert_to(to_jsonb(t)::text,'UTF8')),'hex') AS h
                FROM public.{} t) rows""").format(sql.Identifier(table))).scalar_one()
    return {'mutable': mutable, 'protected': protected, 'schema': _schema(connection)}


def _references(connection, entity):
    rows = connection.execute(text("""SELECT c.conname,t.relname,c.condeferrable,c.condeferred,c.convalidated,
        pg_get_constraintdef(c.oid) AS definition,
        ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num,ord)
              JOIN pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.num ORDER BY k.ord) AS columns
        FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
        WHERE c.contype='f' AND c.confrelid='public.organization_entities'::regclass
        ORDER BY t.relname,c.conname""")).mappings().all()
    _require({r['relname'] for r in rows} == REFERENCING and len(rows) == len(REFERENCING))
    for row in rows:
        _require(row['columns'] == ['organization_id', 'entity_id'] and row['convalidated'])
        if row['relname'] != 'workspace_bootstraps':
            count = _execute(connection, sql.SQL('SELECT count(*) FROM public.{} WHERE entity_id={}').format(
                sql.Identifier(row['relname']), sql.Literal(entity))).scalar_one()
            _require(count == 0)
    return next(dict(row) for row in rows if row['relname'] == 'workspace_bootstraps')


def prepare(database, *, source_org, retained_entity, moved_entity, owner, destination_org,
            recovery_sha256, runtime_role='tabula_staging_runtime'):
    """Capture a private, immutable proposal after the operator drains writers."""
    _require(re.fullmatch('[0-9a-f]{64}', recovery_sha256 or '') is not None
             and recovery_sha256 != '0' * 64)
    _require(all(isinstance(v, str) and re.fullmatch('[A-Za-z0-9_-]{1,128}', v)
                 for v in (source_org, retained_entity, moved_entity, owner, destination_org, runtime_role)))
    _require(retained_entity != moved_entity and source_org != destination_org)
    with database.transaction(read_only=True) as connection:
        _require(current_revision(connection) == SOURCE)
        _require(connection.execute(text('SELECT environment FROM identity_environments ORDER BY environment')).scalars().all()
                 == ['staging'])
        guard = _guard(connection)
        state = _snapshot(connection)
        rows = state['mutable']
        _require(len(rows['organizations']) == 2 and len(rows['organization_entities']) == 3)
        org = next((r for r in rows['organizations'] if r['id'] == source_org), None)
        _require(org is not None and org['state'] == 'active')
        _require(not any(r['id'] == destination_org for r in rows['organizations']))
        bindings = [r for r in rows['organization_entities'] if r['organization_id'] == source_org]
        _require({r['entity_id'] for r in bindings} == {retained_entity, moved_entity}
                 and len(bindings) == 2 and all(r['state'] == 'active' for r in bindings))
        members = [r for r in rows['memberships'] if r['organization_id'] == source_org]
        active = [r for r in members if r['state'] == 'active']
        _require(len(active) == 1 and active[0]['role'] == 'owner' and active[0]['user_id'] == owner)
        inactive = [r for r in members if r['state'] == 'inactive']
        _require(len(members) == 2 and len(inactive) == 1 and inactive[0]['role'] == 'read_only')
        _require(connection.scalar(text("SELECT state='active' FROM identity_users WHERE id=:id"), {'id': owner}))
        receipts = [r for r in rows['workspace_bootstraps'] if r['entity_id'] == moved_entity]
        _require(len(receipts) == 1 and receipts[0]['organization_id'] == source_org
                 and receipts[0]['user_id'] == owner)
        _require(connection.scalar(text('SELECT count(*) FROM support_grants WHERE organization_id=:org'),
                                   {'org': source_org}) == 0)
        _require(connection.execute(text('SELECT state FROM workspace_invitations WHERE organization_id=:org'),
                                    {'org': source_org}).scalars().all() == ['accepted'])
        receipt_fk = _references(connection, moved_entity)
        _require(not receipt_fk['condeferrable'] and not receipt_fk['condeferred'])
        name = connection.scalar(text('SELECT name FROM business_entities WHERE id=:id'), {'id': moved_entity})
        _require(isinstance(name, str) and 0 < len(name) <= 160)
        _require(guard['owns'] and guard['actor'] != runtime_role)
        _separate_runtime(connection, runtime_role, guard['owner'])
        created_at = connection.scalar(text('SELECT to_json(CURRENT_TIMESTAMP)'))
    return {'format': 1, 'environment': 'staging', 'database_sha256': database_identity(database),
            'source_revision': SOURCE, 'source_org': source_org, 'retained_entity': retained_entity,
            'moved_entity': moved_entity, 'owner': owner, 'destination_org': destination_org,
            'destination_name': name, 'created_at': created_at,
            'recovery_sha256': recovery_sha256, 'runtime_role': runtime_role,
            'migration_role': guard['actor'], 'before': state}


def _expected(plan):
    result = deepcopy(plan['before'])
    rows = result['mutable']
    rows['organizations'].append({'id': plan['destination_org'], 'name': plan['destination_name'],
                                  'state': 'active', 'created_at': plan['created_at']})
    rows['memberships'].append({'organization_id': plan['destination_org'], 'user_id': plan['owner'],
                               'role': 'owner', 'state': 'active', 'authorization_version': 1})
    for table in ('organization_entities', 'workspace_bootstraps'):
        for row in rows[table]:
            if row['entity_id'] == plan['moved_entity']:
                row['organization_id'] = plan['destination_org']
    result['mutable'] = {table: sorted(values, key=canonical) for table, values in rows.items()}
    return result


def _check_plan(database, plan, approval):
    _require(plan['format'] == 1 and plan['environment'] == 'staging'
             and plan['source_revision'] == SOURCE and approval == fingerprint(plan)
             and plan['database_sha256'] == database_identity(database))


def readback(database, plan, *, approval):
    """One bounded outcome check; never repeat a move after an uncertain commit."""
    _check_plan(database, plan, approval)
    with database.transaction(read_only=True) as connection:
        _require(current_revision(connection) == SOURCE)
        state = _snapshot(connection)
    if state == _expected(plan):
        return 'applied'
    if state == plan['before']:
        return 'not_applied'
    raise ReconciliationError()


def apply(database, plan, *, approval, writers_drained=False):
    """Migration-owner-only transaction; no automatic upgrade or hosted action."""
    _check_plan(database, plan, approval)
    _require(writers_drained is True)
    with database.transaction() as connection:
        connection.execute(text("SET LOCAL lock_timeout='5s'"))
        connection.execute(text("SET LOCAL statement_timeout='30s'"))
        connection.execute(text('SELECT pg_advisory_xact_lock(244,1)'))
        # All source fingerprints must describe the same frozen maintenance
        # state. EXCLUSIVE blocks writers, not ordinary SELECTs.
        for table in _tables(connection):
            _execute(connection, sql.SQL('LOCK TABLE public.{} IN EXCLUSIVE MODE').format(sql.Identifier(table)))
        _require(current_revision(connection) == SOURCE)
        guard = _guard(connection)
        _require(guard['owns'] and guard['actor'] == plan['migration_role']
                 and guard['actor'] != plan['runtime_role'])
        _separate_runtime(connection, plan['runtime_role'], guard['owner'])
        _require(connection.scalar(text('SELECT count(*) FROM pg_stat_activity WHERE usename=:role'),
                                   {'role': plan['runtime_role']}) == 0)
        _require(_snapshot(connection) == plan['before'])
        fk = _references(connection, plan['moved_entity'])
        # Literal values are quoted by psycopg, never interpolated as SQL/code.
        permit = sql.SQL("""\n        IF current_user={} AND OLD.entity_id={} AND NEW.entity_id=OLD.entity_id
            AND OLD.organization_id={} AND NEW.organization_id={}
            AND NEW.state IS NOT DISTINCT FROM OLD.state THEN RETURN NEW; END IF;\n""").format(
                sql.Literal(guard['actor']), sql.Literal(plan['moved_entity']),
                sql.Literal(plan['source_org']), sql.Literal(plan['destination_org'])).as_string()
        marker = "ELSIF TG_TABLE_NAME='organization_entities' THEN"
        _require(guard['definition'].count(marker) == 1)
        changed_body = guard['body'].replace(marker, marker + permit)
        quoted_body = sql.Literal(changed_body).as_string()
        original_body = '$function$' + guard['body'] + '$function$'
        _require(guard['definition'].count(original_body) == 1)
        connection.exec_driver_sql(guard['definition'].replace(original_body, quoted_body))
        _execute(connection, sql.SQL('ALTER TABLE public.workspace_bootstraps ALTER CONSTRAINT {} DEFERRABLE INITIALLY DEFERRED')
                 .format(sql.Identifier(fk['conname'])))
        connection.execute(text('INSERT INTO organizations(id,name,created_at) VALUES (:id,:name,:created)'),
                           {'id': plan['destination_org'], 'name': plan['destination_name'], 'created': plan['created_at']})
        connection.execute(text("INSERT INTO memberships(organization_id,user_id,role) VALUES (:org,:user,'owner')"),
                           {'org': plan['destination_org'], 'user': plan['owner']})
        connection.execute(text('UPDATE organization_entities SET organization_id=:new WHERE entity_id=:entity AND organization_id=:old'),
                           {'new': plan['destination_org'], 'entity': plan['moved_entity'], 'old': plan['source_org']})
        connection.execute(text('UPDATE workspace_bootstraps SET organization_id=:new WHERE entity_id=:entity AND organization_id=:old'),
                           {'new': plan['destination_org'], 'entity': plan['moved_entity'], 'old': plan['source_org']})
        connection.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        _execute(connection, sql.SQL('ALTER TABLE public.workspace_bootstraps ALTER CONSTRAINT {} NOT DEFERRABLE INITIALLY IMMEDIATE')
                 .format(sql.Identifier(fk['conname'])))
        connection.exec_driver_sql(guard['definition'])
        _require(_snapshot(connection) == _expected(plan))
    return 'applied'


def write_plan(path, plan):
    """Never overwrite the original provenance; operator owns private ACLs."""
    path = Path(path)
    _require(path.is_absolute() and not path.is_symlink())
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(canonical(plan) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    return fingerprint(plan)
