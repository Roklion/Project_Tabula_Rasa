"""Frozen inventory and identity rules are independent of external byte I/O."""

from dataclasses import replace
import json

import pytest

from tabula_rasa.application.documents import DocumentMetadata
from tabula_rasa.migration.documents import enrich_snapshot
from tabula_rasa.migration.model import MigrationError
from tabula_rasa.migration.planning import build_plan
from tabula_rasa.infrastructure.postgres.migration import PostgresMigrationRunner
from tests.migration_support import complete_plan, document
from tests.test_sheets_migration_source import plan_for


def test_profile_scoped_inventory_includes_unreferenced_documents_and_persisted_mappings():
    alpha, _, _ = complete_plan("alpha")
    beta, _, _ = complete_plan("beta")
    assert alpha.target_id("Documents", "file-mixed") != beta.target_id("Documents", "file-mixed")
    assert alpha.target_id("Documents", "file-ordinary") == "a" * 32
    assert len(alpha.snapshot.metadata["documents"]) == 3
    document_unit = next(unit for unit in alpha.units if unit.kind == "documents")
    assert len(document_unit.rows["Documents"]) == 3
    assert all("documents" in unit.dependencies for unit in alpha.units if unit.kind.endswith("_receipts") or unit.kind == "mixed_pair")
    assert "Synthetic" not in repr(alpha) + repr(alpha.snapshot) + repr(alpha.units)
    assert "file-mixed" not in json.dumps(alpha.report())


def test_inventory_reordering_is_deterministic_and_ledger_identity_affects_binding():
    plan, _, docs = complete_plan()
    snapshot = enrich_snapshot(plan.snapshot, entity_name="Synthetic alpha", document_scope="folder-alpha",
                               documents=tuple(reversed(docs)), inventory_complete=True)
    assert build_plan(snapshot) == plan
    other = enrich_snapshot(plan.snapshot, entity_name="Different synthetic business", document_scope="folder-alpha",
                            documents=docs, inventory_complete=True)
    assert build_plan(other).run_id != plan.run_id


@pytest.mark.parametrize("change", ["wrong_profile", "missing", "conflict", "duplicate", "shared_identity"])
def test_inventory_anomalies_fail_before_any_database_access(change):
    plan, _, docs = complete_plan()
    documents = list(docs)
    if change == "wrong_profile":
        documents[0] = replace(documents[0], profile_key="beta")
    elif change == "missing":
        documents.pop(0)
    elif change == "conflict":
        documents[0] = replace(documents[0], metadata=DocumentMetadata("", "Changed synthetic scan.pdf"))
    elif change == "duplicate":
        documents.append(documents[0])
    else:
        documents[2] = replace(documents[2], metadata=documents[1].metadata)
    with pytest.raises(MigrationError) as caught:
        enrich_snapshot(plan.snapshot, entity_name="Synthetic alpha", document_scope="folder-alpha",
                        documents=documents, inventory_complete=True)
    assert "Synthetic" not in str(caught.value)


def test_unconfigured_receipts_are_blocked_and_inventory_only_is_supported():
    plan, _, _ = complete_plan()
    with pytest.raises(MigrationError, match="absent"):
        enrich_snapshot(plan.snapshot)
    source = plan_for().snapshot
    inventory_only = enrich_snapshot(source, document_scope="folder-alpha",
                                    documents=[document("alpha", "unreferenced")], inventory_complete=True)
    assert "documents" in [unit.kind for unit in build_plan(inventory_only).units]
    assert PostgresMigrationRunner(None, secondary=True).execute(build_plan(inventory_only))["missing_loaders"] == []


def test_core_framework_keeps_missing_receipt_loader_report_without_an_inventory():
    from tests.migration_support import put
    from tests.test_sheets_migration_source import values_with_records
    values = values_with_records()
    put(values, "Transactions", 1, receipt_references='[{"id":"file-alpha","name":"Synthetic scan.pdf"}]')
    plan = plan_for(values)
    assert PostgresMigrationRunner(None).execute(plan)["missing_loaders"] == ["simple_entry_receipts"]
    with pytest.raises(MigrationError, match="absent"):
        PostgresMigrationRunner(None, secondary=True).execute(plan)
