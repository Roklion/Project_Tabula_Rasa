"""Trusted migrated-profile binding; never inferred from browser input."""

from collections.abc import Mapping

from .errors import TransportError


class MigratedProfileServices:
    """Inject into PostgresRuntime for operator-configured migrated entities.

    Cutover controls enforce authority. Named operation also requires approved
    entity ownership and scoped document grants; internal legacy composition keeps
    its profile-owned adapter. All profile bindings are server-only inputs.
    """

    def __init__(self, database, *, entity_profiles: Mapping[str, str], secrets: Mapping[str, object], connections=None):
        if not isinstance(entity_profiles, Mapping) or not isinstance(secrets, Mapping):
            raise TransportError("forbidden")
        self.database = database
        self.entity_profiles = dict(entity_profiles)
        self.secrets = secrets
        self.connections = connections

    def __call__(self, context):
        if getattr(context, "trusted_development", False):
            raise TransportError("forbidden")
        if self.connections is not None:
            return self._named_services(context)
        return self._services(context.entity_id)

    def validate(self):
        """Check every operator binding before exposing the shared runtime."""
        if (not self.entity_profiles
                or any(not isinstance(profile, str) or not profile.strip() for profile in self.entity_profiles.values())
                or len(set(self.entity_profiles.values())) != len(self.entity_profiles)):
            raise TransportError("forbidden")
        for entity_id in self.entity_profiles:
            if self.connections is None:
                self._services(entity_id)
            else:
                organization_id, profile, scope = self._named_binding(entity_id)
                self.connections.validate_migrated_binding(organization_id=organization_id,
                    entity_id=entity_id, profile_key=profile, scope_key=scope)

    def _named_binding(self, entity_id, organization_id=None):
        from sqlalchemy import text
        from tabula_rasa.application.identity import IdentityError
        from tabula_rasa.infrastructure.postgres.control_plane import identity_operation
        from tabula_rasa.infrastructure.postgres.cutover import PostgresCutoverController
        from tabula_rasa.migration.model import Binding
        from tabula_rasa.business_profiles import select_profile_secrets
        profile, configured = self._configuration(entity_id)
        with identity_operation(self.database, read_only=True) as connection:
            row = connection.execute(text('SELECT * FROM legacy_entity_claims WHERE entity_id=:entity'),
                                     {'entity': entity_id}).mappings().first()
            if (row is None or row['profile_key'] != profile
                    or organization_id is not None and row['organization_id'] != organization_id):
                raise IdentityError('forbidden')
        selected = select_profile_secrets(self.secrets, profile)
        binding = Binding(profile, str(selected['spreadsheet_id']).strip(), entity_id)
        drive = selected.get('google_drive')
        folder = drive.get('receipt_folder') if isinstance(drive, Mapping) else None
        scope = str(folder.get('id', '')) if isinstance(folder, Mapping) else ''
        PostgresCutoverController(self.database).require_postgres(binding, mode=configured['mode'], document_scope=scope)
        return row['organization_id'], profile, scope

    def _named_services(self, context):
        from tabula_rasa.infrastructure.postgres.composition import create_postgres_services
        self._named_binding(context.entity_id, context.organization_id)
        store = self.connections.document_store(context)
        return create_postgres_services(self.database, context.entity_id,
            document_store=store, document_store_kind=store.store_kind if store is not None else None)

    def _services(self, entity_id):
        profile, _ = self._configuration(entity_id)
        # Legacy internal composition retains its profile-owned grant boundary.
        from tabula_rasa.composition import create_application
        return create_application(profile, self.secrets, database=self.database).services

    def _configuration(self, entity_id):
        profile = self.entity_profiles.get(entity_id)
        if not isinstance(profile, str) or not profile.strip() or not isinstance(entity_id, str) or not entity_id.strip():
            raise TransportError("forbidden")
        backends = self.secrets.get("bookkeeping_backends", {})
        configured = backends.get(profile) if isinstance(backends, Mapping) else None
        if (not isinstance(configured, Mapping) or configured.get("backend") != "postgres"
                or configured.get("entity_id") != entity_id):
            raise TransportError("forbidden")
        return profile, configured
