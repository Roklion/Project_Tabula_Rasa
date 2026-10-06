"""Transaction import commands and provider-independent QuickBooks preview."""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from tabula_rasa.quickbooks_import import (
    fingerprint,
    missing_references,
    normalize_rows,
    suggested_account_classification,
    suggested_account_type,
)
from tabula_rasa.reference_data import normalize_payee_name
from tabula_rasa.reference_data import clean_text
from tabula_rasa.errors import StorageValidationError


ImportRow = Mapping[str, Any]


@dataclass(frozen=True)
class TransactionImportContext:
    """One selected ledger's references and existing transaction identities."""

    accounts: Sequence[ImportRow]
    categories: Sequence[ImportRow]
    payees: Sequence[ImportRow]
    transactions: Sequence[ImportRow]
    import_fingerprints: Sequence[str] = ()


class TransactionImportRepository(Protocol):
    """Batch imports with fresh validation and existing bounded recovery.

    Commands keep reference creation and transaction persistence together in
    the current backend's mutation boundary. They must revalidate against fresh
    references and duplicate identities rather than trusting a displayed preview.
    No worksheet positions, batches, or provider requests cross this port.
    """

    def quickbooks_context(self) -> TransactionImportContext: ...

    def import_csv(self, rows: Iterable[ImportRow]) -> list[dict[str, str]]: ...

    def import_quickbooks(
        self, rows: Iterable[ImportRow], *, auto_create: bool = False
    ) -> list[dict[str, str]]: ...


def preview_quickbooks(
    rows: Iterable[ImportRow],
    context: TransactionImportContext,
    *,
    auto_create: bool = False,
) -> dict[str, Any]:
    """Apply the existing mapping, reference proposals, and duplicate rules."""
    source_rows = list(rows)
    accounts = {str(item["id"]): dict(item) for item in context.accounts}
    categories = {str(item["id"]): dict(item) for item in context.categories}
    new_accounts, new_categories = missing_references(
        source_rows, accounts.values(), categories.values()
    )
    if auto_create:
        for name in new_accounts:
            item = {
                "id": f"pending-account:{name.casefold()}",
                "name": name,
                "active": True,
            }
            accounts[item["id"]] = item
        for name, kind in new_categories:
            item = {
                "id": f"pending-category:{kind}:{name.casefold()}",
                "name": name,
                "kind": kind,
            }
            categories[item["id"]] = item
    normalized, errors = normalize_rows(
        source_rows, accounts.values(), categories.values()
    )
    payee_names = {
        normalize_payee_name(item["name"]): item["name"] for item in context.payees
    }
    existing = {fingerprint(item) for item in context.transactions} | set(context.import_fingerprints)
    seen: set[str] = set()
    ready: list[dict[str, str]] = []
    duplicate_rows: list[int] = []
    for item in normalized:
        payee_key = normalize_payee_name(item.get("payee", ""))
        if payee_key:
            item["payee"] = payee_names.setdefault(payee_key, item["payee"])
        row_number = int(item.pop("_source_row"))
        identity = fingerprint(item)
        if identity in existing or identity in seen:
            duplicate_rows.append(row_number)
        else:
            seen.add(identity)
            ready.append(item)
    counts = {
        kind: sum(item["kind"] == kind for item in ready)
        for kind in ("Income", "Expense", "Transfer")
    }
    return {
        "rows": ready,
        "errors": errors,
        "duplicate_rows": duplicate_rows,
        "new_accounts": new_accounts,
        "new_account_types": {
            name: suggested_account_type(name) for name in new_accounts
        },
        "new_account_classifications": {
            name: suggested_account_classification(name, suggested_account_type(name))
            for name in new_accounts
        },
        "new_categories": new_categories,
        "summary": {"ready": len(ready), "duplicates": len(duplicate_rows), **counts},
    }


def csv_transaction_inputs(rows: Iterable[ImportRow], context: TransactionImportContext):
    """Shared CSV field/reference mapping; transaction rules validate the commands."""
    accounts = {str(item['name']).casefold(): item for item in context.accounts}
    categories = {(str(item['name']).casefold(), item['kind']): item for item in context.categories}
    result = []
    for index, row in enumerate(rows, 2):
        kind = clean_text(row.get('Type'), 'Type', required=True).title()
        if kind not in {'Income', 'Expense'}:
            raise StorageValidationError(f'CSV row {index}: Type must be Income or Expense')
        account_name = clean_text(row.get('Account'), 'Account', required=True)
        category_name = clean_text(row.get('Category'), 'Category', required=True)
        account = accounts.get(account_name.casefold())
        category = categories.get((category_name.casefold(), kind))
        if account is None or category is None:
            raise StorageValidationError(f'CSV row {index}: unknown account or category')
        result.append({
            'txn_date': row.get('Date'), 'kind': kind, 'amount': row.get('Amount'),
            'account_id': account['id'], 'category_id': category['id'],
            'description': row.get('Description', ''), 'reference': row.get('Reference', ''),
            'new_payee_name': clean_text(row.get('Payee', ''), 'New payee'),
        })
    return result


class TransactionImportService:
    """One import boundary shared by ordinary UI and future API callers."""

    def __init__(self, repository: TransactionImportRepository) -> None:
        self._repository = repository

    def preview_quickbooks(
        self, rows: Iterable[ImportRow], *, auto_create: bool = False
    ) -> dict[str, Any]:
        return preview_quickbooks(
            rows, self._repository.quickbooks_context(), auto_create=auto_create
        )

    def import_csv(self, rows: Iterable[ImportRow]) -> list[dict[str, str]]:
        return self._repository.import_csv(rows)

    def import_quickbooks(
        self, rows: Iterable[ImportRow], *, auto_create: bool = False
    ) -> list[dict[str, str]]:
        return self._repository.import_quickbooks(rows, auto_create=auto_create)
