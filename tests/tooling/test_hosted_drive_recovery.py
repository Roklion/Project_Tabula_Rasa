"""Hosted orchestration must isolate credentials and retain encrypted evidence."""
import io
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest
import yaml

from scripts import run_hosted_drive_recovery as runner


def test_workflow_requires_manual_main_history_and_keeps_service_network_private():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / '.github/workflows/drive-recovery-drill.yml').read_text(), Loader=yaml.BaseLoader)
    assert set(workflow['on']) == {'workflow_dispatch'}
    assert workflow['permissions'] == {'contents': 'read'}
    job = workflow['jobs']['recovery']
    assert job['environment'] == 'receipt-recovery-drill'
    assert 'ports' not in job['services']['postgres']
    steps = job['steps']
    gate = next(index for index, step in enumerate(steps) if 'merge-base --is-ancestor' in step.get('run', ''))
    credential_step = next(index for index, step in enumerate(steps) if 'DRIVE_RECOVERY_STAGING_BINDING' in step.get('env', {}))
    assert gate < credential_step
    assert all(not step.get('with', {}).get('persist-credentials', 'false') == 'true' for step in steps if step.get('uses', '').startswith('actions/checkout@'))


@pytest.fixture(autouse=True)
def process_state(monkeypatch):
    previous = runner.os.umask(0o077)
    runner.os.umask(previous)
    monkeypatch.setattr(runner.sys, 'path', list(runner.sys.path))
    yield
    runner.os.umask(previous)


def environment(tmp_path, monkeypatch, binding):
    source = tmp_path / 'workspace' / 'source'
    source.mkdir(parents=True)
    temporary = tmp_path / 'private'
    temporary.mkdir()
    key = Fernet.generate_key()
    for name, value in {
        'GITHUB_WORKSPACE': str(source.parent), 'RUNNER_TEMP': str(temporary),
        'GITHUB_RUN_ID': 'synthetic-run', 'SOURCE_SHA': 'a' * 40,
        'DRIVE_RECOVERY_ARCHIVE_KEY': key.decode(),
        'DRIVE_RECOVERY_STAGING_BINDING': json.dumps(binding),
        'TABULA_RASA_DATABASE_URL': 'production-binding-must-not-propagate',
    }.items():
        monkeypatch.setenv(name, value)
    return source, temporary / 'drive-recovery-evidence', key


def test_invalid_binding_fails_before_provider_or_test_and_retains_only_encrypted_private_artifact(tmp_path, monkeypatch, capsys):
    _, output, key = environment(tmp_path, monkeypatch, {'private-marker': 'synthetic-secret-value'})
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid binding must stop before any test execution')
    monkeypatch.setattr(runner.subprocess, 'run', forbidden)
    assert runner.main() == 1
    evidence = json.loads((output / 'sanitized-evidence.json').read_text())
    assert not evidence['passed'] and evidence['exception_type'] == 'AssertionError'
    assert set(path.name for path in output.iterdir()) == {'sanitized-evidence.json', 'private-recovery.tar.gz.fernet'}
    assert Fernet(key).decrypt((output / 'private-recovery.tar.gz.fernet').read_bytes())
    assert 'synthetic-secret-value' not in capsys.readouterr().out


def configurations():
    return {entity: {mode: {'profile_key': 'stage-' + entity,
        'google_drive_oauth': {'client_secret': 'synthetic-client-secret'},
        'google_drive': {'authorized_email': 'synthetic@example.test', 'receipt_folder': {'id': entity + '-' + mode}}}
        for mode in ('source', 'target')} for entity in ('alpha', 'beta')}


class FakeClient:
    occupied = ''
    def __init__(self, config, grant):
        self.grant = grant
    def validate_storage_configuration(self, profile):
        assert self.grant['receipt_folder']['id'].startswith(profile.removeprefix('stage-'))
    def _request(self, method, url, **kwargs):
        assert method == 'GET'
        data = {'user': {'emailAddress': 'synthetic@example.test'}} if url.endswith('/about') else {
            'ownedByMe': True, 'shared': False, 'capabilities': {'canAddChildren': True}}
        return SimpleNamespace(json=lambda: data)
    def _list(self, query, **kwargs):
        return [{}] if self.grant['receipt_folder']['id'] == self.occupied else []


