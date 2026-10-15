"""Legacy local operator authority remains independent of tenant membership."""
import hashlib

from tabula_rasa.local_profile_store import local_profile_admin_available


def password_binding(encoded_hash):
    return hashlib.sha256(str(encoded_hash).encode()).hexdigest() if encoded_hash else ''


def legacy_admin_boundary(server_address, state, environment=None):
    return (local_profile_admin_available(server_address, environment)
            and state.get('authenticated') is True)


def legacy_admin_unlocked(server_address, state, encoded_hash, environment=None):
    return (legacy_admin_boundary(server_address, state, environment)
            and bool(encoded_hash) and state.get('local_profile_admin_unlocked') is True
            and state.get('local_profile_admin_password_binding') == password_binding(encoded_hash))
