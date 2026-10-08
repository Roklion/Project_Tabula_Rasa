"""Reference services validate without persistence and preserve the Sheets contract."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

from tabula_rasa.application import (
    AccountService,
    PayeeService,
    TagService,
    assemble_application_services,
)
from tabula_rasa.composition import create_sheets_application
from tabula_rasa.errors import (
    StorageConflictError,
    StorageNotFoundError,
    StorageValidationError,
)
from tabula_rasa.infrastructure.google_sheets import (
    GoogleSheetsAccountRepository,
    GoogleSheetsLedgerSetupRepository,
    GoogleSheetsPayeeRepository,
    GoogleSheetsTagRepository,
)
from tabula_rasa.storage import GoogleSheetsStorage
from tests.app_support import profile_config
from tests.fakes import FakeWorkbook


class RecordingRepository:
    """A persistence-free port that records calls and returns an opaque result."""

    def __init__(self):
        self.calls = []
        self.result = {"id": "synthetic", "status": "fully_applied"}
        self.records = [self.result]
        self.error = None

    def _call(self, operation, args, kwargs):
        self.calls.append((operation, args, kwargs))
        if self.error is not None:
            raise self.error
        return self.result

    def list(self, **kwargs):
        self._call("list", (), kwargs)
        return self.records

    def create(self, *args, **kwargs):
        return self._call("create", args, kwargs)

    def update(self, *args, **kwargs):
        return self._call("update", args, kwargs)

    def merge(self, *args, **kwargs):
        return self._call("merge", args, kwargs)

    def remove(self, *args, **kwargs):
        return self._call("remove", args, kwargs)


def test_account_service_normalizes_inputs_without_additional_reads():
    repository = RecordingRepository()
    service = AccountService(repository)

    assert service.list() is repository.records
    assert service.list(active_only=False) is repository.records
    assert [call[2] for call in repository.calls] == [
        {"active_only": True},
        {"active_only": False},
    ]
    repository.calls.clear()

    assert service.create(" Owner draws ", " Other ", "-125.505") is repository.result
    assert repository.calls == [
        (
            "create",
            ("Owner draws", "Other", "-125.50"),
            {"classification": "Equity", "parent_id": ""},
        )
    ]
    repository.calls.clear()
    assert (
        service.update(
            " account-1 ",
            name=" Checking ",
            type=" Bank ",
            classification=" asset ",
            opening_balance="1.235",
            active="false",
            parent_id=" parent-1 ",
        )
        is repository.result
    )
    assert repository.calls == [
        (
            "update",
            ("account-1",),
            {
                "changes": {
                    "name": "Checking",
                    "type": "Bank",
                    "classification": "Asset",
                    "opening_balance": "1.24",
                    "active": False,
                    "parent_id": "parent-1",
                }
            },
        )
    ]
    repository.calls.clear()
    service.rename("account-1", " Renamed ")
    service.deactivate("account-1")
    assert repository.calls == [
        ("update", ("account-1",), {"changes": {"name": "Renamed"}}),
        ("update", ("account-1",), {"changes": {"active": False}}),
    ]


@pytest.mark.parametrize(
    "operation",
    [
        lambda service: service.create(" ", "Bank"),
        lambda service: service.create("Checking", "Unknown"),
        lambda service: service.create("Checking", "Bank", classification="Liability"),
        lambda service: service.create("Checking", "Bank", "NaN"),
        lambda service: service.create("Checking", "Bank", "bad amount"),
        lambda service: service.create("Checking", "Bank", "9" * 27),
        lambda service: service.update("account-1", opening_balance="9" * 26 + ".999"),
        lambda service: service.update("", name="Checking"),
        lambda service: service.update("account-1", classification="invalid"),
        lambda service: service.update(
            "account-1", type="Bank", classification="Equity"
        ),
        lambda service: service.update("account-1", active="invalid"),
    ],
)
def test_account_service_rejects_invalid_input_before_repository_call(operation):
    repository = RecordingRepository()
    with pytest.raises(StorageValidationError):
        operation(AccountService(repository))
    assert repository.calls == []


@pytest.mark.parametrize("service_type", [PayeeService, TagService])
def test_managed_services_preserve_expected_snapshots_and_delegate_once(service_type):
    repository = RecordingRepository()
    service = service_type(repository)
    expected_record = {"id": "source-1", "name": "Old name", "active": False}
    expected_records = [expected_record, {"id": "target-1", "name": "Target"}]

    assert service.list() is repository.records
    assert repository.calls[-1] == ("list", (), {"active_only": False})
    repository.calls.clear()
    assert service.create("  New name  ", active=False) is repository.result
    assert (
        service.rename(" source-1 ", " Renamed ", expected=expected_record)
        is repository.result
    )
    assert (
        service.update("source-1", active="TRUE", expected=expected_record)
        is repository.result
    )
    assert (
        service.merge(
            " target-1 ",
            [" source-1 ", "source-1", "source-2"],
            expected=expected_records,
        )
        is repository.result
    )
    assert service.remove(" source-1 ", expected=expected_record) is repository.result
    assert repository.calls == [
        ("create", ("New name",), {"active": False}),
        (
            "update",
            ("source-1",),
            {"changes": {"name": "Renamed"}, "expected": expected_record},
        ),
        (
            "update",
            ("source-1",),
            {"changes": {"active": True}, "expected": expected_record},
        ),
        (
            "merge",
            ("target-1", ["source-1", "source-2"]),
            {"expected": expected_records},
        ),
        ("remove", ("source-1",), {"expected": expected_record}),
    ]
    assert repository.calls[1][2]["expected"] is expected_record
    assert repository.calls[3][2]["expected"] is expected_records
    assert expected_record["active"] is False


@pytest.mark.parametrize("service_type", [PayeeService, TagService])
@pytest.mark.parametrize(
    "operation",
    [
        lambda service: service.create(" "),
        lambda service: service.create("Name", active="invalid"),
        lambda service: service.rename("record-1", " "),
        lambda service: service.update("record-1", active="invalid"),
        lambda service: service.merge("target", []),
        lambda service: service.merge("target", [" target "]),
        lambda service: service.merge("target", [""]),
        lambda service: service.remove(""),
    ],
)
def test_managed_services_reject_invalid_input_without_reading_or_writing(
    service_type, operation
):
    repository = RecordingRepository()
    with pytest.raises(StorageValidationError):
        operation(service_type(repository))
    assert repository.calls == []


@pytest.mark.parametrize("service_type", [AccountService, PayeeService, TagService])
@pytest.mark.parametrize(
    "operation",
    [
        lambda service: service.list(),
        lambda service: service.rename("record-1", "Renamed"),
    ],
)
def test_service_failures_are_propagated_without_retry(service_type, operation):
    repository = RecordingRepository()
    failure = StorageNotFoundError("Synthetic record is unavailable")
    repository.error = failure
    with pytest.raises(StorageNotFoundError) as raised:
        operation(service_type(repository))
    assert raised.value is failure
    assert len(repository.calls) == 1


def _sheets_services(storage):
    return assemble_application_services(
        "test",
        ledger_repository=GoogleSheetsLedgerSetupRepository(storage),
        account_repository=GoogleSheetsAccountRepository(storage),
        payee_repository=GoogleSheetsPayeeRepository(storage),
        tag_repository=GoogleSheetsTagRepository(storage),
    )


def test_account_adapter_preserves_hierarchy_classification_and_depreciation_guards(
    storage,
):
    service = _sheets_services(storage).accounts
    parent = service.create("Operating", "Bank")
    child = service.create("Reserve", "Cash", parent_id=parent["id"])
    original_rows = deepcopy(storage._workbook.sheets["Accounts"].rows)

    with pytest.raises(StorageConflictError, match="unique"):
        service.create(" operating ", "Cash")
    with pytest.raises(StorageValidationError, match="Asset"):
        service.update(parent["id"], classification="Liability")
    with pytest.raises(StorageValidationError, match="hierarchy"):
        service.update(parent["id"], parent_id=child["id"])
    assert storage._workbook.sheets["Accounts"].rows == original_rows

    expense = storage.create_category("Depreciation", "Expense")
    offset = service.create("Accumulated depreciation", "Other", classification="Asset")
    storage.create_asset(
        name="Office laptop",
        asset_type="Computers & office equipment",
        acquisition_date="2026-01-15",
        depreciation_start_date="2026-01-31",
        cost_basis="1200",
        salvage_value="0",
        useful_life_quarters=20,
        depreciation_method="Straight-line",
        depreciation_expense_account_id=expense["id"],
        accumulated_depreciation_account_id=offset["id"],
    )
    with pytest.raises(StorageConflictError, match="Other / Asset"):
        service.update(offset["id"], type="Bank")
    service.deactivate(child["id"])
    assert child["id"] not in {record["id"] for record in service.list()}
    assert (
        next(
            record
            for record in service.list(active_only=False)
            if record["id"] == child["id"]
        )["active"]
        is False
    )


@pytest.mark.parametrize("kind", ["payees", "tags"])
def test_managed_adapters_keep_deduplication_reactivation_and_stale_guards(
    storage, kind
):
    service = getattr(_sheets_services(storage), kind)
    source = service.create("Ａｃｍｅ   Supplies", active=False)
    reactivated = service.create("acme supplies")
    assert reactivated["id"] == source["id"]
    assert reactivated["active"] == "TRUE"
    assert len(service.list()) == 1
    target = service.create("Target")
    service.update(source["id"], active=False, expected=reactivated)

    for operation in (
        lambda: service.rename(source["id"], "Renamed", expected=reactivated),
        lambda: service.merge(
            target["id"], [source["id"]], expected=[target, reactivated]
        ),
        lambda: service.remove(source["id"], expected=reactivated),
    ):
        with pytest.raises(StorageConflictError, match="changed"):
            operation()
    fresh = next(record for record in service.list() if record["id"] == source["id"])
    assert fresh["name"] == "Ａｃｍｅ   Supplies" and fresh["active"] == "FALSE"
    assert service.remove(source["id"], expected=fresh) == {"status": "fully_applied"}


def test_profile_composition_scopes_reference_mutations_and_preserves_merge_fields():
    storages = {
        f"{key}-sheet": GoogleSheetsStorage(FakeWorkbook())
        for key in ("north", "south")
    }
    secrets = {
        "business_profiles": {
            key: profile_config(name=key.title(), spreadsheet_id=f"{key}-sheet")
            for key in ("north", "south")
        }
    }
    with patch.object(
        GoogleSheetsStorage,
        "from_secrets",
        side_effect=lambda selected: storages[selected["spreadsheet_id"]],
    ):
        north = create_sheets_application("north", secrets)
        south = create_sheets_application("south", secrets)
    created = {}
    for key, application in (("north", north), ("south", south)):
        services, storage = application.services, application.workbook_admin
        account = services.accounts.create("Checking", "Bank", "100")
        category = storage.create_category("Office", "Expense")
        source_payee, target_payee = (
            services.payees.create("Source"),
            services.payees.create("Target"),
        )
        source_tag, target_tag = (
            services.tags.create("Source"),
            services.tags.create("Target"),
        )
        transaction = storage.create_transaction(
            txn_date="2026-09-01",
            kind="Expense",
            amount="10.55",
            account_id=account["id"],
            category_id=category["id"],
            payee_id=source_payee["id"],
            tag_ids=[source_tag["id"]],
            description="Invoice payment",
            reference="INV-42",
        )
        trip = storage.create_mileage_trip(
            trip_date="2026-09-02",
            miles="12.5",
            start_location="Office",
            destination="Client",
            business_purpose="Site visit",
            tag_ids=[source_tag["id"]],
        )
        created[key] = (
            account,
            source_payee,
            target_payee,
            source_tag,
            target_tag,
            transaction,
            trip,
        )
    south_before = {
        title: deepcopy(sheet.rows)
        for title, sheet in storages["south-sheet"]._workbook.sheets.items()
    }
    transaction_sheet = north.workbook_admin._workbook.sheets["Transactions"]
    transaction_before = dict(
        zip(transaction_sheet.rows[0], transaction_sheet.rows[1], strict=True)
    )
    account, source_payee, target_payee, source_tag, target_tag, transaction, trip = (
        created["north"]
    )
    services = north.services
    services.accounts.update(
        account["id"], name="North checking", opening_balance="150"
    )
    for service, record in (
        (services.payees, source_payee),
        (services.tags, source_tag),
    ):
        with pytest.raises(StorageConflictError, match="referenced"):
            service.remove(record["id"], expected=record)
    assert services.payees.merge(
        target_payee["id"],
        [source_payee["id"]],
        expected=[source_payee, target_payee],
    ) == {"status": "fully_applied", "count": "1"}
    assert services.tags.merge(
        target_tag["id"],
        [source_tag["id"]],
        expected=[source_tag, target_tag],
    ) == {"status": "fully_applied", "count": "1"}
    fresh_transaction = north.workbook_admin.list_transactions()[0]
    transaction_after = dict(
        zip(transaction_sheet.rows[0], transaction_sheet.rows[1], strict=True)
    )
    for field, value in transaction_before.items():
        if field not in {"payee_id", "tag_ids"}:
            assert transaction_after[field] == value
    assert fresh_transaction["payee_id"] == target_payee["id"]
    assert fresh_transaction["tag_ids"] == [target_tag["id"]]
    fresh_trip = north.workbook_admin.list_mileage_trips()[0]
    assert fresh_trip["id"] == trip["id"] and fresh_trip["miles"] == trip["miles"]
    assert fresh_trip["tag_ids"] == [target_tag["id"]]
    assert {
        title: sheet.rows
        for title, sheet in storages["south-sheet"]._workbook.sheets.items()
    } == south_before


def test_reference_services_run_without_importing_ui_or_persistence():
    code = """
