"""Identity DTO capabilities follow the accepted #310 administration contract."""

from tabula_rasa.application.identity import capabilities


def test_owner_only_administration_and_recovery_capabilities():
    owner_only = {
        'entity:manage', 'organization:manage', 'connections:manage',
        'ownership:manage', 'backup:create', 'backup:download',
        'restore:execute', 'migration:execute', 'recovery:authorize', 'business:admin',
    }
    assert owner_only <= capabilities('owner')
    for role in ('admin', 'editor', 'accountant', 'read_only', 'unknown'):
        assert not owner_only & capabilities(role)
    assert 'members:manage' in capabilities('admin')
    assert {'bookkeeping:read', 'bookkeeping:write', 'bookkeeping:import',
            'bookkeeping:export'} <= capabilities('admin')
