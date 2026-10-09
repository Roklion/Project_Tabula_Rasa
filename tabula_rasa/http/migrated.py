"""Trusted migrated-profile binding; never inferred from browser input."""

from collections.abc import Mapping

from .errors import TransportError


class MigratedProfileServices:
    """Inject into PostgresRuntime for operator-configured migrated entities.

    #258's create_application owns authority/environment/document checks.
    Configurations and entity->profile bindings are server-only inputs.
    """

    def __init__(self, database, *, entity_profiles: Mapping[str, str], secrets: Mapping[str, object]):
        if not isinstance(entity_profiles, Mapping) or not isinstance(secrets, Mapping):
            raise TransportError("forbidden")
        self.database = database
        self.entity_profiles = dict(entity_profiles)
        self.secrets = secrets

    def __call__(self, context):
        if getattr(context, "trusted_development", False):
            raise TransportError("forbidden")
        return self._services(context.entity_id)

    def validate(self):
        """Check every operator binding before exposing the shared runtime."""
        if (not self.entity_profiles
                or any(not isinstance(profile, str) or not profile.strip() for profile in self.entity_profiles.values())
                or len(set(self.entity_profiles.values())) != len(self.entity_profiles)):
            raise TransportError("forbidden")
        for entity_id in self.entity_profiles:
            self._services(entity_id)

    def _services(self, entity_id):
        profile = self.entity_profiles.get(entity_id)
        if not isinstance(profile, str) or not profile.strip() or not isinstance(entity_id, str) or not entity_id.strip():
            raise TransportError("forbidden")
        backends = self.secrets.get("bookkeeping_backends", {})
        configured = backends.get(profile) if isinstance(backends, Mapping) else None
        if (not isinstance(configured, Mapping) or configured.get("backend") != "postgres"
                or configured.get("entity_id") != entity_id):
            raise TransportError("forbidden")
        # Lazy import: schema and synthetic API runtime do not load legacy
        # provider dependencies. Operator binding uses the existing owner.
        from tabula_rasa.composition import create_application
        return create_application(profile, self.secrets, database=self.database).services
