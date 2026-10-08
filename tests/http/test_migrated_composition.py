from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tabula_rasa.http.errors import TransportError
from tabula_rasa.http.migrated import MigratedProfileServices


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
