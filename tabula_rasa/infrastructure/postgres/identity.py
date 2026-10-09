"""Opaque endpoint identity shared by cutover and hosted deployment binding."""

from tabula_rasa.migration.model import digest


def database_identity(database):
    """Passwords, users and query options never participate."""
    url = database.engine.url
    return digest([url.host, url.port or 5432, url.database])
