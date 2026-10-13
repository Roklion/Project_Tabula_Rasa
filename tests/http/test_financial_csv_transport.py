"""Read capability, selected scope and bounded safe failures at CSV transport."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from tabula_rasa.application.reporting import ReportingService
from tabula_rasa.application.reporting_contracts import LedgerSnapshot
from tabula_rasa.errors import StorageError
from tabula_rasa.http.app import create_app
from tabula_rasa.http.config import HttpSettings
from tabula_rasa.http.context import DenyContext, RequestContext
from tests.test_financial_csv import csv_rows, financial_snapshot
from tests.test_journal_exports import JOURNAL_COLUMNS, TRANSACTION_COLUMNS


PREFIX = "/api/v1/entities/alpha/"
FILES = ("exports/transactions.csv", "exports/journal-postings.csv", "ledger/selected.csv")


@pytest.fixture
def csv_client():
    runtime = SimpleNamespace(entity="alpha", capabilities=frozenset({"bookkeeping:read"}),
        operation=nullcontext, close=lambda: None, ready=lambda: True)
    repository = Mock()
    repository.read_ledger.side_effect = lambda **_: financial_snapshot(runtime.entity.title())
    runtime.services = Mock(return_value=SimpleNamespace(reporting=ReportingService(repository)))
    runtime.resolve_context = lambda _: RequestContext("actor", "org", runtime.entity, runtime.capabilities,
                                                       "scope:" + runtime.entity, "csrf")
    with TestClient(create_app(settings=HttpSettings("test", "http://testserver"),
                              runtime_factory=lambda _: runtime)) as client:
        yield client, runtime, repository


def test_read_only_downloads_are_current_private_csv_attachments_and_whole_journals(csv_client):
    client, _, repository = csv_client
    responses = [client.get(PREFIX + path) for path in FILES[:2]]
    selected = client.get(PREFIX + FILES[2], params=[("entry_ids", "journal:shared-journal"), ("entry_ids", "simple")])
    for response in (*responses, selected):
        assert response.status_code == 200 and response.headers["content-type"] == "text/csv; charset=utf-8"
        assert response.headers["content-disposition"].startswith('attachment; filename="tabula-rasa-')
        assert response.headers["cache-control"] == "no-store" and response.headers["x-content-type-options"] == "nosniff"
    assert csv_rows(responses[0].content)[0] == TRANSACTION_COLUMNS
    assert csv_rows(responses[1].content)[0] == JOURNAL_COLUMNS
    assert [row["Type"] for row in csv_rows(selected.content)[1]] == ["Journal", "↳ Posting", "↳ Posting", "Expense"]
    assert repository.read_ledger.call_count == 3
    assert all(call.kwargs == {"force_refresh": True} for call in repository.read_ledger.call_args_list)


def test_two_selected_entities_never_reuse_each_others_csv_even_with_equal_record_ids(csv_client):
    client, runtime, _ = csv_client
    alpha = client.get(PREFIX + FILES[0]).content
    assert csv_rows(alpha)[1][0]["Account"] == "Alpha"
    runtime.entity = "beta"
    assert client.get(PREFIX + FILES[0]).status_code == 403
    beta = client.get("/api/v1/entities/beta/" + FILES[0]).content
    assert csv_rows(beta)[1][0]["Account"] == "Beta"
    assert b"Beta" not in alpha and b"Alpha" not in beta


@pytest.mark.parametrize("path", FILES)
def test_forbidden_and_anonymous_downloads_fail_before_composing_services(csv_client, path):
    client, runtime, repository = csv_client
    assert client.get("/api/v1/entities/foreign/" + path).status_code == 403
    runtime.capabilities = frozenset({"bookkeeping:write"})
    assert client.get(PREFIX + path).status_code == 403
    runtime.resolve_context = DenyContext()
    assert client.get(PREFIX + path).status_code == 401
    runtime.services.assert_not_called()
    repository.read_ledger.assert_not_called()


def test_missing_or_filtered_selection_is_not_silently_partially_downloaded(csv_client):
    client, _, _ = csv_client
    for params in ([('entry_ids', 'simple'), ('entry_ids', 'missing')],
                   [('entry_ids', 'debit')], [('entry_ids', 'simple'), ('kind', 'Transfer')]):
        result = client.get(PREFIX + FILES[2], params=params)
        assert result.status_code == 404 and result.json()["error"]["code"] == "not_found"
        assert "content-disposition" not in result.headers
    result = client.get(PREFIX + FILES[2], params={"start": "2026-10-05", "end": "2026-10-01"})
    assert result.status_code == 422


def test_empty_csv_downloads_and_provider_failures_do_not_fabricate_data_or_echo_private_values(csv_client):
    client, _, repository = csv_client
    repository.read_ledger.side_effect = None
    repository.read_ledger.return_value = LedgerSnapshot()
    assert csv_rows(client.get(PREFIX + FILES[0]).content) == (TRANSACTION_COLUMNS, [])
    assert csv_rows(client.get(PREFIX + FILES[1]).content) == (JOURNAL_COLUMNS, [])
    assert csv_rows(client.get(PREFIX + FILES[2]).content)[1] == []
    repository.read_ledger.side_effect = StorageError("PRIVATE ledger / credentials")
    for path in FILES:
        result = client.get(PREFIX + path)
        assert result.status_code == 503 and result.json()["error"]["code"] == "unavailable"
        assert "PRIVATE" not in result.text and "content-disposition" not in result.headers
