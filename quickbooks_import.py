"""Parse the supported QuickBooks Online Transaction Detail CSV export."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


REQUIRED_COLUMNS = {
    "Date",
    "Transaction Type",
    "Num",
    "Name",
    "Memo/Description",
    "Account",
    "Split",
    "Amount",
}
TRANSFER_TYPES = {"transfer", "funds transfer"}
GENERAL_LEDGER_COLUMNS = (
    "Date", "Transaction Type", "Num", "Name", "Memo/Description",
    "Account", "Debit", "Credit", "Balance",
)
EQUITY_NAME_TERMS = (
    "equity",
    "owner investment",
    "owners investment",
    "owner's investment",
    "capital",
    "retained earnings",
    "opening balance equity",
    "drawing",
    "draws",
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _date(value: Any) -> str:
    text = _text(value)
    for pattern in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    raise ValueError("Date must use MM/DD/YYYY, MM/DD/YY, or YYYY-MM-DD")


def _amount(value: Any) -> Decimal:
    text = _text(value).replace("$", "").replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        result = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("Amount must be a number") from error
    if not result.is_finite() or result == 0:
        raise ValueError("Amount must be non-zero")
    return result


def suggested_account_type(name: str) -> str:
    """Infer a conservative ledger account type from a QuickBooks account name."""
    lowered = name.casefold()
    if any(term in lowered for term in EQUITY_NAME_TERMS):
        return "Equity"
    if "credit card" in lowered or "card payable" in lowered:
        return "Credit card"
    if any(word in lowered for word in ("checking", "savings", "bank")):
        return "Bank"
    if "cash" in lowered:
        return "Cash"
    if "loan" in lowered:
        return "Loan"
    return "Other"


def suggested_account_classification(name: str, account_type: str) -> str:
    """Infer the balance-sheet classification for an account."""
    if account_type in {"Bank", "Cash"}:
        return "Asset"
    if account_type in {"Credit card", "Loan"}:
        return "Liability"
    if account_type == "Equity" or any(
        term in name.casefold() for term in EQUITY_NAME_TERMS
    ):
        return "Equity"
    return "Asset"


def fingerprint(row: Mapping[str, Any]) -> str:
    """Return the stable identity used to prevent repeated imports."""
    fields = (
        "txn_date", "kind", "amount", "account_id", "to_account_id",
        "category_id", "payee", "description", "reference",
    )
    payload = [str(row.get(field, "")).strip().casefold() for field in fields]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def missing_references(
    rows: Iterable[Mapping[str, Any]],
    accounts: Iterable[Mapping[str, Any]],
    categories: Iterable[Mapping[str, Any]],
) -> tuple[list[str], list[tuple[str, str]]]:
    """Return missing account names and inferred (category, kind) pairs."""
    account_names = {_text(item["name"]).casefold() for item in accounts}
    category_keys = {
        (_text(item["name"]).casefold(), _text(item["kind"]).title())
        for item in categories
    }
    missing_accounts: dict[str, str] = {}
    missing_categories: dict[tuple[str, str], tuple[str, str]] = {}
    for source in rows:
        source_name = _text(source.get("Account"))
        if source_name and source_name.casefold() not in account_names:
            missing_accounts.setdefault(source_name.casefold(), source_name)
        txn_type = _text(source.get("Transaction Type")).casefold()
        split_name = _text(source.get("Split"))
        if txn_type in TRANSFER_TYPES:
            if split_name and split_name.casefold() not in account_names:
                missing_accounts.setdefault(split_name.casefold(), split_name)
        else:
            try:
                kind = "Income" if _amount(source.get("Amount")) > 0 else "Expense"
            except ValueError:
                continue
            key = (split_name.casefold(), kind)
            if split_name and key not in category_keys:
                missing_categories.setdefault(key, (split_name, kind))
    return list(missing_accounts.values()), list(missing_categories.values())


def general_ledger_rows(matrix: Iterable[Iterable[Any]]) -> tuple[list[dict[str, str]], list[str]]:
    """Collapse paired QuickBooks General Ledger entries into import rows."""
    rows = [list(row) for row in matrix]
    header_index = next(
        (index for index, row in enumerate(rows) if set(GENERAL_LEDGER_COLUMNS).issubset({_text(value) for value in row})),
        None,
    )
    if header_index is None:
        return [], ["General Ledger header row was not found"]
    header = [_text(value) for value in rows[header_index]]
    positions = {name: header.index(name) for name in GENERAL_LEDGER_COLUMNS}
    entries: list[dict[str, str]] = []
    errors: list[str] = []
    for sheet_row, values in enumerate(rows[header_index + 1 :], start=header_index + 2):
        def cell(name: str) -> Any:
            index = positions[name]
            return values[index] if index < len(values) else ""

        if not _text(cell("Date")):
            continue
        try:
            debit = Decimal(_text(cell("Debit")) or "0")
            credit = Decimal(_text(cell("Credit")) or "0")
            if (debit > 0) == (credit > 0):
                raise ValueError("exactly one of Debit or Credit must be positive")
            entries.append({
                "sheet_row": str(sheet_row),
                "Date": _date(cell("Date")),
                "Transaction Type": _text(cell("Transaction Type")),
                "Num": _text(cell("Num")),
                "Name": _text(cell("Name")),
                "Memo/Description": _text(cell("Memo/Description")),
                "Account": _text(cell("Account")),
                "Debit": f"{debit:.2f}",
                "Credit": f"{credit:.2f}",
            })
        except (ValueError, InvalidOperation) as error:
            errors.append(f"General Ledger row {sheet_row}: {error}")

    account_groups: set[str] = set()
    for item in entries:
        txn_type = item["Transaction Type"].casefold()
        if txn_type in TRANSFER_TYPES:
            account_groups.add(item["Account"].casefold())
        elif txn_type in {"deposit", "income", "sales receipt", "invoice", "payment"} and Decimal(item["Debit"]) > 0:
            account_groups.add(item["Account"].casefold())
        elif txn_type in {"expense", "check", "bill", "credit card expense"} and Decimal(item["Credit"]) > 0:
            account_groups.add(item["Account"].casefold())
    buckets: dict[tuple[str, ...], list[dict[str, str]]] = {}
    for item in entries:
        amount = item["Debit"] if Decimal(item["Debit"]) > 0 else item["Credit"]
        key = (item["Date"], item["Transaction Type"].casefold(), amount)
        buckets.setdefault(key, []).append(item)

    converted: list[dict[str, str]] = []
    pairs: list[list[dict[str, str]]] = []
    for bucket in buckets.values():
        debits = [item for item in bucket if Decimal(item["Debit"]) > 0]
        credits = [item for item in bucket if Decimal(item["Credit"]) > 0]
        if len(debits) != len(credits):
            locations = ", ".join(item["sheet_row"] for item in bucket)
            errors.append(f"General Ledger row(s) {locations}: debit/credit entry count does not balance")
            continue
        unmatched = list(credits)
        for debit in debits:
            scored = []
            for credit in unmatched:
                score = sum(
                    weight
                    for field, weight in (("Num", 4), ("Memo/Description", 2), ("Name", 1))
                    if debit[field] and debit[field].casefold() == credit[field].casefold()
                )
                scored.append((score, credit))
            best_score = max((score for score, _ in scored), default=-1)
            candidates = [credit for score, credit in scored if score == best_score]
            if len(candidates) != 1:
                locations = ", ".join([debit["sheet_row"]] + [item["sheet_row"] for item in candidates])
                errors.append(f"General Ledger row(s) {locations}: matching entry is ambiguous")
                continue
            credit = candidates[0]
            unmatched.remove(credit)
            pairs.append([debit, credit])

    for paired in pairs:
        if paired[0]["Account"].casefold() == paired[1]["Account"].casefold():
            locations = ", ".join(item["sheet_row"] for item in paired)
            errors.append(f"General Ledger row(s) {locations}: both entries use the same account")
            continue
        debit = next((item for item in paired if Decimal(item["Debit"]) > 0), None)
        credit = next((item for item in paired if Decimal(item["Credit"]) > 0), None)
        if debit is None or credit is None:
            errors.append(f"General Ledger rows {paired[0]['sheet_row']}, {paired[1]['sheet_row']}: entries do not balance")
            continue
        first = paired[0]
        debit_is_account = debit["Account"].casefold() in account_groups
        credit_is_account = credit["Account"].casefold() in account_groups
        if debit_is_account and credit_is_account:
            account, split, txn_type, amount = credit["Account"], debit["Account"], "Transfer", credit["Credit"]
        elif debit_is_account != credit_is_account:
            account_entry = debit if debit_is_account else credit
            category_entry = credit if debit_is_account else debit
            kind = "Income" if credit is category_entry else "Expense"
            account, split, txn_type = account_entry["Account"], category_entry["Account"], kind
            amount_value = Decimal(debit["Debit"])
            amount = f"{amount_value if kind == 'Income' else -amount_value:.2f}"
        else:
            errors.append(f"General Ledger rows {debit['sheet_row']}, {credit['sheet_row']}: neither side is a cash, card, or transfer account")
            continue
        payee = next((item["Name"] for item in paired if item["Name"]), "")
        converted.append({
            "Date": first["Date"], "Transaction Type": txn_type,
            "Num": first["Num"], "Name": payee,
            "Memo/Description": first["Memo/Description"],
            "Account": account, "Split": split, "Amount": amount,
        })
    return converted, errors


def normalize_rows(
    rows: Iterable[Mapping[str, Any]],
    accounts: Iterable[Mapping[str, Any]],
    categories: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[str]]:
    """Map QuickBooks rows to ledger fields, collecting every actionable error."""
    account_map = {_text(item["name"]).casefold(): item for item in accounts}
    category_map = {
        (_text(item["name"]).casefold(), _text(item["kind"]).title()): item
        for item in categories
    }
    normalized: list[dict[str, str]] = []
    errors: list[str] = []
    for number, source in enumerate(rows, start=2):
        try:
            txn_type = _text(source.get("Transaction Type"))
            source_name = _text(source.get("Account"))
            split_name = _text(source.get("Split"))
            account = account_map.get(source_name.casefold())
            if account is None:
                raise ValueError(f"Account '{source_name}' does not exist")
            amount = _amount(source.get("Amount"))
            if txn_type.casefold() in TRANSFER_TYPES:
                destination = account_map.get(split_name.casefold())
                if destination is None:
                    raise ValueError(f"destination account '{split_name}' does not exist")
                if destination["id"] == account["id"]:
                    raise ValueError("transfer accounts must be different")
                kind, category_id, to_account_id = "Transfer", "", destination["id"]
            else:
                kind = "Income" if amount > 0 else "Expense"
                category = category_map.get((split_name.casefold(), kind))
                if category is None:
                    raise ValueError(f"{kind.lower()} category '{split_name}' does not exist")
                category_id, to_account_id = category["id"], ""
            normalized.append({
                "_source_row": str(number),
                "txn_date": _date(source.get("Date")),
                "kind": kind,
                "amount": f"{abs(amount):.2f}",
                "account_id": str(account["id"]),
                "to_account_id": str(to_account_id),
                "category_id": str(category_id),
                "payee": _text(source.get("Name")),
                "description": _text(source.get("Memo/Description")),
                "reference": _text(source.get("Num")),
            })
        except (ValueError, KeyError) as error:
            errors.append(f"QuickBooks row {number}: {error}")
    return normalized, errors
