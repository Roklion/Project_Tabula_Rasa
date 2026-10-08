import subprocess
import sys

import pytest

from tabula_rasa.infrastructure.postgres import config
from tabula_rasa.infrastructure.postgres.config import DatabaseConfigurationError, DatabaseSettings


def test_absent_configuration_is_optional():
    assert DatabaseSettings.from_environment({}) is None
    with pytest.raises(DatabaseConfigurationError, match="Set TABULA_RASA_DATABASE_URL"):
        DatabaseSettings.from_environment({}, required=True)


def test_url_normalization_and_secret_safe_representation():
    settings = DatabaseSettings.from_environment({
        "TABULA_RASA_DATABASE_URL": "postgresql://operator:private-password@localhost/dev?sslmode=require",
    })
    assert settings.url.drivername == "postgresql+psycopg"
    assert settings.url.query == {"sslmode": "require"}
    assert "private-password" not in repr(settings)
    assert "operator" not in repr(settings)


@pytest.mark.parametrize("mode", ["disable", "prefer", "require"])
def test_channel_binding_security_option_is_preserved(mode):
    settings = DatabaseSettings.from_environment({
        "TABULA_RASA_DATABASE_URL": f"postgresql://operator:private-password@localhost/dev?sslmode=require&channel_binding={mode}",
    })
    assert settings.url.query == {"sslmode": "require", "channel_binding": mode}
    assert "private-password" not in repr(settings)


@pytest.mark.parametrize("url", [
    "sqlite:///private-secret.db", "postgresql://user:private-secret@host",
    "postgresql://user:private-secret@host:not-a-port/dev",
    "postgresql+psycopg2://user:private-secret@host/dev",
    "postgresql://user:private-secret@host/dev?options=private-secret",
    "postgresql://user:private-secret@host/dev?channel_binding=private-secret",
    "postgresql://user:private-secret@host/dev?channel_binding=require&channel_binding=disable",
    "postgresql malformed user:private-secret@host/dev",
])
def test_invalid_urls_have_safe_errors(url):
    with pytest.raises(DatabaseConfigurationError) as caught:
        DatabaseSettings.from_environment({"TABULA_RASA_DATABASE_URL": url})
    assert str(caught.value) == "Invalid PostgreSQL settings."
    assert caught.value.__context__ is None


@pytest.mark.parametrize("key,value", [
    ("TABULA_RASA_DATABASE_POOL_SIZE", "0"), ("TABULA_RASA_DATABASE_MAX_OVERFLOW", "-1"),
    ("TABULA_RASA_DATABASE_CONNECT_TIMEOUT", "61"), ("TABULA_RASA_DATABASE_POOL_SIZE", "secret"),
])
def test_bounded_pool_configuration(key, value):
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_environment({"TABULA_RASA_DATABASE_URL": "postgresql://localhost/dev", key: value})


def test_sheets_composition_does_not_import_database_provider():
    result = subprocess.run([
        sys.executable, "-c", "import sys; import tabula_rasa.composition; "
        "assert 'sqlalchemy' not in sys.modules; assert 'psycopg' not in sys.modules; "
        "assert 'tabula_rasa.infrastructure.postgres.runtime' not in sys.modules",
    ], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_local_file_loads_from_repository_path_without_exporting_secrets(tmp_path, monkeypatch):
    local_path = tmp_path / ".env.local"
    local_path.write_text(
        'TABULA_RASA_DATABASE_URL="postgresql://operator:p${UNCHANGED}@localhost/uat?sslmode=require"\n'
        'TABULA_RASA_DATABASE_POOL_SIZE=2\n'
        'TABULA_RASA_TEST_DATABASE_URL=postgresql://localhost/never_use_this\n',
        encoding="utf-8-sig",
    )
    monkeypatch.setattr(config, "_LOCAL_ENV_PATH", local_path)
    for key in ("TABULA_RASA_DATABASE_URL", "TABULA_RASA_DATABASE_POOL_SIZE", "TABULA_RASA_TEST_DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("UNCHANGED", "must-not-expand")
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)
    settings = DatabaseSettings.from_environment(required=True)
    assert settings.url.database == "uat"
    assert settings.url.password == "p${UNCHANGED}"
    assert settings.pool_size == 2
    assert "TABULA_RASA_DATABASE_URL" not in config.os.environ
    assert "TABULA_RASA_TEST_DATABASE_URL" not in config.os.environ
    assert "operator" not in repr(settings)


def test_environment_overrides_local_file_including_empty_url(tmp_path, monkeypatch):
    local_path = tmp_path / ".env.local"
    local_path.write_text("TABULA_RASA_DATABASE_URL=postgresql://localhost/uat\n")
    monkeypatch.setattr(config, "_LOCAL_ENV_PATH", local_path)
    monkeypatch.setenv("TABULA_RASA_DATABASE_URL", "postgresql://localhost/deployment")
    assert DatabaseSettings.from_environment(required=True).url.database == "deployment"
    monkeypatch.setenv("TABULA_RASA_DATABASE_URL", "")
    assert DatabaseSettings.from_environment() is None
    with pytest.raises(DatabaseConfigurationError, match="Set TABULA_RASA_DATABASE_URL"):
        DatabaseSettings.from_environment(required=True)


def test_explicit_mapping_bypasses_invalid_local_file(tmp_path, monkeypatch):
    local_path = tmp_path / ".env.local"
    local_path.write_bytes(b"\xffinvalid-private-value")
    monkeypatch.setattr(config, "_LOCAL_ENV_PATH", local_path)
    assert DatabaseSettings.from_environment({}) is None
    settings = DatabaseSettings.from_environment({"TABULA_RASA_DATABASE_URL": "postgresql://localhost/test"})
    assert settings.url.database == "test"
    with pytest.raises(DatabaseConfigurationError) as caught:
        DatabaseSettings.from_environment()
    assert str(caught.value) == "Cannot read local database configuration."
    assert caught.value.__context__ is None


def test_missing_local_file_keeps_environment_only_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_LOCAL_ENV_PATH", tmp_path / ".env.local")
    monkeypatch.delenv("TABULA_RASA_DATABASE_URL", raising=False)
    assert DatabaseSettings.from_environment() is None
    monkeypatch.setenv("TABULA_RASA_DATABASE_URL", "postgresql://localhost/deployment")
    assert DatabaseSettings.from_environment(required=True).url.database == "deployment"