import importlib.abc
import sys

class RejectInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = (
            'tabula_rasa.storage', 'tabula_rasa.infrastructure',
            'tabula_rasa.composition', 'gspread', 'google', 'streamlit', 'pandas',
        )
        if any(fullname == name or fullname.startswith(name + '.') for name in blocked):
            raise AssertionError('Application imported infrastructure: ' + fullname)

sys.meta_path.insert(0, RejectInfrastructure())
from tabula_rasa.application import assemble_application_services
from tabula_rasa.errors import StorageValidationError

class Repository:
    ledger_name = 'Synthetic ledger'
    def __init__(self):
        self.calls = []
    def ensure_defaults(self):
        return {'accounts': 0, 'categories': 0}
    def list(self, **kwargs):
        return []
    def create(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {'id': 'synthetic', 'name': args[0]}
    def update(self, record_id, **kwargs):
        self.calls.append((record_id, kwargs))
        return {'id': record_id, **kwargs['changes']}
    def merge(self, target_id, source_ids, **kwargs):
        self.calls.append((target_id, source_ids, kwargs))
        return {'status': 'fully_applied', 'count': str(len(source_ids))}
    def remove(self, record_id, **kwargs):
        return {'status': 'fully_applied'}

accounts, payees, tags = Repository(), Repository(), Repository()
services = assemble_application_services(
    'test', ledger_repository=Repository(), account_repository=accounts,
    payee_repository=payees, tag_repository=tags,
)
assert services.accounts.create(' Checking ', 'Bank')['name'] == 'Checking'
assert accounts.calls[0][1]['classification'] == 'Asset'
assert services.accounts.update('account-1', active='false')['active'] is False
for service, repository in ((services.payees, payees), (services.tags, tags)):
    assert service.create(' Name ')['name'] == 'Name'
    snapshot = {'id': 'source', 'active': False}
    service.rename('source', 'Renamed', expected=snapshot)
    assert repository.calls[-1][1]['expected'] is snapshot
    assert service.merge('target', ['source'])['count'] == '1'
    assert service.remove('source')['status'] == 'fully_applied'
try:
    services.accounts.create('Checking', 'Bank', classification='Liability')
except StorageValidationError:
    pass
else:
    raise AssertionError('Invalid classification reached repository')
assert len(accounts.calls) == 2
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