def provider(monkeypatch):
    monkeypatch.setattr('tabula_rasa.google_drive.GoogleDriveClient', FakeClient)
    monkeypatch.setattr('tabula_rasa.google_drive.load_oauth_config', lambda value: value)


def test_occupied_beta_target_stops_before_upload_or_database_execution(tmp_path, monkeypatch):
    _, output, _ = environment(tmp_path, monkeypatch, configurations())
    provider(monkeypatch)
    monkeypatch.setattr(FakeClient, 'occupied', 'beta-target')
    monkeypatch.setattr(runner.subprocess, 'run', lambda *a, **k: pytest.fail('Must not run on occupied folders'))
    assert runner.main() == 1
    assert not json.loads((output / 'sanitized-evidence.json').read_text())['passed']


@pytest.mark.parametrize('exit_code', [0, 1])
def test_test_environment_isolated_and_success_or_failure_artifacts_never_expose_private_inputs(tmp_path, monkeypatch, capsys, exit_code):
    source, output, key = environment(tmp_path, monkeypatch, configurations())
    provider(monkeypatch)
    receipt = b'synthetic-private-receipt'
    import hashlib
    digest = hashlib.sha256(receipt).hexdigest()
    class Archive:
        def __init__(self, path, entity):
            self.documents = [SimpleNamespace(metadata=SimpleNamespace(sha256=digest, byte_size=len(receipt)),
                storage_key=str(index)) for index in (1, 2)]
        def fetch(self, entity, storage_key):
            return receipt
    monkeypatch.setattr('tabula_rasa.infrastructure.document_archive.DocumentArchive', Archive)
    def execute(command, *, cwd, env, **kwargs):
        assert cwd == source
        assert command[1:] == ['-m', 'pytest',
            'tests/postgres/test_drive_document_recovery.py::test_real_drive_staging_exact_byte_backup_and_isolated_restore', '-q', '-s']
        assert 'TABULA_RASA_DATABASE_URL' not in env
        assert 'DRIVE_RECOVERY_STAGING_BINDING' not in env and 'DRIVE_RECOVERY_ARCHIVE_KEY' not in env
        assert env['TABULA_RASA_TEST_DATABASE_URL'] == 'postgresql+psycopg://tabula_test@postgres:5432/postgres'
        assert env['TABULA_RASA_ALLOW_DRIVE_RECOVERY_STAGING_DRILL'] == 'approved'
        root = Path(env['DRILL_PRIVATE']) / 'pytest-output' / 'test-synthetic' / 'archives'
        root.mkdir(parents=True)
        (root / 'synthetic.bin').write_bytes(receipt)
        status = dict(status='drive_recovery_drill_passed', entities=2, documents=4,
                      isolated_db_and_drive=True, originals_retained=True)
        return SimpleNamespace(returncode=exit_code, stdout=json.dumps(status), stderr='synthetic-private-error')
    monkeypatch.setattr(runner.subprocess, 'run', execute)
    assert runner.main() == exit_code
    evidence = json.loads((output / 'sanitized-evidence.json').read_text())
    assert evidence['passed'] == (exit_code == 0)
    if exit_code == 0:
        assert evidence['offline_archive_documents_verified'] == 4
    blob = Fernet(key).decrypt((output / 'private-recovery.tar.gz.fernet').read_bytes())
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz') as archive:
        binding = next(member for member in archive.getmembers() if member.name.endswith('/binding.json'))
        assert 'synthetic-client-secret' in archive.extractfile(binding).read().decode()
    logs = capsys.readouterr().out + (output / 'sanitized-evidence.json').read_text()
    assert 'synthetic-client-secret' not in logs and key.decode() not in logs
    assert receipt.decode() not in logs and 'synthetic-private-error' not in logs
