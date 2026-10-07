"""Freeze selected-profile identity and document inventory without byte I/O."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
import json

from tabula_rasa.application.documents import DocumentMetadata, DocumentReference
from tabula_rasa.document_identity import legacy_document_id
from tabula_rasa.ledger_validation import decode_receipt_references
from tabula_rasa.receipt_manifest import validate_receipt_reference, ReceiptManifestError
from tabula_rasa.receipt_records import document_to_receipt_reference
from .model import MigrationError, SYNTHESIZED_TIMESTAMP


def enrich_snapshot(snapshot, *, entity_name=None, document_scope="", documents=(), inventory_complete=False,
                    document_timestamps=None):
    """Inventory is explicit and profile-bound; unreferenced files remain records."""
    name = snapshot.binding.entity_id if entity_name is None else entity_name
    if not isinstance(name, str) or not name.strip() or name != name.strip():
        raise MigrationError("The source profile needs a valid ledger display name.")
    if not isinstance(document_scope, str) or document_scope != document_scope.strip():
        raise MigrationError("The document-store binding is invalid.")
    by_locator = {}
    identities = set()
    document_timestamps = document_timestamps or {}
    for document in documents:
        if not isinstance(document, DocumentReference) or document.profile_key != snapshot.binding.profile_key:
            raise MigrationError("Document inventory belongs to a different source profile.")
        if not document_scope or document.storage_key in by_locator:
            raise MigrationError("Document inventory has a missing scope or duplicate locator.")
        valid = True
        try:
            validate_receipt_reference(document_to_receipt_reference(document), allow_nonportable_legacy_name=True)
            instants = {}
            for key in ("created_at", "updated_at"):
                value = document_timestamps.get(document.storage_key, {}).get(key, "")
                if value:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    if parsed.tzinfo is None or parsed.utcoffset() is None:
                        raise ValueError
                    instants[key] = parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                else:
                    instants[key] = SYNTHESIZED_TIMESTAMP if key == "created_at" else ""
        except (ReceiptManifestError, ValueError, TypeError):
            valid = False
        if not valid:
            raise MigrationError("Document inventory metadata is invalid; inspect the source privately.")
        identity = document.metadata.document_id or legacy_document_id(
            snapshot.binding.entity_id, "google_drive", document_scope, document.storage_key)
        if (not isinstance(identity, str) or identity != identity.strip() or not identity
                or identity in identities or identity == document.storage_key):
            raise MigrationError("Document inventory contains conflicting document identities.")
        identities.add(identity)
        by_locator[document.storage_key] = {
            **asdict(document), "metadata": {**asdict(document.metadata), "document_id": identity},
            **instants,
        }
    owners = {}
    for title in ("Transactions", "MixedUseExpenses"):
        for row in snapshot.tables[title]:
            owner = ("MixedUseExpenses", row["source_id"]) if row.get("source_type") == "mixed_use_expense" else (title, row["id"])
            for reference in decode_receipt_references(row["receipt_references"]):
                document = by_locator.get(reference["id"])
                if not inventory_complete or document is None:
                    raise MigrationError("A referenced receipt is absent from the selected-profile inventory.")
                actual = document_to_receipt_reference(document_from_record(document))
                if actual != reference:
                    raise MigrationError("Receipt inventory and ledger metadata disagree; inspect the source privately.")
                if reference["id"] in owners and owners[reference["id"]] != owner:
                    raise MigrationError("A receipt has more than one bookkeeping owner.")
                owners[reference["id"]] = owner
    if not document_scope and not by_locator and entity_name is None:
        return replace(snapshot, context="{}")
    metadata = dict(entity_name=name, document_scope=document_scope, inventory_complete=bool(inventory_complete),
                    documents=sorted(by_locator.values(), key=lambda row: row["storage_key"]))
    return replace(snapshot, context=json.dumps(metadata, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def document_from_record(row, *, profile_key=None):
    return DocumentReference(profile_key or row["profile_key"], DocumentMetadata(**row["metadata"]),
                             row["storage_key"], row["open_url"])


def validate_context(snapshot):
    metadata = snapshot.metadata
    if not metadata:
        return snapshot
    return enrich_snapshot(snapshot, entity_name=metadata.get("entity_name"),
                           document_scope=metadata.get("document_scope", ""),
                           documents=[document_from_record(row) for row in metadata.get("documents", ())],
                           inventory_complete=metadata.get("inventory_complete", False),
                           document_timestamps={row["storage_key"]: {key: row.get(key, "") for key in ("created_at", "updated_at")}
                                                for row in metadata.get("documents", ())})
