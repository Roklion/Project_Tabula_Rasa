import subprocess
import sys

import pytest

from tabula_rasa.infrastructure.postgres.config import DatabaseConfigurationError, DatabaseSettings


def test_absent_configuration_is_optional():
    assert DatabaseSettings.from_environment({}) is None
    with pytest.raises(DatabaseConfigurationError, match="Set TABULA_DATABASE_URL"):
        DatabaseSettings.from_environment({}, required=True)


def test_url_normalization_and_secret_safe_representation():
    settings = DatabaseSettings.from_environment({
        "TABULA_DATABASE_URL": "postgresql://operator:private-password@localhost/dev?sslmode=require",
    })
    assert settings.url.drivername == "postgresql+psycopg"
    assert settings.url.query == {"sslmode": "require"}
    assert "private-password" not in repr(settings)
    assert "operator" not in repr(settings)


@pytest.mark.parametrize("url", [
    "sqlite:///private-secret.db", "postgresql://user:private-secret@host",
    "postgresql://user:private-secret@host:not-a-port/dev",
    "postgresql+psycopg2://user:private-secret@host/dev",
    "postgresql://user:private-secret@host/dev?options=private-secret",
])
def test_invalid_urls_have_safe_errors(url):
    with pytest.raises(DatabaseConfigurationError) as caught:
        DatabaseSettings.from_environment({"TABULA_DATABASE_URL": url})
    assert str(caught.value) == "Invalid PostgreSQL settings."
    assert caught.value.__context__ is None


@pytest.mark.parametrize("key,value", [
    ("TABULA_DATABASE_POOL_SIZE", "0"), ("TABULA_DATABASE_MAX_OVERFLOW", "-1"),
    ("TABULA_DATABASE_CONNECT_TIMEOUT", "61"), ("TABULA_DATABASE_POOL_SIZE", "secret"),
])
def test_bounded_pool_configuration(key, value):
    with pytest.raises(DatabaseConfigurationError):
        DatabaseSettings.from_environment({"TABULA_DATABASE_URL": "postgresql://localhost/dev", key: value})


def test_sheets_composition_does_not_import_database_provider():
    result = subprocess.run([
        sys.executable, "-c", "import sys; import tabula_rasa.composition; "
        "assert 'sqlalchemy' not in sys.modules; assert 'psycopg' not in sys.modules; "
        "assert 'tabula_rasa.infrastructure.postgres.runtime' not in sys.modules",
    ], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
