"""Trusted migrated-profile binding; never inferred from browser input."""

from collections.abc import Mapping

from .errors import TransportError


class MigratedProfileServices:
    """Inject into PostgresRuntime for operator-configured migrated entities.

    #258's create_application owns authority/environment/document checks.
    Configurations and entity->profile bindings are server-only inputs.
    """

    def __init__(self, database, *, entity_profiles: Mapping[str, str], secrets: Mapping[str, object]):
        self.database = database
        self.entity_profiles = dict(entity_profiles)
        self.secrets = secrets

    def __call__(self, context):
        profile = self.entity_profiles.get(context.entity_id)
        configured = self.secrets.get("bookkeeping_backends", {}).get(profile, {})
        if (profile is None or configured.get("backend") != "postgres"
                or configured.get("entity_id") != context.entity_id):
            raise TransportError("forbidden")
        # Lazy import: schema and synthetic API runtime do not load legacy
        # provider dependencies. Operator binding uses the existing owner.
        from tabula_rasa.composition import create_application
        return create_application(profile, self.secrets, database=self.database).services
