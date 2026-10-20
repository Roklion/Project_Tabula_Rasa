"""Synthetic cleanup previews cannot authorize deletion or weaken retention."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts import preview_resource_retirement as cli
from tabula_rasa.deployment.resource_retirement import (
    InventoryError, preview, read_inventory, validate_inventory,
)

NOW = datetime(2026, 10, 20, 3, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def resource(identifier='synthetic-a', **overrides):
    return {
        'id': identifier, 'kind': 'postgres_database', 'scope': 'synthetic-project-a',
        'provider_id': 'db-a', 'environment': 'test', 'owner': 'test-operator',
        'disposition': 'disposable_synthetic', 'authority': 'inactive',
        'protections': [], 'references': [], 'depends_on': [],
        'last_backup': 'private-verified-export-sha256', 'handoff': 'issue-377-D7-reviewed',
        'rollback': 'synthetic-recreate-plan', 'evidence': 'private-reference-check-sha256',
        'effects': [identifier], **overrides,
    }


def inventory(*resources):
    return {'version': 1, 'stage': 'owner_operated', 'observed_at': NOW.isoformat(),
            'coverage': 'operator_verified', 'resources': list(resources) or [resource()]}


def test_exact_preview_requires_manual_approval_and_is_deterministic():
    document = inventory()
    before = deepcopy(document)
    result = preview(document, ['synthetic-a'], now=NOW)
    assert result['status'] == 'requires_manual_approval'
    assert result['applied'] is False
    assert result['targets'][0]['provider_id'] == 'db-a'
    assert result['targets'][0]['effects'] == ['synthetic-a']
    assert 'exact_target_set_operator_approval' in result['required_approvals']
    assert result == preview(document, ['synthetic-a'], now=NOW)
    assert document == before
    document['resources'][0]['last_backup'] = 'different-preserved-backup'
    assert preview(document, ['synthetic-a'], now=NOW)['plan_sha256'] != result['plan_sha256']
    assert before['resources'][0]['last_backup'] == 'private-verified-export-sha256'


@pytest.mark.parametrize(('changes', 'blocker'), [
    ({'authority': 'active'}, 'active_or_unknown_authority'),
    ({'authority': 'unknown'}, 'active_or_unknown_authority'),
    ({'environment': 'production'}, 'protected_or_unknown_environment'),
    ({'environment': 'staging'}, 'protected_or_unknown_environment'),
    ({'environment': 'uat'}, 'protected_or_unknown_environment'),
    ({'environment': 'unknown'}, 'protected_or_unknown_environment'),
    ({'disposition': 'required_evidence'}, 'not_disposable_synthetic'),
    ({'protections': ['recovery']}, 'protected_retention'),
    ({'references': ['ci-workflow']}, 'live_or_retained_references'),
    ({'references': ['retained-rehearsal']}, 'live_or_retained_references'),
    ({'provider_id': None}, 'identity_or_owner_unresolved'),
    ({'provider_id': 'unknown'}, 'identity_or_owner_unresolved'),
    ({'scope': 'unknown'}, 'identity_or_owner_unresolved'),
    ({'owner': 'unknown'}, 'identity_or_owner_unresolved'),
    ({'last_backup': None}, 'missing_preservation_or_handoff_evidence'),
    ({'last_backup': 'unknown'}, 'missing_preservation_or_handoff_evidence'),
    ({'handoff': None}, 'missing_preservation_or_handoff_evidence'),
    ({'rollback': None}, 'missing_preservation_or_handoff_evidence'),
    ({'evidence': None}, 'missing_preservation_or_handoff_evidence'),
    ({'effects': []}, 'effects_unreviewed'),
    ({'kind': 'nas_generation'}, 'separate_retention_policy_required'),
    ({'kind': 'sheets_workbook'}, 'separate_retention_policy_required'),
    ({'kind': 'schema_history'}, 'separate_retention_policy_required'),
])
def test_refuses_unsafe_target(changes, blocker):
    result = preview(inventory(resource(**changes)), ['synthetic-a'], now=NOW)
    assert result['status'] == 'blocked'
    assert blocker in result['targets'][0]['blockers']


@pytest.mark.parametrize('age', [timedelta(hours=25), timedelta(seconds=-1)])
def test_requires_recent_observation(age):
    document = inventory()
    document['observed_at'] = (NOW - age).isoformat()
    assert 'inventory_stale_or_future' in preview(document, ['synthetic-a'], now=NOW)['targets'][0]['blockers']


def test_cascade_requires_each_effect_and_blocks_protected_child():
    branch = resource(kind='postgres_branch', effects=['synthetic-a', 'child'])
    child = resource('child', provider_id='child-db', depends_on=['synthetic-a'],
                     protections=['drill_evidence'])
    document = inventory(branch, child)
    result = preview(document, ['synthetic-a'], now=NOW)
    assert set(result['targets'][0]['blockers']) >= {'effects_outside_target_set', 'retained_consumers'}
    assert result['targets'][0]['retained_consumers'] == ['child']
    result = preview(document, ['child', 'synthetic-a'], now=NOW)
    assert result['status'] == 'blocked'
    assert 'protected_retention' in result['targets'][0]['blockers']
    child['protections'] = []
    assert preview(document, ['child', 'synthetic-a'], now=NOW)['status'] == 'requires_manual_approval'


def test_same_database_name_in_two_scopes_does_not_select_other_profile():
    first = resource('profile-a')
    second = resource('profile-b', scope='synthetic-project-b', authority='active')
    document = inventory(first, second)
    result = preview(document, ['profile-a'], now=NOW)
    assert result['status'] == 'requires_manual_approval'
    assert [r['id'] for r in result['targets']] == ['profile-a']
    assert second['authority'] == 'active'
    second['depends_on'] = ['profile-a']
    assert preview(document, ['profile-a'], now=NOW)['status'] == 'blocked'


@pytest.mark.parametrize('change', ['duplicate_id', 'duplicate_identity', 'dangling', 'extra', 'missing', 'url', 'bad_date'])
def test_malformed_inventory_is_refused(change):
    document = inventory()
    if change in {'duplicate_id', 'duplicate_identity'}:
        document['resources'].append(resource('synthetic-a' if change == 'duplicate_id' else 'alias'))
    elif change == 'dangling':
        document['resources'][0]['depends_on'] = ['missing']
    elif change == 'extra':
        document['credentials'] = 'private-sentinel'
    elif change == 'missing':
        del document['resources'][0]['effects']
    elif change == 'url':
        document['resources'][0]['provider_id'] = 'postgresql://private-sentinel@host/db'
    else:
        document['observed_at'] = '2026-10-20'
    with pytest.raises(InventoryError):
        preview(document, ['synthetic-a'], now=NOW)


def test_inventory_seed_is_complete_as_a_desk_inventory_and_blocks_every_row():
    document = read_inventory(ROOT / 'docs/operations/resource-inventory.json')
    rows = validate_inventory(document)
    assert document['coverage'] == 'unverified'
    result = preview(document, list(rows), now=NOW)
    assert result['status'] == 'blocked'
    assert all('inventory_coverage_unverified' in r['blockers'] for r in result['targets'])
    assert {'sheets-frozen-sources', 'nas-mislabeled-generation', 'audit-342-failed-empty-target',
            'temporary-render-bindings', 'forward-alembic-history', 'snapshot-259'} <= rows.keys()


@pytest.mark.parametrize('contents', [
    '{"private-sentinel":', '{"version":1,"version":2}',
    '{"credential":"postgresql://private-sentinel@host/db"}',
])
def test_cli_invalid_input_never_echoes_raw_contents(tmp_path, capsys, contents):
    path = tmp_path / 'private-sentinel.json'
    path.write_text(contents)
    assert cli.main(['--inventory', str(path), '--target', 'synthetic-a']) == 2
    assert json.loads(capsys.readouterr().out) == {
        'status': 'blocked', 'code': 'invalid_inventory', 'applied': False,
    }


def test_cli_missing_file_and_unknown_target_do_not_leak(tmp_path, capsys):
    path = tmp_path / 'private-sentinel.json'
    assert cli.main(['--inventory', str(path), '--target', 'synthetic-a']) == 2
    path.write_text(json.dumps(inventory()))
    assert cli.main(['--inventory', str(path), '--target', 'private-sentinel']) == 2
    assert 'private-sentinel' not in capsys.readouterr().out


def test_cli_preview_exit_codes_without_writes(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'inventory.json'
    document = inventory()
    document['observed_at'] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(document))
    original = path.read_bytes()
    monkeypatch.setenv('TABULA_RASA_DATABASE_URL', 'postgresql://private-sentinel@production/live')
    assert cli.main(['--inventory', str(path), '--target', 'synthetic-a']) == 0
    assert json.loads(capsys.readouterr().out)['status'] == 'requires_manual_approval'
    assert path.read_bytes() == original
    document['resources'][0]['authority'] = 'active'
    path.write_text(json.dumps(document))
    assert cli.main(['--inventory', str(path), '--target', 'synthetic-a']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'blocked'
    # The CLI only reads; both written versions remain byte-for-byte intact.
    assert json.loads(original)['resources'][0]['authority'] == 'inactive'
    assert path.read_text() == json.dumps(document)
