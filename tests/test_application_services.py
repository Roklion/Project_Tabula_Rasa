"""Shared application ports preserve repository ownership without provider dependencies."""

from pathlib import Path
import subprocess
import sys

import pytest

from tabula_rasa.application import LedgerInfo, assemble_application_services


class FakeLedgerSetupRepository:
    def __init__(self, name: str) -> None:
        self.ledger_name = name
        self.calls = 0
        self.error: Exception | None = None

    def ensure_defaults(self) -> dict[str, int]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return {"accounts": 2, "categories": 3}


def test_services_use_only_the_supplied_repository() -> None:
    repository = FakeLedgerSetupRepository("North ledger")
    services = assemble_application_services("north", ledger_repository=repository)

    assert services.profile_key == "north"
    assert services.ledger.get_info() == LedgerInfo(name="North ledger")
    assert services.ledger.ensure_defaults() == {"accounts": 2, "categories": 3}
    assert repository.calls == 1

    repository.ledger_name = "Renamed ledger"
    assert services.ledger.get_info().name == "Renamed ledger"
    failure = RuntimeError("Synthetic repository unavailable")
    repository.error = failure
    with pytest.raises(RuntimeError) as raised:
        services.ledger.ensure_defaults()
    assert raised.value is failure
    assert repository.calls == 2  # The service introduces no retries.


@pytest.mark.parametrize("missing", ["metadata", "documents"])
def test_receipt_capability_requires_both_ports(missing: str) -> None:
    with pytest.raises(ValueError, match="both metadata and document storage"):
        assemble_application_services(
            "north",
            ledger_repository=FakeLedgerSetupRepository("North ledger"),
            receipt_repository=None if missing == "metadata" else object(),
            document_store=None if missing == "documents" else object(),
        )


def test_application_package_loads_without_ui_or_google_infrastructure() -> None:
    # A separate interpreter also catches transitive imports; pytest's shared
    # storage fixtures already import gspread in this interpreter.
    code = """
import importlib.abc
import sys

class RejectInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            'tabula_rasa.storage', 'tabula_rasa.infrastructure',
            'tabula_rasa.composition', 'tabula_rasa.google_drive',
            'tabula_rasa.page_renderers', 'gspread', 'google', 'streamlit', 'pandas',
        )
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('Application imported infrastructure: ' + fullname)

sys.meta_path.insert(0, RejectInfrastructure())
from tabula_rasa.application import LedgerInfo, assemble_application_services
from tabula_rasa.application.documents import ReceiptInventory
from tabula_rasa.application.reporting_contracts import LedgerSnapshot

class Repository:
    ledger_name = 'Synthetic ledger'
    def ensure_defaults(self):
        return {'accounts': 0, 'categories': 0}

class Queries:
    def read_ledger(self, *, force_refresh=False):
        return LedgerSnapshot()

class Mileage:
    def list_trips(self, *, fresh=False):
        return ()
    def list_tags(self, *, fresh=False):
        return ()

class Receipts:
    def associations(self, profile_key, *, fresh=False):
        assert profile_key == 'test'
        return ()
    def references(self, profile_key, transaction_id, *, fresh=False):
        assert profile_key == 'test'
        return ()

class Documents:
    def inventory(self, profile_key, *, fresh=False):
        assert profile_key == 'test'
        return ReceiptInventory(())

services = assemble_application_services(
    'test', ledger_repository=Repository(), reporting_repository=Queries(),
    mileage_repository=Mileage(), receipt_repository=Receipts(),
    document_store=Documents(),
)
assert services.ledger.get_info() == LedgerInfo(name='Synthetic ledger')
assert services.ledger.ensure_defaults() == {'accounts': 0, 'categories': 0}
assert services.reporting.query_ledger().entries == ()
assert services.reporting.period_report(services.reporting.read_ledger()).totals == {
    'income': 0.0, 'expenses': 0.0, 'net': 0.0,
}
assert services.mileage.list_trips() == ()
assert services.receipts.references('transaction') == ()
assert services.receipts.unreferenced().documents == ()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
