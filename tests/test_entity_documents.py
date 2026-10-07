"""Different entity/profile identities preserve the existing provider owner."""

from types import SimpleNamespace

import pytest

from tabula_rasa.application.documents import DocumentValidationError, ReceiptInventory
from tabula_rasa.infrastructure.entity_documents import EntityDocumentStore
from tests.migration_support import document


def test_entity_alias_preserves_profile_owner_for_inventory_metadata_and_bytes_in_two_profiles():
    calls = []
    for profile in ("alpha", "beta"):
        original = document(profile, "same-private-locator")
        def call(method, key, *args, **kwargs):
            calls.append((method, key))
            if method == "inventory":
                return ReceiptInventory((original,), ("unverified",))
            if method == "fetch":
                return b"synthetic bytes"
            return original
        store = SimpleNamespace(scope_key="folder-" + profile,
            inventory=lambda key, **kwargs: call("inventory", key, **kwargs),
            metadata=lambda key, locator: call("metadata", key, locator),
            fetch=lambda key, locator: call("fetch", key, locator),
            upload=lambda key, upload: call("upload", key, upload),
            delete=lambda key, locator: call("delete", key, locator))
        entity_id = "entity-" + profile
        bound = EntityDocumentStore(entity_id, profile, store)
        assert bound.scope_key == "folder-" + profile
        inventory = bound.inventory(entity_id, fresh=True)
        assert inventory.documents[0].profile_key == entity_id
        assert inventory.documents[0].storage_key == original.storage_key
        assert inventory.unverified_storage_keys == ("unverified",)
        assert bound.metadata(entity_id, original.storage_key).profile_key == entity_id
        assert bound.fetch(entity_id, original.storage_key) == b"synthetic bytes"
        assert bound.upload(entity_id, object()).profile_key == entity_id
        bound.delete(entity_id, original.storage_key)
        before = len(calls)
        with pytest.raises(DocumentValidationError, match="different business entity"):
            bound.fetch("entity-foreign", original.storage_key)
        assert len(calls) == before
    assert [key for _, key in calls] == ["alpha"] * 5 + ["beta"] * 5


def test_foreign_provider_response_cannot_be_relabelled_as_the_selected_entity():
    store = SimpleNamespace(scope_key="folder-alpha", inventory=lambda *args, **kwargs: ReceiptInventory((document("beta", "foreign"),)))
    with pytest.raises(DocumentValidationError, match="different business profile"):
        EntityDocumentStore("entity-alpha", "alpha", store).inventory("entity-alpha")
