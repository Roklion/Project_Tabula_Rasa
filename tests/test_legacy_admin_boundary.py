import pytest
from tabula_rasa.legacy_admin import legacy_admin_boundary, legacy_admin_unlocked, password_binding

ENV = {'TABULA_LOCAL_PROFILE_ADMIN': '1'}
OPERATOR = {'authenticated': True, 'local_profile_admin_unlocked': True,
            'local_profile_admin_password_binding': password_binding('synthetic-hash')}


@pytest.mark.parametrize('address', ['0.0.0.0', '::', '192.0.2.1', '', 'public.example.test'])
def test_nonloopback_admin_denied_even_with_old_unlock(address):
    assert not legacy_admin_boundary(address, OPERATOR, ENV)
    assert not legacy_admin_unlocked(address, OPERATOR, 'synthetic-hash', ENV)


def test_commercial_memberships_and_misbound_admin_unlock_do_not_grant_local_authority():
    commercial = {'actor_id': 'user', 'organization_id': 'org', 'capabilities': ['connections:manage'],
                  'local_profile_admin_unlocked': True}
    assert not legacy_admin_boundary('127.0.0.1', commercial, ENV)
    assert not legacy_admin_unlocked('127.0.0.1', commercial, 'synthetic-hash', ENV)
    assert not legacy_admin_unlocked('127.0.0.1', {'authenticated': True, 'local_profile_admin_unlocked': True},
                                    'synthetic-hash', ENV)
    assert legacy_admin_unlocked('127.0.0.1', OPERATOR, 'synthetic-hash', ENV)
    assert not legacy_admin_unlocked('127.0.0.1', OPERATOR, 'rotated-hash', ENV)
    assert not legacy_admin_unlocked('127.0.0.1', OPERATOR, 'synthetic-hash', {})


def test_renderer_refuses_remote_or_commercial_context_before_profile_reads(monkeypatch):
    from unittest.mock import Mock
    from tabula_rasa import local_profile_admin as admin
    monkeypatch.setenv('TABULA_LOCAL_PROFILE_ADMIN', '1')
    monkeypatch.setattr(admin.st, 'error', Mock())
    monkeypatch.setattr(admin.st, 'stop', Mock())
    load = Mock(side_effect=AssertionError('No configuration reads before local operator authorization'))
    monkeypatch.setattr(admin, 'load_local_profiles', load)
    for address, state in [('0.0.0.0', OPERATOR),
                           ('127.0.0.1', {'actor_id': 'owner', 'local_profile_admin_unlocked': True})]:
        monkeypatch.setattr(admin.st, 'get_option', lambda _: address)
        monkeypatch.setattr(admin.st, 'session_state', state)
        admin.render_local_profile_admin({'app_password_hash': 'synthetic-hash'}, {})
    load.assert_not_called()
