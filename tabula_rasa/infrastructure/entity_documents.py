"""Bind canonical entity calls to an existing profile-owned document store."""

from dataclasses import replace

from tabula_rasa.application.documents import DocumentValidationError


class EntityDocumentStore:
    """Thin scope adapter; provider identity, grants and reliability stay owned.

    Existing Drive appProperties use the original profile key even when its
    canonical entity ID differs. Never retag/move bytes merely for cutover.
    """

    def __init__(self, entity_id, profile_key, store):
        self.entity_id, self.profile_key, self.store = entity_id, profile_key, store

    @property
    def scope_key(self):
        return self.store.scope_key

    @property
    def store_kind(self):
        return self.store.store_kind

    def _scope(self, entity_id):
        if entity_id != self.entity_id:
            raise DocumentValidationError("Document storage belongs to a different business entity.")
        return self.profile_key

    def _reference(self, document):
        if document.profile_key != self.profile_key:
            raise DocumentValidationError("Document storage returned a different business profile.")
        return replace(document, profile_key=self.entity_id)

    def upload(self, entity_id, upload):
        return self._reference(self.store.upload(self._scope(entity_id), upload))

    def inventory(self, entity_id, *, fresh=False):
        inventory = self.store.inventory(self._scope(entity_id), fresh=fresh)
        return replace(inventory, documents=tuple(self._reference(document) for document in inventory.documents))

    def metadata(self, entity_id, storage_key):
        return self._reference(self.store.metadata(self._scope(entity_id), storage_key))

    def fetch(self, entity_id, storage_key):
        return self.store.fetch(self._scope(entity_id), storage_key)

    def delete(self, entity_id, storage_key):
        return self.store.delete(self._scope(entity_id), storage_key)
