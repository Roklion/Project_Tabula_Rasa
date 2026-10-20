"""Recovery tooling never falls back to an application secret or prints data."""

import json

import pytest

from scripts import verify_postgres_recovery as command
from tabula_rasa.bookkeeping_export.files import write_artifact
from tabula_rasa.bookkeeping_export.format import build_artifact
from tests.test_bookkeeping_export import empty_snapshot


def arguments(path, *, later=None):
    return ["verify", "--entity", "alpha", "--expected", str(path),
            "--source-database-sha256", "a" * 64, "--target-database-sha256", "b" * 64,
            *(["--later", str(later)] if later else [])]


def test_missing_recovery_url_never_uses_application_or_local_settings(monkeypatch, capsys):
    monkeypatch.delenv("TABULA_RASA_RECOVERY_DATABASE_URL", raising=False)
    monkeypatch.setenv("TABULA_RASA_DATABASE_URL", "postgresql://private-secret@production/live")
    monkeypatch.setattr(command, "Database", lambda settings: pytest.fail("Pool must not be created"))
    assert command.main(["inspect"]) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "unavailable"}


def test_private_artifact_is_validated_before_pool_creation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TABULA_RASA_RECOVERY_DATABASE_URL", "postgresql://test@127.0.0.1/restored")
    path = tmp_path / "private.json"
    path.write_text('{"private-secret":', encoding="utf-8")
    monkeypatch.setattr(command, "Database", lambda settings: pytest.fail("Pool must not be created"))
    assert command.main(arguments(path)) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "format"}


@pytest.mark.parametrize("phase", ["connect", "verify", "dispose"])
def test_failures_emit_only_fixed_codes(tmp_path, monkeypatch, capsys, phase):
    monkeypatch.setenv("TABULA_RASA_RECOVERY_DATABASE_URL", "postgresql://test@127.0.0.1/restored")
    path = tmp_path / "expected.json"
    write_artifact(path, build_artifact(empty_snapshot()))
    disposed = []
    class Pool:
        def __init__(self, settings):
            if phase == "connect":
                raise RuntimeError("private-credential-and-ledger-sentinel")
        def dispose(self):
            disposed.append(True)
            if phase == "dispose":
                raise RuntimeError("private-credential-and-ledger-sentinel")
    def verify(*args, **kwargs):
        if phase == "verify":
            raise RuntimeError("private-credential-and-ledger-sentinel")
        return {"status": "matched"}
    monkeypatch.setattr(command, "Database", Pool)
    monkeypatch.setattr(command, "verify_recovery", verify)
    assert command.main(arguments(path)) == 1
    assert json.loads(capsys.readouterr().out) == {"status": "failed", "code": "unavailable"}
    assert disposed == ([] if phase == "connect" else [True])


def test_success_passes_selected_artifacts_and_recovery_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TABULA_RASA_RECOVERY_DATABASE_URL", "postgresql://test@127.0.0.1/restored")
    monkeypatch.setenv("TABULA_RASA_DATABASE_URL", "postgresql://secret@production/live")
    path = tmp_path / "expected.json"
    later = tmp_path / "later.json"
    artifact = build_artifact(empty_snapshot())
    write_artifact(path, artifact)
    write_artifact(later, artifact)
    disposed = []
    class Pool:
        def __init__(self, settings):
            assert settings.url.database == "restored"
        def dispose(self):
            disposed.append(True)
    def verify(database, entity, expected, **kwargs):
        assert entity == "alpha" and expected == artifact and kwargs["later"] == artifact
        assert kwargs["source_database_sha256"] == "a" * 64 and kwargs["target_database_sha256"] == "b" * 64
        return {"status": "matched", "scope": "entity_bookkeeping"}
    monkeypatch.setattr(command, "Database", Pool)
    monkeypatch.setattr(command, "verify_recovery", verify)
    assert command.main(arguments(path, later=later)) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "matched", "scope": "entity_bookkeeping"}
    assert disposed == [True]


def test_inspection_is_read_only_and_disposes_pool(monkeypatch, capsys):
    monkeypatch.setenv("TABULA_RASA_RECOVERY_DATABASE_URL", "postgresql://test@127.0.0.1/restored")
    disposed = []
    class Pool:
        def __init__(self, settings):
            pass
        def health(self):
            return {"connected": True, "revision": "0005_bookkeeping_cutover"}
        def dispose(self):
            disposed.append(True)
    monkeypatch.setattr(command, "Database", Pool)
    monkeypatch.setattr(command, "database_identity", lambda pool: "b" * 64)
    assert command.main(["inspect"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "connected": True, "revision": "0005_bookkeeping_cutover", "database_sha256": "b" * 64,
    }
    assert disposed == [True]


def test_audit_capture_is_private_no_clobber_and_prints_no_manifest(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TABULA_RASA_RECOVERY_DATABASE_URL', 'postgresql://test@127.0.0.1/synthetic')
    output = tmp_path / 'audit.json'
    class Pool:
        def __init__(self, settings):
            assert settings.url.database == 'synthetic'
        def dispose(self):
            pass
    def capture(database, entity, *, capabilities):
        assert entity == 'alpha' and capabilities == frozenset({'platform:operate','audit:inspect'})
        return {'private-sentinel': 'only-in-private-file'}
    monkeypatch.setattr(command, 'Database', Pool)
    monkeypatch.setattr(command, 'capture_audit_recovery', capture)
    args = ['audit-capture','--entity','alpha','--output',str(output)]
    assert command.main(args) == 0
    assert 'private-sentinel' not in capsys.readouterr().out
    assert json.loads(output.read_text()) == {'private-sentinel': 'only-in-private-file'}
    assert command.main(args) == 1
    assert json.loads(capsys.readouterr().out)['code'] == 'output_exists'
    assert 'only-in-private-file' in output.read_text()


def test_audit_invalid_manifest_is_rejected_before_pool_creation(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('TABULA_RASA_RECOVERY_DATABASE_URL', 'postgresql://test@127.0.0.1/synthetic')
    path = tmp_path / 'audit.json'
    path.write_text('{"private-sentinel":true}')
    monkeypatch.setattr(command, 'Database', lambda settings: pytest.fail('Invalid oracle must not create pool'))
    args = arguments(path)
    args[0] = 'audit-verify'
    assert command.main(args) == 1
    assert json.loads(capsys.readouterr().out) == {'status':'failed','code':'audit_manifest_invalid'}
