"""Isolated hosted drill custody; reuse the canonical recovery test and verifier."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

from cryptography.fernet import Fernet


def main():
    if sys.flags.optimize:
        raise RuntimeError('Python optimization must be disabled for recovery validation')
    os.umask(0o077)
    source = Path(os.environ['GITHUB_WORKSPACE']) / 'source'
    output = Path(os.environ['RUNNER_TEMP']) / 'drive-recovery-evidence'
    output.mkdir(mode=0o700, exist_ok=False)
    # Validate encryption custody before loading credentials or making Google calls.
    cipher = Fernet(os.environ['DRIVE_RECOVERY_ARCHIVE_KEY'].encode())
    assert cipher.decrypt(cipher.encrypt(b'custody-check')) == b'custody-check'
    private = Path(tempfile.mkdtemp(prefix='drive-recovery-private-', dir=os.environ['RUNNER_TEMP']))
    assert not any((p / '.git').exists() for p in (private, *private.parents))
    evidence = {'scope': 'isolated_github_hosted_runner', 'passed': False,
        'source_sha': os.environ['SOURCE_SHA'], 'run_id': os.environ['GITHUB_RUN_ID']}
    try:
        binding = json.loads(os.environ['DRIVE_RECOVERY_STAGING_BINDING'])
        assert set(binding) == {'alpha', 'beta'}
        sys.path.insert(0, str(source))
        from tabula_rasa.google_drive import GoogleDriveClient, load_oauth_config
        folders = []
        accounts = set()
        for modes in binding.values():
            assert set(modes) == {'source', 'target'}
            assert modes['source']['profile_key'] == modes['target']['profile_key']
            assert modes['source']['profile_key'].startswith('stage-')
            for config in modes.values():
                assert set(config) == {'profile_key', 'google_drive_oauth', 'google_drive'}
                grant = config['google_drive']
                client = GoogleDriveClient(load_oauth_config(config), grant)
                client.validate_storage_configuration(config['profile_key'])
                about = client._request('GET', 'https://www.googleapis.com/drive/v3/about',
                    params={'fields': 'user(emailAddress)'}).json()
                assert about['user']['emailAddress'] == grant['authorized_email']
                accounts.add(about['user']['emailAddress'])
                folder = grant['receipt_folder']['id']
                assert not client._list(f"trashed=false and '{folder}' in parents", fetch_all=True)
                metadata = client._request('GET', 'https://www.googleapis.com/drive/v3/files/' + folder,
                    params={'fields': 'ownedByMe,shared,capabilities(canAddChildren)'}).json()
                assert metadata['ownedByMe'] and not metadata['shared'] and metadata['capabilities']['canAddChildren']
                folders.append(folder)
        assert len(set(folders)) == 4 and len(accounts) == 1
        binding_path = private / 'binding.json'
        binding_path.write_text(json.dumps(binding))
        # Preserve the test's newly generated grant-envelope key in the encrypted archive.
        (private / 'custody_plugin.py').write_text('''import json
import os
from pathlib import Path
import pytest
@pytest.hookimpl(tryfirst=True)
def pytest_runtest_call(item):
    root = Path(os.environ['DRILL_PRIVATE'])
    assert item.funcargs['tmp_path'].resolve().is_relative_to(root.resolve())
    original = item.module.ConnectionSecrets
    class RetainedSecrets(original):
        def __init__(self, directory, key):
            super().__init__(directory, key)
            (root / 'grant-envelope.key').write_text(key)
    item.module.ConnectionSecrets = RetainedSecrets
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    yield
    if call.excinfo is not None:
        diagnostic = {'phase': call.when, 'exception_type': call.excinfo.typename,
            'frames': [{'file': Path(str(frame.path)).name, 'function': frame.name,
                'line': frame.lineno + 1} for frame in call.excinfo.traceback][-8:]}
        (Path(os.environ['DRILL_PRIVATE']) / 'test-diagnostic.json').write_text(json.dumps(diagnostic))
''')
        env = {k: v for k, v in os.environ.items() if not k.startswith('TABULA_RASA_')
            and k not in {'DRIVE_RECOVERY_STAGING_BINDING', 'DRIVE_RECOVERY_ARCHIVE_KEY', 'PYTHONOPTIMIZE'}}
        env.update(TABULA_RASA_TEST_DATABASE_URL='postgresql+psycopg://tabula_test@postgres:5432/postgres',
            TABULA_RASA_DRIVE_RECOVERY_STAGING_BINDING=str(binding_path),
            TABULA_RASA_ALLOW_DRIVE_RECOVERY_STAGING_DRILL='approved', DRILL_PRIVATE=str(private),
            PYTHONPATH=str(private) + os.pathsep + str(source), PYTEST_PLUGINS='custody_plugin',
            PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
            PYTEST_ADDOPTS='--tb=no --basetemp=' + str(private / 'pytest-output'))
        result = subprocess.run([sys.executable, '-m', 'pytest',
            'tests/postgres/test_drive_document_recovery.py::test_real_drive_staging_exact_byte_backup_and_isolated_restore',
            '-q', '-s'], cwd=source, env=env, capture_output=True, text=True, timeout=480)
        evidence['pytest_exit_code'] = result.returncode
        for line in result.stdout.splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get('status') == 'drive_recovery_drill_passed':
                evidence['result'] = {k: record[k] for k in ('status', 'entities', 'documents',
                    'isolated_db_and_drive', 'originals_retained')}
        evidence['passed'] = result.returncode == 0 and 'result' in evidence
        if evidence['passed']:
            from tabula_rasa.infrastructure.document_archive import DocumentArchive
            paths = {p.resolve() for p in private.rglob('archives') if p.is_dir()}
            assert len(paths) == 1
            verified = 0
            for entity in ('alpha', 'beta'):
                archive = DocumentArchive(next(iter(paths)) / entity, entity)
                assert len(archive.documents) == 2
                for document in archive.documents:
                    data = archive.fetch(entity, document.storage_key)
                    assert hashlib.sha256(data).hexdigest() == document.metadata.sha256
                    assert len(data) == document.metadata.byte_size
                    verified += 1
            evidence['offline_archive_documents_verified'] = verified
    except Exception as error:
        evidence.update(passed=False, exception_type=type(error).__name__)
    finally:
        # No raw logs, binding JSON, keys or receipt bytes enter public artifacts.
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode='w:gz') as archive:
            archive.add(private, arcname='private', recursive=True)
        plaintext = memory.getvalue()
        ciphertext = cipher.encrypt(plaintext)
        assert cipher.decrypt(ciphertext) == plaintext
        (output / 'private-recovery.tar.gz.fernet').write_bytes(ciphertext)
        evidence['encrypted_archive_sha256'] = hashlib.sha256(ciphertext).hexdigest()
        evidence['plaintext_archive_sha256'] = hashlib.sha256(plaintext).hexdigest()
        (output / 'sanitized-evidence.json').write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence['passed'] else 1


if __name__ == '__main__':
    try:
        status = main()
    except Exception as error:
        print(json.dumps({'passed': False, 'exception_type': type(error).__name__, 'private_details_suppressed': True}))
        status = 1
    sys.exit(status)
