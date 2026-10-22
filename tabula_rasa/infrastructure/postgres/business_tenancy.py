"""Read-only control-plane inventory for operator-reviewed tenancy rollout."""

from sqlalchemy import text

from .control_plane import identity_operation
from .identity import database_identity
from .migrations import current_revision


def tenancy_inventory(database):
    """Return counts only; never names, recipients, credentials or ledger data.

    Empty containers are retained for explicit legacy claims. Inactive bindings
    count as occupied: changing state must never recycle an ownership boundary.
    This is a preflight, not a conversion or authorization to run a migration.
    """
    with identity_operation(database, read_only=True) as connection:
        counts = {}
        for table in ('organizations', 'organization_entities', 'memberships',
                      'workspace_invitations', 'workspace_bootstraps', 'legacy_entity_claims',
                      'external_connections', 'identity_sessions', 'support_grants'):
            counts[table] = connection.scalar(text(f'SELECT count(*) FROM {table}'))
        ambiguous = connection.scalar(text('''SELECT count(*) FROM (
            SELECT organization_id FROM organization_entities
            GROUP BY organization_id HAVING count(*)>1) conflicts'''))
        empty = connection.scalar(text('''SELECT count(*) FROM organizations o
            WHERE NOT EXISTS (SELECT 1 FROM organization_entities e WHERE e.organization_id=o.id)'''))
        return {'database_sha256': database_identity(database), 'revision': current_revision(connection),
                'counts': counts, 'multi_business_organizations': ambiguous,
                'empty_organizations': empty, 'ready_for_constraint': ambiguous == 0}
