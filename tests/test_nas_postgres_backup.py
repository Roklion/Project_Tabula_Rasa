"""NAS generations, private subprocess boundary, scheduling and recovery health."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import nas_postgres_backup as nas


NOW = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)  # Wednesday 22:00 EDT
SENTINEL = "private-password-and-ledger-content"


def private_file(path, content):
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.fixture
def configured(tmp_path, monkeypatch):
    # tmp_path is the protected, mounted operator storage in this fixture.
    storage = tmp_path / "storage"
    storage.mkdir(mode=0o700)
    marker = "c" * 32
    private_file(storage / ".tabula-nas-storage", marker)
    service = private_file(tmp_path / "pg_service.conf", """[backup]
host=production.example.invalid
port=5432
dbname=ledger
user=backup_role
sslmode=verify-full
sslrootcert=/test/ca.pem
channel_binding=require
connect_timeout=15
""")
    config = {"environment": "production", "storage": str(storage), "storage_marker": marker,
              "source_sha256": hashlib.sha256(b"production.example.invalid:5432/ledger").hexdigest(),
              "service_file": str(service), "passfile": str(private_file(tmp_path / "pgpass", SENTINEL)),
              "recipients_file": str(private_file(tmp_path / "recipients", "age1test-public-recipient")),
              "minimum_free_bytes": 1}
    path = private_file(tmp_path / "config.json", json.dumps(config))
    monkeypatch.setattr(nas, "instant", lambda: NOW)
    return path, config


@pytest.fixture
def clients(monkeypatch):
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["env"]["PGSERVICE"] == "backup"
        assert "PGPASSWORD" not in kwargs["env"]
        assert SENTINEL not in " ".join(args)
        output = b""
        if "--version" in args:
            output = f"{args[0]} (PostgreSQL) 18.6\n".encode()
        elif args[0] == "psql":
            output = json.dumps({"server_version_num": 180006, "schema_version": "0005_bookkeeping_cutover", "tls": True}).encode()
        elif args[0] == "pg_dump":
            Path(args[-1]).write_bytes(b"PGDMP" + SENTINEL.encode())
        elif args[0] == "age" and "--output" in args:
            Path(args[-2]).write_bytes(b"age-encrypted-test-archive")
        return subprocess.CompletedProcess(args, 0, output)
    monkeypatch.setattr(nas.subprocess, "run", run)
    return calls


def load(configured):
    return nas.load_config(configured[0])


def test_complete_generation_is_encrypted_scoped_and_verifiable(configured, clients, monkeypatch, capsys):
    monkeypatch.setenv("PGPASSWORD", SENTINEL)
    monkeypatch.setenv("PGHOST", "wrong-uat")
    monkeypatch.setenv("PGOPTIONS", "unsafe-ambient-options")
    assert nas.main(["run", "--config", str(configured[0])]) == 0
    output = json.loads(capsys.readouterr().out)
    config = load(configured)
    folder = nas.namespace(config) / "complete" / output["generation"]
    assert {p.name for p in folder.iterdir()} == {"database.dump.age", "manifest.json"}
    manifest = nas.verify_generation(config, output["generation"])
    assert manifest["status"] == "complete" and manifest["tls"] is True
    assert manifest["tools"] == {"pg_dump": "18.6", "pg_restore": "18.6", "psql": "18.6"}
    assert SENTINEL not in (folder / "manifest.json").read_text()
    assert nas.health(config, NOW)["status"] == "healthy"
    assert [a[0] for a, _ in clients] == ["pg_dump", "pg_restore", "psql", "psql", "pg_dump", "pg_restore", "age"]
    assert all("PGHOST" not in kw["env"] and "PGOPTIONS" not in kw["env"] for _, kw in clients)
    assert not (nas.namespace(config) / ".lock").exists()


@pytest.mark.parametrize("tool,code", [("pg_dump", "dump"), ("pg_restore", "integrity"), ("age", "encryption")])
def test_failure_quarantines_partial_and_preserves_last_success(configured, clients, monkeypatch, capsys, tool, code):
    config = load(configured)
    initial = nas.backup(config)
    original_run = nas.subprocess.run
    def fail(args, **kwargs):
        if args[0] == tool and "--version" not in args:
            if tool == "pg_dump":
                Path(args[-1]).write_text(SENTINEL)
            raise subprocess.CalledProcessError(1, args, stderr=SENTINEL)
        return original_run(args, **kwargs)
    monkeypatch.setattr(nas.subprocess, "run", fail)
    assert nas.main(["run", "--config", str(configured[0])]) == 1
    text = capsys.readouterr().out
    assert SENTINEL not in text and json.loads(text)["code"] == code
    state = nas.read_state(nas.namespace(config))
    assert state["last_success"] == initial["generation"] and state["result"] == "failed"
    assert len(list((nas.namespace(config) / "complete").iterdir())) == 1
    assert len(list((nas.namespace(config) / "incomplete").iterdir())) == 1
    nas.verify_generation(config, initial["generation"])
    assert nas.health(config, NOW)["status"] == "failed"


def test_tampered_ciphertext_fails_verification(configured, clients):
    config = load(configured)
    result = nas.backup(config)
    folder = nas.namespace(config) / "complete" / result["generation"]
    (folder / "database.dump.age").write_bytes(b"tampered")
    with pytest.raises(nas.BackupError, match="integrity"):
        nas.verify_generation(config, result["generation"])


def test_overlap_never_changes_state_or_attempts_remote_call(configured, clients):
    config = load(configured)
    root = nas.namespace(config)
    root.mkdir(parents=True)
    with nas.guard(root):
        with pytest.raises(nas.BackupError, match="overlap"):
            nas.backup(config)
    assert not clients and not (root / "status.json").exists()


def test_interruption_leaves_running_health_and_no_usable_partial(configured, clients, monkeypatch):
    config = load(configured)
    original_run = nas.subprocess.run
    def interrupt(args, **kwargs):
        if args[0] == "pg_dump" and "--version" not in args:
            raise KeyboardInterrupt
        return original_run(args, **kwargs)
    monkeypatch.setattr(nas.subprocess, "run", interrupt)
    with pytest.raises(KeyboardInterrupt):
        nas.backup(config)
    assert nas.health(config, NOW)["status"] == "running"
    assert not (nas.namespace(config) / "complete").exists()
    # A subsequent scheduler tick cannot retry the interrupted slot.
    assert nas.backup(config, scheduled=True) == {"status": "no_attempt", "health": "running"}


@pytest.mark.parametrize("date,expected", [
    ("2026-03-05T03:00:00+00:00", "2026-03-05T03:00:00+00:00"),
    ("2026-03-09T02:00:00+00:00", "2026-03-09T02:00:00+00:00"),
    ("2026-10-29T02:00:00+00:00", "2026-10-29T02:00:00+00:00"),
    ("2026-11-02T03:00:00+00:00", "2026-11-02T03:00:00+00:00"),
    ("2026-11-02T02:59:00+00:00", "2026-10-29T02:00:00+00:00"),
])
def test_calendar_slots_follow_eastern_dst(date, expected):
    assert nas.stamp(nas.latest_slot(datetime.fromisoformat(date))) == expected


def test_schedule_one_attempt_then_next_slot_and_unlimited_retention(configured, clients, monkeypatch):
    config = load(configured)
    first = nas.backup(config, scheduled=True)
    assert nas.backup(config, scheduled=True)["status"] == "no_attempt"
    monkeypatch.setattr(nas, "instant", lambda: NOW + timedelta(days=4))
    second = nas.backup(config, scheduled=True)
    assert first["generation"] != second["generation"]
    assert len(list((nas.namespace(config) / "complete").iterdir())) == 2
    nas.verify_generation(config, first["generation"])


def test_missed_run_stale_signal_and_bounded_catchup(configured, clients, monkeypatch):
    config = load(configured)
    nas.backup(config, scheduled=True)
    missed = NOW + timedelta(days=4, hours=3)
    assert nas.health(config, missed)["status"] == "stale"
    monkeypatch.setattr(nas, "instant", lambda: missed)
    assert nas.backup(config, scheduled=True)["status"] == "complete"
    too_late = NOW + timedelta(days=8, hours=1)
    monkeypatch.setattr(nas, "instant", lambda: too_late)
    assert nas.backup(config, scheduled=True) == {"status": "no_attempt", "health": "stale"}


def test_production_uat_and_two_databases_do_not_share_archives_or_guards(configured, clients):
    config = load(configured)
    production = nas.backup(config)
    path, original = configured
    def other_config(label, host, database, environment):
        service = private_file(path.parent / f"{label}.service", Path(original["service_file"]).read_text().replace(
            "production.example.invalid", host).replace("dbname=ledger", f"dbname={database}"))
        passfile = private_file(path.parent / f"{label}.pgpass", label + "-private-password")
        selected = {**original, "environment": environment,
                    "source_sha256": hashlib.sha256(f"{host}:5432/{database}".encode()).hexdigest(),
                    "service_file": str(service), "passfile": str(passfile)}
        return nas.load_config(private_file(path.parent / f"{label}.json", json.dumps(selected)))
    uat = other_config("uat", "uat.example.invalid", "ledger", "uat")
    second_db = other_config("other-db", "production.example.invalid", "other", "production")
    with nas.guard(nas.namespace(config)):
        other = nas.backup(uat)
        nas.backup(second_db)
    assert nas.read_state(nas.namespace(config))["last_success"] == production["generation"]
    assert nas.read_state(nas.namespace(uat))["last_success"] == other["generation"]
    with pytest.raises(FileNotFoundError):
        nas.verify_generation(uat, production["generation"])
    observed_passfiles = {kw["env"]["PGPASSFILE"] for _, kw in clients}
    assert observed_passfiles == {str(value["passfile"]) for value in (config, uat, second_db)}


@pytest.mark.parametrize("mutation", ["pooler", "tls", "identity", "password", "defaults", "dbname", "permissions", "marker"])
def test_invalid_or_unsafe_configuration_never_connects(configured, clients, capsys, mutation):
    path, config = configured
    service = Path(config["service_file"])
    text = service.read_text()
    changes = {"pooler": ("production.example", "production-pooler.example"),
               "tls": ("verify-full", "require"), "dbname": ("dbname=ledger", "dbname=postgresql://secret@wrong/db")}
    if mutation in changes:
        service.write_text(text.replace(*changes[mutation]))
    elif mutation == "password":
        service.write_text(text + "password=" + SENTINEL)
    elif mutation == "defaults":
        service.write_text("[DEFAULT]\npassword=" + SENTINEL + "\n" + text)
    elif mutation == "identity":
        config["source_sha256"] = "d" * 64
        path.write_text(json.dumps(config))
    elif mutation == "permissions":
        if os.name != "posix":
            # Windows ACLs are outside the NAS POSIX permission boundary.
            service.unlink()
        else:
            service.chmod(0o644)
    else:
        (Path(config["storage"]) / ".tabula-nas-storage").write_text("wrong-mount")
    assert nas.main(["run", "--config", str(path)]) == 1
    assert SENTINEL not in capsys.readouterr().out and not clients


def test_disk_capacity_blocks_dump_and_health_is_actionable(configured, clients, monkeypatch):
    config = load(configured)
    class Disk:
        free = 0
    monkeypatch.setattr(nas.shutil, "disk_usage", lambda _: Disk())
    with pytest.raises(nas.BackupError, match="storage"):
        nas.backup(config)
    assert not clients
    assert nas.health(config, NOW)["status"] == "capacity"


@pytest.mark.parametrize("failure", ["version", "tls", "schema", "timeout"])
def test_preflight_rejects_incompatible_source_without_exposing_output(configured, clients, monkeypatch, capsys, failure):
    original_run = nas.subprocess.run
    def invalid(args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(args, 30, output=SENTINEL)
        result = original_run(args, **kwargs)
        if failure == "version" and args[0] == "pg_dump":
            result.stdout = b"pg_dump (PostgreSQL) 17.1"
        elif failure in {"tls", "schema"} and args[0] == "psql" and "--version" not in args:
            data = json.loads(result.stdout)
            data["tls" if failure == "tls" else "schema_version"] = False if failure == "tls" else ""
            result.stdout = json.dumps(data).encode()
        return result
    monkeypatch.setattr(nas.subprocess, "run", invalid)
    assert nas.main(["preflight", "--config", str(configured[0])]) == 1
    assert SENTINEL not in capsys.readouterr().out


def test_status_failure_after_publication_preserves_archive(configured, clients, monkeypatch):
    config = load(configured)
    original = nas.write_json
    def fail(path, data):
        if path.name == "status.json" and data["result"] != "running":
            raise OSError(SENTINEL)
        return original(path, data)
    monkeypatch.setattr(nas, "write_json", fail)
    with pytest.raises(OSError):
        nas.backup(config)
    root = nas.namespace(config)
    generation = next((root / "complete").iterdir()).name
    nas.verify_generation(config, generation)
    assert nas.health(config, NOW)["status"] == "running"


def test_missing_config_has_safe_action_without_application_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TABULA_RASA_DATABASE_URL", SENTINEL)
    assert nas.main(["run", "--config", str(tmp_path / "missing.json")]) == 1
    output = capsys.readouterr().out
    assert SENTINEL not in output and json.loads(output)["action"]


def test_failed_scheduled_slot_is_not_retried_automatically(configured, clients, monkeypatch):
    config = load(configured)
    def fail(*args, **kwargs):
        raise nas.BackupError("source")
    monkeypatch.setattr(nas, "source_info", fail)
    with pytest.raises(nas.BackupError, match="source"):
        nas.backup(config, scheduled=True)
    monkeypatch.setattr(nas, "source_info", lambda _: pytest.fail("Failed slot must not reconnect"))
    assert nas.backup(config, scheduled=True) == {"status": "no_attempt", "health": "failed"}


def test_overdue_running_state_alerts_after_grace(configured, clients, monkeypatch, capsys):
    config = load(configured)
    root = nas.namespace(config)
    root.mkdir(parents=True)
    nas.write_json(root / "status.json", {"result": "running", "started_at": nas.stamp(NOW)})
    assert nas.main(["status", "--config", str(configured[0])]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "running"
    monkeypatch.setattr(nas, "instant", lambda: NOW + timedelta(hours=3))
    assert nas.main(["status", "--config", str(configured[0])]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "overdue"
