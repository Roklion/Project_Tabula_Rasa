from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.http.errors import TransportError
from tabula_rasa.http.migrated import MigratedProfileServices
from tabula_rasa.http.composition import open_migrated_runtime
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import RequestContext


def test_migrated_binding_enters_existing_cutover_and_document_composition(monkeypatch):
    services = object()
    factory = Mock(return_value=SimpleNamespace(services=services))
    monkeypatch.setattr("tabula_rasa.composition.create_application", factory)
    database = object()
    secrets = {"bookkeeping_backends": {"profile-alpha": {
        "backend": "postgres", "entity_id": "entity-alpha", "mode": "rehearsal",
    }}}
    binding = MigratedProfileServices(database, entity_profiles={"entity-alpha": "profile-alpha"}, secrets=secrets)
    assert binding(SimpleNamespace(entity_id="entity-alpha")) is services
    factory.assert_called_once_with("profile-alpha", secrets, database=database)
    with pytest.raises(TransportError):
        binding(SimpleNamespace(entity_id="entity-beta"))
    assert factory.call_count == 1


def test_mismatched_server_binding_cannot_return_another_profiles_services(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("tabula_rasa.composition.create_application", factory)
    binding = MigratedProfileServices(object(), entity_profiles={"alpha": "profile-beta"},
        secrets={"bookkeeping_backends": {"profile-beta": {"backend": "postgres", "entity_id": "beta"}}})
    with pytest.raises(TransportError):
        binding(SimpleNamespace(entity_id="alpha"))
    factory.assert_not_called()


def test_synthetic_context_cannot_bind_a_migrated_profile(monkeypatch):
    factory = Mock()
    monkeypatch.setattr("tabula_rasa.composition.create_application", factory)
    binding = MigratedProfileServices(None, entity_profiles={"alpha": "alpha"}, secrets={})
    with pytest.raises(TransportError, match="forbidden"):
        binding(SimpleNamespace(entity_id="alpha", trusted_development=True))
    factory.assert_not_called()


@pytest.mark.parametrize("mapping,backends", [
    ({}, {}),
    ({"alpha": "profile", "beta": "profile"}, {}),
    ({"alpha": ""}, {}),
    ({"alpha": "profile"}, None),
    ({"alpha": "profile"}, {"profile": None}),
    ({"alpha": "profile"}, {"profile": {"backend": "maintenance"}}),
])
def test_invalid_server_bindings_fail_before_provider_composition(monkeypatch, mapping, backends):
    factory = Mock()
    monkeypatch.setattr("tabula_rasa.composition.create_application", factory)
    binding = MigratedProfileServices(None, entity_profiles=mapping, secrets={"bookkeeping_backends": backends})
    with pytest.raises(TransportError):
        binding.validate()
    factory.assert_not_called()


@pytest.mark.parametrize("resolver,fixture", [(None, None), (lambda request: None, "alpha-synthetic")])
def test_migrated_factory_requires_authorization_and_refuses_fixture_option(monkeypatch, resolver, fixture):
    database = Mock()
    monkeypatch.setattr("tabula_rasa.http.composition.Database", database)
    settings = HttpSettings("test", "http://testserver", trusted_entity_id=fixture)
    with pytest.raises(RuntimeError, match="authorization resolver"):
        open_migrated_runtime(settings, resolve_context=resolver, entity_profiles={}, profile_secrets={})
    database.assert_not_called()


@pytest.mark.parametrize("failure", ["binding", "schema", "allocation"])
def test_migrated_startup_disposes_pool_and_does_not_retain_private_errors(monkeypatch, failure):
    database = Mock()
    database.health.return_value = {"connected": True, "revision": "unsupported"}
    allocate = Mock(return_value=database)
    if failure == "allocation":
        allocate.side_effect = ValueError("private synthetic connection")
    monkeypatch.setattr("tabula_rasa.http.composition.Database", allocate)
    monkeypatch.setattr(MigratedProfileServices, "validate", Mock(
        side_effect=ValueError("private synthetic binding") if failure == "binding" else None))
    with pytest.raises(RuntimeError, match="Migrated HTTP runtime startup failed") as caught:
        open_migrated_runtime(HttpSettings("production", "https://owner.example.test"),
            resolve_context=lambda request: None, entity_profiles={"alpha": "alpha"},
            profile_secrets={}, database_settings=object())
    assert caught.value.__context__ is None
    assert "private" not in str(caught.value)
    assert database.dispose.call_count == (0 if failure == "allocation" else 1)


def test_shared_production_factory_validates_all_bindings_and_preserves_request_scopes(monkeypatch):
    from tabula_rasa.infrastructure.postgres.migrations import head_revision

    database = Mock()
    database.health.return_value = {"connected": True, "revision": head_revision()}
    monkeypatch.setattr("tabula_rasa.http.composition.Database", Mock(return_value=database))
    services = {profile: object() for profile in ("alpha", "beta")}
    factory = Mock(side_effect=lambda profile, *args, **kwargs: SimpleNamespace(services=services[profile]))
    monkeypatch.setattr("tabula_rasa.composition.create_application", factory)
    secrets = {"bookkeeping_backends": {profile: {
        "backend": "postgres", "entity_id": profile, "mode": "rehearsal",
    } for profile in services}}
    resolver = Mock()
    runtime = open_migrated_runtime(HttpSettings("production", "https://owner.example.test"),
        resolve_context=resolver, entity_profiles={profile: profile for profile in services},
        profile_secrets=secrets, database_settings=object())
    assert factory.call_count == 2
    assert runtime.resolve_context is resolver and runtime.ready()
    for profile in services:
        context = RequestContext("actor", "org", profile, frozenset({"bookkeeping:read"}), "session", "csrf")
        assert runtime.services(context) is services[profile]
        factory.assert_called_with(profile, secrets, database=database)
    runtime.close()
    database.dispose.assert_called_once()
