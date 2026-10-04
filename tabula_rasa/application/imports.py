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


ImportRow = Mapping[str, Any]


@dataclass(frozen=True)
class TransactionImportContext:
    """One selected ledger's references and existing transaction identities."""

    accounts: Sequence[ImportRow]
    categories: Sequence[ImportRow]
    payees: Sequence[ImportRow]
    transactions: Sequence[ImportRow]


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
    existing = {fingerprint(item) for item in context.transactions}
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
