"""Stable legacy receipt identity, independent of external byte storage."""

import json
from uuid import NAMESPACE_URL, uuid5


def legacy_document_id(entity_id, store_kind, store_scope_key, storage_key):
    payload = json.dumps(['tabula-rasa-document-v1', entity_id, store_kind,
                          store_scope_key, storage_key], separators=(',', ':'))
    return uuid5(NAMESPACE_URL, payload).hex
