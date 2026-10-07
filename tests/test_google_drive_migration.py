"""Migration inventory reads selected-provider metadata and never document bytes."""

from copy import deepcopy

import pytest

from tabula_rasa.infrastructure.google_drive_migration import GoogleDriveMigrationInventory
from tabula_rasa.migration.documents import enrich_snapshot
from tabula_rasa.migration.model import MigrationError
from tabula_rasa.migration.planning import build_plan
from tabula_rasa.infrastructure.postgres.migration import PostgresMigrationRunner
from tests.test_sheets_migration_source import plan_for


class MetadataOnlyDrive:
    def __init__(self, files):
        self.files, self.calls = files, []

    def list_profile_receipts(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.files)

    def download_file(self, *_):
        raise AssertionError("Migration must not download bytes.")

    upload_receipt = delete_file = download_file


def legacy_file(profile="alpha"):
    return dict(id="legacy-file", name="Synthetic legacy scan.pdf", size="123", mimeType="application/pdf",
                description="Synthetic original.pdf", parents=["folder-" + profile],
                createdTime="2026-01-01T01:00:00+01:00", modifiedTime="2026-02-01T00:00:00Z",
                appProperties=dict(tabulaRasaKind="receipt", tabulaRasaProfile=profile))


def test_legacy_inventory_keeps_known_metadata_instants_and_deterministic_mapping():
    client = MetadataOnlyDrive([legacy_file()])
    store = GoogleDriveMigrationInventory("alpha", "folder-alpha", lambda: client)
    inventory = store.inventory("alpha", fresh=True)
    assert client.calls == [dict(profile_key="alpha", folder_id="folder-alpha", _force_refresh=True)]
    source = plan_for().snapshot
    snapshot = enrich_snapshot(source, document_scope=store.scope_key, documents=inventory.documents,
                               document_timestamps=inventory.timestamps, inventory_complete=True)
    plan = build_plan(snapshot)
    row, = snapshot.metadata["documents"]
    assert row["created_at"] == "2026-01-01T00:00:00Z"
    assert row["updated_at"] == "2026-02-01T00:00:00Z"
    assert row["metadata"]["byte_size"] == 123
    assert row["metadata"]["mime_type"] == "application/pdf"
    assert row["metadata"]["sha256"] == ""
    assert row["metadata"]["original_filename"] == "Synthetic original.pdf"
    mapping = next(row for row in plan.mappings if row.source_record_kind == "Documents")
    assert mapping.source_updated_at == "2026-02-01T00:00:00Z"
    assert mapping.mapping_reason == "entity_store_locator_identity"
    assert PostgresMigrationRunner(None, secondary=True).execute(plan)["missing_loaders"] == []


@pytest.mark.parametrize("change", ["profile", "folder", "checksum", "size", "filename"])
def test_inventory_anomalies_stop_without_returning_private_metadata(change):
    file = legacy_file()
    if change == "profile":
        file["appProperties"]["tabulaRasaProfile"] = "beta"
    elif change == "folder":
        file["parents"] = ["folder-beta"]
    elif change == "checksum":
        file["appProperties"]["tabulaRasaSha256"] = "invalid-secret-like-string"
    elif change == "size":
        file["size"] = "private invalid size"
    else:
        file["name"] = ""
    store = GoogleDriveMigrationInventory("alpha", "folder-alpha", lambda: MetadataOnlyDrive([file]))
    with pytest.raises(MigrationError) as caught:
        store.inventory("alpha", fresh=True)
    assert "private invalid size" not in str(caught.value) and "secret-like" not in str(caught.value)
    assert caught.value.__context__ is None


def test_inventory_cannot_fall_back_to_another_profile():
    client = MetadataOnlyDrive([legacy_file("beta")])
    store = GoogleDriveMigrationInventory("alpha", "folder-alpha", lambda: client)
    with pytest.raises(Exception, match="different business profile"):
        store.inventory("beta", fresh=True)
    assert client.calls == []
