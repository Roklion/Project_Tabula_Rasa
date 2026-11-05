"""Opaque endpoint identity shared by cutover and hosted deployment binding."""

from tabula_rasa.migration.model import digest


def database_identity(database):
    """Passwords, users and query options never participate."""
    return database_url_identity(database.engine.url)


def database_url_identity(url):
    return digest([url.host, url.port or 5432, url.database])
