"""Offline, fail-closed resource-disposition preview for #339. Never deletes."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re


class InventoryError(ValueError):
    """Invalid sanitized inventory; do not echo input or parser exceptions."""


KINDS = {
    'postgres_branch', 'postgres_database', 'postgres_endpoint', 'postgres_role', 'managed_snapshot',
    'nas_generation', 'sheets_workbook', 'drive_artifact', 'local_artifact',
    'deployment_binding', 'fixture', 'schema_history',
}
PROTECTIONS = {
    'source', 'live', 'recovery', 'drill_evidence', 'legacy_snapshot',
    'nas_indefinite', 'document_bytes', 'schema_history', 'customer_retention',
}
FIELDS = {
    'id', 'kind', 'scope', 'provider_id', 'environment', 'owner', 'disposition',
    'authority', 'protections', 'references', 'depends_on', 'last_backup',
    'handoff', 'rollback', 'evidence', 'effects',
}


def _require(condition):
    if not condition:
        raise InventoryError('invalid_inventory')


def _handle(value):
    # Handles only: no URLs, filesystem paths, connection strings or free text.
    _require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}', value))


def _handles(values):
    _require(type(values) is list)
    for value in values:
        _handle(value)
    _require(len(values) == len(set(values)))


def _instant(value):
    _require(isinstance(value, str))
    try:
        result = datetime.fromisoformat(value)
        _require(result.utcoffset() == timedelta(0))
        return result
    except (ValueError, TypeError):
        raise InventoryError('invalid_inventory') from None


def validate_inventory(document):
    """Validate the entire file before returning any user-controlled output."""
    _require(type(document) is dict and set(document) == {
        'version', 'stage', 'observed_at', 'coverage', 'resources',
    })
    _require(type(document['version']) is int and document['version'] == 1)
    _require(document['stage'] in {'technical_alpha', 'owner_operated', 'external_beta', 'commercial'})
    _instant(document['observed_at'])
    _require(document['coverage'] in {'unverified', 'operator_verified'})
    _require(type(document['resources']) is list and document['resources'])
    by_id, identities = {}, set()
    for row in document['resources']:
        _require(type(row) is dict and set(row) == FIELDS)
        for key in ('id', 'scope', 'owner'):
            _handle(row[key])
        for key in ('provider_id', 'last_backup', 'handoff', 'rollback', 'evidence'):
            if row[key] is not None:
                _handle(row[key])
        for key in ('protections', 'references', 'depends_on', 'effects'):
            _handles(row[key])
        _require(row['kind'] in KINDS)
        _require(row['environment'] in {'unknown', 'development', 'test', 'uat', 'staging', 'production', 'archive'})
        _require(row['disposition'] in {'retained_source', 'active_recoverable', 'required_evidence',
                                        'disposable_synthetic', 'unresolved'})
        _require(row['authority'] in {'unknown', 'active', 'inactive', 'not_applicable'})
        _require(set(row['protections']) <= PROTECTIONS)
        _require(row['id'] not in by_id)
        if row['provider_id'] is not None:
            identity = (row['kind'], row['scope'], row['provider_id'])
            _require(identity not in identities)
            identities.add(identity)
        by_id[row['id']] = row
    for row in by_id.values():
        _require(set(row['depends_on'] + row['effects']) <= by_id.keys())
        _require(row['id'] not in row['depends_on'])
    return by_id


def preview(document, targets, *, now=None):
    """Assess an explicit set, including collateral effects and incoming consumers.

    All facts are operator attestations. Eligibility is not authority to delete.
    The 24h bound forces a new inventory before later execution; it cannot prove
    that the provider state has stayed unchanged since the observation.
    """
    rows = validate_inventory(document)
    _handles(targets)
    _require(targets and set(targets) <= rows.keys())
    now = now or datetime.now(timezone.utc)
    age = now - _instant(document['observed_at'])
    global_blocks = []
    if document['coverage'] != 'operator_verified':
        global_blocks.append('inventory_coverage_unverified')
    if not timedelta(0) <= age <= timedelta(hours=24):
        global_blocks.append('inventory_stale_or_future')
    selected, results = set(targets), []
    for target in sorted(selected):
        row = rows[target]
        reasons = list(global_blocks)
        if row['disposition'] != 'disposable_synthetic':
            reasons.append('not_disposable_synthetic')
        if row['protections']:
            reasons.append('protected_retention')
        if row['kind'] in {'nas_generation', 'sheets_workbook', 'schema_history'}:
            reasons.append('separate_retention_policy_required')
        if row['environment'] not in {'development', 'test'}:
            reasons.append('protected_or_unknown_environment')
        if row['authority'] not in {'inactive', 'not_applicable'}:
            reasons.append('active_or_unknown_authority')
        if row['provider_id'] in {None, 'unknown'} or row['scope'] == 'unknown' or row['owner'] == 'unknown':
            reasons.append('identity_or_owner_unresolved')
        if row['references']:
            reasons.append('live_or_retained_references')
        if any(row[key] in {None, 'unknown'} for key in ('last_backup', 'handoff', 'rollback', 'evidence')):
            reasons.append('missing_preservation_or_handoff_evidence')
        # Every side effect is another exact resource, reviewed under the same
        # guards. Empty effects means unknown, not an assertion of no cascade.
        if target not in row['effects']:
            reasons.append('effects_unreviewed')
        if set(row['effects']) - selected:
            reasons.append('effects_outside_target_set')
        consumers = sorted(other['id'] for other in rows.values()
                           if target in other['depends_on'] and other['id'] not in selected)
        if consumers:
            reasons.append('retained_consumers')
        results.append({**row, 'retained_consumers': consumers, 'blockers': reasons})
    payload = {'stage': document['stage'], 'observed_at': document['observed_at'],
               'inventory_sha256': sha256(json.dumps(document, sort_keys=True,
                                                     separators=(',', ':')).encode()).hexdigest(),
               'targets': results}
    plan_hash = sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**payload, 'plan_sha256': plan_hash, 'applied': False,
            'status': 'blocked' if any(row['blockers'] for row in results) else 'requires_manual_approval',
            'required_approvals': ['exact_target_set_operator_approval', 'fresh_reference_and_effects_recheck',
                                   'stage_retention_owner_review', 'retained_resource_postchecks']}


def read_inventory(path):
    """Reject duplicate JSON keys rather than allowing last-key-wins overrides."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
