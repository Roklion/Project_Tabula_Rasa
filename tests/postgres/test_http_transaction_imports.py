"""Imports through HTTP/application/native storage, including isolation and replay."""

from dataclasses import replace

from tabula_rasa.http.context import RequestContext
from tests.postgres.test_http_baselines import HEADERS, PREFIX, commercial as commercial, snapshot
from tests.postgres.test_import_repository import csv as transaction_csv, qb
from tests.test_transaction_import_files import csv_bytes, general_ledger_bytes


UPLOAD_HEADERS = {**HEADERS, "Content-Type": "application/octet-stream"}


def upload(client, path, content, **query):
    return client.post(PREFIX + "imports/" + path, headers=UPLOAD_HEADERS, content=content, params=query)


def test_quickbooks_preview_has_no_writes_and_commit_preserves_duplicates_transfer_and_replay(database, commercial):
    alpha, beta, (client, other), _ = commercial
    content = csv_bytes([qb(), qb(), qb(**{"Transaction Type": "Transfer", "Split": "bank", "Num": "T-1", "Name": "", "Amount": "5"})])
    before = snapshot(database)
    preview = upload(client, "quickbooks/preview", content, filename="transactions.csv")
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"] == {"ready": 2, "duplicates": 1, "Income": 0, "Expense": 1,
                                       "Transfer": 1, "validation_errors": 0, "conversion_errors": 0}
    assert preview.json()["duplicate_rows"] == [3]
    assert snapshot(database) == before
    committed = upload(client, "quickbooks", content, filename="transactions.csv")
    assert committed.status_code == 200, committed.text
    assert committed.json()["status"] == "fully_applied" and committed.json()["imported_count"] == 2
    assert len(set(committed.json()["transaction_ids"])) == 2
    assert not beta.transactions.list()
    assert upload(other, "quickbooks", content, filename="transactions.csv").json()["imported_count"] == 0
    assert upload(client, "quickbooks/preview", content, filename="transactions.csv").json()["summary"]["duplicates"] == 3
    transfers = [row for row in alpha.transactions.list() if row["kind"] == "Transfer"]
    assert len(transfers) == 1 and transfers[0]["to_account_id"] == "bank" and transfers[0]["category_id"] == ""
    # Equal source batches in a separately authorized entity retain their own identities.
    beta_context = RequestContext("actor", "org", "beta", frozenset({"bookkeeping:read", "bookkeeping:write"}), "beta-scope", "csrf")
    other.app.state.runtime.resolve_context = lambda request: beta_context
    beta_result = other.post(PREFIX.replace("/alpha/", "/beta/") + "imports/quickbooks", headers=UPLOAD_HEADERS,
                             content=content, params={"filename": "transactions.csv"})
    assert beta_result.status_code == 200 and beta_result.json()["imported_count"] == 2
    assert set(committed.json()["transaction_ids"]).isdisjoint(beta_result.json()["transaction_ids"])


def test_auto_create_proposals_are_read_only_and_fresh_validation_blocks_invalid_batch(database, commercial):
    alpha, beta, (client, _), _ = commercial
    content = csv_bytes([qb(Account="Checking", Split="New office")])
    before = snapshot(database)
    preview = upload(client, "quickbooks/preview", content, filename="transactions.csv", auto_create=True).json()
    assert preview["summary"]["ready"] == 1 and not preview["errors"]
    assert preview["new_accounts"] == [{"name": "Checking", "type": "Bank", "classification": "Asset", "opening_balance": "0.00"}]
    assert preview["new_categories"] == [{"name": "New office", "kind": "Expense"}]
    assert snapshot(database) == before
    committed = upload(client, "quickbooks", content, filename="transactions.csv", auto_create=True)
    assert committed.status_code == 200 and committed.json()["imported_count"] == 1
    assert not any(row["name"] == "Checking" for row in beta.accounts.list())
    invalid = csv_bytes([qb(Account="Other checking", Split="Other office"), qb(Date="invalid")])
    before = snapshot(database)
    assert upload(client, "quickbooks", invalid, filename="transactions.csv", auto_create=True).status_code == 422
    assert snapshot(database) == before
    ordinary = csv_bytes([qb(Num="Fresh-boundary")])
    assert upload(client, "quickbooks/preview", ordinary, filename="transactions.csv").json()["summary"]["ready"] == 1
    alpha.accounts.deactivate("cash")
    before = snapshot(database)
    assert upload(client, "quickbooks", ordinary, filename="transactions.csv").status_code == 422
    assert snapshot(database) == before


def test_csv_prepare_source_rows_then_explicit_atomic_import_and_batch_replay(database, commercial):
    alpha, beta, (client, _), _ = commercial
    content = csv_bytes([transaction_csv(), transaction_csv()])
    before = snapshot(database)
    preview = upload(client, "csv/prepare", content)
    assert preview.status_code == 200 and preview.json()["total_rows"] == 2
    assert snapshot(database) == before
    made = upload(client, "csv", content)
    assert made.status_code == 200 and made.json()["imported_count"] == 2  # CSV retains repeated rows within this batch.
    assert upload(client, "csv", content).json()["imported_count"] == 0
    assert not beta.transactions.list()
    invalid = csv_bytes([transaction_csv(Reference="new"), transaction_csv(Type="Transfer")])
    before = snapshot(database)
    assert upload(client, "csv", invalid).status_code == 422
    assert snapshot(database) == before
    assert len(alpha.transactions.list()) == 3  # Includes the fixture's original expense.


def test_xlsx_and_zip_conversion_failures_cannot_be_bypassed_at_commit(database, commercial):
    _, _, (client, _), _ = commercial
    before = snapshot(database)
    broken = general_ledger_bytes(broken=True)
    preview = upload(client, "quickbooks/preview", broken, filename="General_ledger.xlsx")
    assert preview.status_code == 200 and preview.json()["summary"]["conversion_errors"] == 1
    assert preview.json()["conversion_errors"]
    assert upload(client, "quickbooks", broken, filename="General_ledger.xlsx").status_code == 422
    assert snapshot(database) == before
    good = upload(client, "quickbooks", general_ledger_bytes(), filename="General_ledger.xlsx")
    assert good.status_code == 200 and good.json()["imported_count"] == 1


def test_import_transport_enforces_entity_csrf_mime_and_sanitized_errors(database, commercial):
    _, _, (client, _), _ = commercial
    content = csv_bytes([transaction_csv()])
    before = snapshot(database)
    assert client.post(PREFIX + "imports/csv", content=content).status_code == 403
    assert client.post(PREFIX.replace("/alpha/", "/beta/") + "imports/csv", content=content, headers=UPLOAD_HEADERS).status_code == 403
    assert client.post(PREFIX + "imports/csv", content=content, headers=HEADERS).status_code == 422
    invalid = upload(client, "quickbooks", b"private-source-contents", filename="private-name.xlsx")
    assert invalid.status_code == 422 and "private" not in invalid.text
    missing = upload(client, "csv/prepare", b"Date,Type\n").json()
    assert "Missing columns: Account, Amount, Category" in missing["errors"]
    assert snapshot(database) == before
    resolver = client.app.state.runtime.resolve_context
    client.app.state.runtime.resolve_context = lambda request: replace(resolver(request), capabilities=frozenset({"bookkeeping:read"}))
    assert upload(client, "csv/prepare", content).status_code == 403
