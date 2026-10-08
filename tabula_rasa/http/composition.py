"""Infrastructure imports and lifecycle live here, never in resource handlers."""

from contextlib import contextmanager
import secrets

from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.migrations import head_revision
from tabula_rasa.infrastructure.postgres.runtime import Database, DatabaseError

from .context import DenyContext, TrustedDevelopmentContext


@contextmanager
def translate_database_errors():
    try:
        yield
    except DatabaseError as error:
        code = error.code
    else:
        return
    if code in {"duplicate", "concurrent_write"}:
        raise StorageConflictError(code=code) from None
    if code in {"reference", "invariant", "required"}:
        raise StorageValidationError(code=code) from None
    raise StorageError(code="unavailable") from None


class PostgresRuntime:
    """One pool; compose a fresh service graph after resolving each request."""

    def __init__(self, database, resolver, *, service_factory):
        self.database = database
        self.resolve_context = resolver
        self.service_factory = service_factory

    def services(self, context) -> ApplicationServices:
        with translate_database_errors():
            return self.service_factory(context)

    def operation(self):
        # Error translation only; repositories own transaction boundaries.
        return translate_database_errors()

    def ready(self):
        health = self.database.health()
        return health.get("connected") is True and health.get("revision") == head_revision()

    def close(self):
        self.database.dispose()


def open_runtime(settings):
    if settings.trusted_entity_id and settings.trusted_entity_id != "alpha-synthetic":
        raise RuntimeError("Default trusted runtime requires the explicit alpha-synthetic fixture.")
    database = Database(DatabaseSettings.from_environment(required=True))
    try:
        resolver = (
            TrustedDevelopmentContext(settings.trusted_entity_id, secrets.token_urlsafe(32))
            if settings.trusted_entity_id else DenyContext()
        )
        runtime = PostgresRuntime(database, resolver, service_factory=
            lambda context: create_postgres_services(database, context.entity_id))
        if settings.trusted_entity_id:
            # Only explicit seed tooling creates synthetic entities.
            runtime.services(resolver.context)
        return runtime
    except BaseException:
        database.dispose()
        # Startup failures must not retain raw configuration/provider text.
        raise RuntimeError("HTTP runtime startup failed. Check configuration and dependency health.") from None


def open_migrated_runtime(settings, *, resolve_context, entity_profiles, profile_secrets, database_settings=None):
    """Bind the shared application to accepted profiles, with normal authorization.

    The deployment supplies its existing authenticated context resolver and
    trusted configuration. Cutover policy never selects an identity resolver.
    This factory neither activates authority nor enables the synthetic resolver.
    """
    if settings.trusted_entity_id or not callable(resolve_context):
        raise RuntimeError("Migrated runtime requires an explicit authorization resolver without fixture context.")
    from .migrated import MigratedProfileServices

    database = None
    try:
        database = Database(database_settings or DatabaseSettings.from_environment(required=True))
        services = MigratedProfileServices(database, entity_profiles=entity_profiles, secrets=profile_secrets)
        services.validate()
        runtime = PostgresRuntime(database, resolve_context, service_factory=services)
        if not runtime.ready():
            raise RuntimeError("The migrated database is not ready.")
        return runtime
    except Exception:
        if database is not None:
            database.dispose()
    # Raise outside the handler: raw provider/configuration exceptions can
    # contain credentials or ledger values and must not survive as context.
    raise RuntimeError("Migrated HTTP runtime startup failed. Check authority, bindings and dependency health.")
