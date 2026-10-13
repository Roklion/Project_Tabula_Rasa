"""Infrastructure imports and lifecycle live here, never in resource handlers."""

from contextlib import contextmanager
import json
import os
import secrets

from sqlalchemy import text

from tabula_rasa.application.services import ApplicationServices
from tabula_rasa.errors import StorageConflictError, StorageError, StorageValidationError
from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
from tabula_rasa.infrastructure.postgres.config import DatabaseSettings
from tabula_rasa.infrastructure.postgres.hosted import open_alpha_database
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

    def __init__(self, database, resolver, *, service_factory, identity=None):
        self.database = database
        self.resolve_context = resolver
        self.service_factory = service_factory
        self.identity = identity

    def services(self, context) -> ApplicationServices:
        with translate_database_errors():
            return self.service_factory(context)

    def operation(self):
        # Error translation only; repositories own transaction boundaries.
        return translate_database_errors()

    @contextmanager
    def document_upload_operation(self, context, document_id):
        """Reject overlapping creates for one entity/ID across HTTP workers."""
        with translate_database_errors(), self.database.transaction() as connection:
            scope = json.dumps([context.entity_id, document_id])
            acquired = connection.scalar(text(
                'SELECT pg_try_advisory_xact_lock(hashtextextended(:scope,304))'
            ), {'scope': scope})
            if not acquired:
                raise StorageConflictError(code='concurrent_write')
            yield

    def ready(self):
        health = self.database.health()
        return health.get("connected") is True and health.get("revision") == head_revision()

    def close(self):
        try:
            if self.identity is not None:
                self.identity.close()
        finally:
            self.database.dispose()


def open_runtime(settings):
    if settings.trusted_entity_id and settings.trusted_entity_id != "alpha-synthetic":
        raise RuntimeError("Default trusted runtime requires the explicit alpha-synthetic fixture.")
    database = None
    try:
        database = (open_alpha_database(dict(os.environ)) if settings.hosted_alpha
                    else Database(DatabaseSettings.from_environment(required=True)))
        from .alpha_documents import load_alpha_document_store
        document_store = load_alpha_document_store(settings, dict(os.environ))
        if document_store is not None:
            from tabula_rasa.infrastructure.postgres.documents import PostgresReceiptRepository
            PostgresReceiptRepository(database, document_store.entity_id,
                store_kind="google_drive", store_scope_key=document_store.scope_key).validate_binding()
        identity = None
        resolver = (
            TrustedDevelopmentContext(settings.trusted_entity_id, secrets.token_urlsafe(32),
                                      hosted=settings.hosted_alpha,
                                      entity_ids=() if settings.hosted_alpha else ('beta-synthetic',))
            if settings.trusted_entity_id else DenyContext()
        )
        if settings.access_mode == "named_user":
            from tabula_rasa.infrastructure.oidc import OidcProvider, OidcSettings
            from tabula_rasa.infrastructure.postgres.sessions import PostgresSessionRepository
            from .identity import NamedIdentity
            oidc = OidcSettings.from_environment(settings, dict(os.environ))
            sessions = PostgresSessionRepository(database, settings.environment, oidc.configuration_hash)
            sessions.configure()
            identity = NamedIdentity(settings, sessions, OidcProvider(oidc))
            resolver = identity
        def services(context):
            if document_store is None:
                return create_postgres_services(database, context.entity_id)
            if context.entity_id != document_store.entity_id or not context.trusted_development:
                raise StorageValidationError(code="forbidden")
            return create_postgres_services(database, context.entity_id,
                document_store=document_store, document_store_kind="google_drive")

        runtime = PostgresRuntime(database, resolver, service_factory=services, identity=identity)
        if settings.trusted_entity_id:
            # Only explicit seed tooling creates synthetic entities.
            for context in resolver.contexts:
                runtime.services(context)
        return runtime
    except BaseException as error:
        if database is not None:
            database.dispose()
        if not isinstance(error, Exception):
            raise
        # Startup failures must not retain raw configuration/provider text.
    raise RuntimeError("HTTP runtime startup failed. Check configuration and dependency health.")


def open_migrated_runtime(settings, *, resolve_context, entity_profiles, profile_secrets, database_settings=None):
    """Bind the shared application to accepted profiles, with normal authorization.

    The deployment supplies its existing authenticated context resolver and
    trusted configuration. Cutover policy never selects an identity resolver.
    This factory neither activates authority nor enables the synthetic resolver.
    """
    if settings.trusted_entity_id or not callable(resolve_context):
        raise RuntimeError("Migrated runtime requires an explicit authorization resolver without fixture context.")
    from .identity import NamedIdentity
    if isinstance(resolve_context, NamedIdentity) and settings.access_mode != "named_user":
        raise RuntimeError("Named identity requires explicit named-user access mode.")
    from .migrated import MigratedProfileServices

    database = None
    try:
        database = Database(database_settings or DatabaseSettings.from_environment(required=True))
        services = MigratedProfileServices(database, entity_profiles=entity_profiles, secrets=profile_secrets)
        services.validate()
        runtime = PostgresRuntime(database, resolve_context, service_factory=services,
                                  identity=resolve_context if isinstance(resolve_context, NamedIdentity) else None)
        if not runtime.ready():
            raise RuntimeError("The migrated database is not ready.")
        return runtime
    except Exception:
        if database is not None:
            database.dispose()
    # Raise outside the handler: raw provider/configuration exceptions can
    # contain credentials or ledger values and must not survive as context.
    raise RuntimeError("Migrated HTTP runtime startup failed. Check authority, bindings and dependency health.")
