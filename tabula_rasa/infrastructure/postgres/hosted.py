"""Explicit Neon target binding for hosted deployment processes."""

import re

from .config import DatabaseSettings
from .identity import database_identity
from .runtime import Database


def open_alpha_database(environ):
    if environ.get("TABULA_RASA_ENVIRONMENT") not in {"development", "staging"}:
        raise ValueError("Only synthetic development/staging targets are supported.")
    return open_bound_neon_database(environ)


def open_bound_neon_database(environ):
    expected = environ.get("TABULA_RASA_DEPLOY_DATABASE_SHA256", "")
    if not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError("Explicit deployment database binding is required.")
    database = Database(direct_neon_settings(environ))
    if database_identity(database) != expected:
        database.dispose()
        raise ValueError("Deployment database binding does not match.")
    return database


def direct_neon_settings(environ):
    settings = DatabaseSettings.from_environment(environ, required=True)
    if (not (settings.url.host or "").endswith(".neon.tech")
            or "-pooler" in settings.url.host or settings.url.query.get("sslmode") != "require"):
        raise ValueError("Hosted deployment requires direct Neon TLS connectivity.")
    return settings
