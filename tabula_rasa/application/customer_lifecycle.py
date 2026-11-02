"""Customer lifecycle policy; destructive execution is deliberately unavailable."""

from datetime import timedelta

from .identity import IdentityError

POLICY_VERSION = 'customer-lifecycle-v1'
RECOVERY_WINDOW = timedelta(days=60)
KINDS = frozenset({'business_closure', 'account_closure', 'privacy_erasure'})
DELETION_BLOCKERS = (
    'legal_policy_unapproved', 'manual_hold_review_required',
    'backup_retention_change_unapproved', 'document_inventory_required',
    'recovery_verification_required', 'exact_target_approval_required',
    'destructive_executor_unavailable',
)


def transition(current, action, version, expected_version):
    """Repeated final commands are harmless; conflicting stale commands stop."""
    target = {'confirm': 'confirmed', 'cancel': 'cancelled'}.get(action)
    if target is None:
        raise IdentityError('validation')
    if current == target:
        return False
    if version != expected_version:
        raise IdentityError('stale')
    if current == 'cancelled' or action == 'confirm' and current != 'pending':
        raise IdentityError('conflict')
    return True
