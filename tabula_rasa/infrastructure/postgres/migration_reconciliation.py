"""Read-only core/secondary reconciliation; whole-profile acceptance is separate."""

from dataclasses import asdict
from datetime import date
from decimal import Decimal
import calendar

from sqlalchemy import text

from tabula_rasa.accounting_postings import accounting_postings
from tabula_rasa.ledger_reporting import (
    account_balances, balance_sheet, profit_and_loss, monthly_performance, category_activity_rollups,
)
from tabula_rasa.ledger_validation import decode_receipt_references
from tabula_rasa.application.reporting import calculation_records
from tabula_rasa.errors import StorageNotFoundError
from tabula_rasa.migration.model import digest
from tabula_rasa.migration.reconciliation import mismatched_fields
from .migration import validate_plan
from .migration_readback import TABLES, unit_differences
from .migrations import current_revision, head_revision
from .repository import serialized
from .reporting import PostgresLedgerQueryRepository

CORE = {"Entity", "Accounts", "Categories", "Payees", "Tags", "Transactions", "JournalEntries",
        "JournalPostings", "Postings", "Reports", "Migration"}


class PostgresMigrationReconciler:
    def __init__(self, database):
        self.database = database

    def reconcile(self, plan, *, periods=()):
        validate_plan(plan)
        # One coherent read-only target snapshot, including report calculations.
        with self.database.transaction(read_only=True, require_outer=True) as connection:
            return self._reconcile(connection, plan, periods)

    def _reconcile(self, connection, plan, periods):
        scope = plan.snapshot.binding.entity_id
        params = dict(scope=scope, run=plan.run_id)
        checks, exceptions = [], []

        def check(domain, name, passed):
            checks.append(dict(domain=domain, check=name, passed=bool(passed)))
            if not passed:
                exceptions.append(dict(domain=domain, fields=[name]))

        check("Migration", "schema_revision", current_revision(connection) == head_revision())
        root = connection.execute(text("SELECT name,currency_code FROM business_entities WHERE id=:scope"), params).mappings().first()
        check("Entity", "identity_and_defaults", root is not None and
              root["name"] == plan.snapshot.metadata.get("entity_name", scope) and root["currency_code"] == "USD")
        run = connection.execute(text("SELECT * FROM migration_runs WHERE entity_id=:scope"), params).mappings().all()
        check("Migration", "frozen_run_binding", len(run) == 1 and run[0]["id"] == plan.run_id and
              run[0]["source_snapshot_sha256"] == plan.snapshot.sha256 and
              run[0]["source_profile_key"] == plan.snapshot.binding.profile_key and
              run[0]["source_workbook_key"] == plan.snapshot.binding.workbook_key and
              run[0]["manifest_version"] == plan.report()["manifest_version"] and
              run[0]["mapping_version"] == plan.report()["mapping_version"])
        actual_mappings = [dict(row) for row in connection.execute(text(
            "SELECT source_record_kind,source_id,target_record_kind,target_id,mapping_reason,source_updated_at "
            "FROM migration_id_mappings WHERE entity_id=:scope AND run_id=:run"), params).mappings()]
        actual_mappings = [{**row, "source_updated_at": serialized(row["source_updated_at"]) or None} for row in actual_mappings]
        def mapping_key(row):
            return row["source_record_kind"], row["source_id"]
        check("Migration", "identity_and_provenance_map",
              sorted(actual_mappings, key=mapping_key) == sorted([asdict(row) for row in plan.mappings], key=mapping_key))
        checkpoints = connection.execute(text(
            "SELECT unit_key,unit_kind,unit_sha256,status FROM migration_units WHERE entity_id=:scope AND run_id=:run"), params).all()
        check("Migration", "complete_unit_checkpoints", set(checkpoints) ==
              {(unit.key, unit.kind, unit.sha256, "loaded") for unit in plan.units})
        tables = plan.snapshot.tables
        for title, table in TABLES.items():
            query = f"SELECT * FROM {table} WHERE entity_id=:scope"
            if title in {"Transactions", "JournalEntries"}:
                query += " AND projection_kind=:projection"
            actual = connection.execute(text(query), {**params, "projection":
                        "simple" if title == "Transactions" else "journal"}).mappings().all()
            source = plan.snapshot.metadata.get("documents", []) if title == "Documents" else tables[title]
            ids = {plan.target_id(title, row["storage_key"] if title == "Documents" else row["id"]) for row in source}
            check(title, "record_counts_and_identities", {row["id"] for row in actual} == ids)
        secondary_unit_failed = False
        for unit in plan.units:
            differences = unit_differences(connection, plan, unit)
            if differences and unit.kind in {"mixed_pair", "asset_history", "recurring_entry",
                                             "simple_entry_receipts", "recurring_entry_receipts"}:
                secondary_unit_failed = True
            checks.append(dict(domain=unit.kind, check="record_fields_and_relationships", passed=not differences))
            exceptions.extend(differences)

        source_journals = [{**entry, "id": plan.target_id("JournalEntries", entry["id"]),
                           "postings": sorted([row for row in tables["JournalPostings"] if row["parent_entry_id"] == entry["id"]],
                                              key=lambda row: int(row["position"]))} for entry in tables["JournalEntries"]]
        source_transactions = [{**row, "id": plan.target_id("Transactions", row["id"])} for row in tables["Transactions"]]
        self._postings(connection, params, source_transactions, source_journals, checks, exceptions)
        self._relationships(connection, plan, params, check)
        try:
            reporting_snapshot = PostgresLedgerQueryRepository(None, scope).project_ledger(connection)
        except StorageNotFoundError:
            check("Reports", "target_ledger_available", False)
        else:
            self._reports(tables, source_transactions, source_journals, calculation_records(reporting_snapshot), periods, check)
        core_passed = not any(item["domain"] in CORE for item in exceptions)
        # Shared binding/checkpoint failures invalidate both evidence groups;
        # source-owned core projections also belong to their secondary unit.
        global_failed = any(item["domain"] in {"Entity", "Migration"} for item in exceptions)
        secondary_passed = not (global_failed or secondary_unit_failed or
                                any(item["domain"] not in CORE for item in exceptions))
        secondary_present = any(tables[title] for title in ("RecurringSchedules", "MixedUseExpenses", "Assets", "Mileage")) or bool(
            plan.snapshot.metadata.get("documents"))
        return dict(reconciliation_version="1", run_id=plan.run_id, source_snapshot_sha256=plan.snapshot.sha256,
                    passed=not exceptions, core_passed=core_passed, secondary_passed=secondary_passed,
                    evidence_scope="core_and_secondary" if secondary_present else "core_only",
                    acceptance="provisional_reconciliation", whole_profile_accepted=False, cutover_authorized=False,
                    checks=checks, exceptions=exceptions,
                    normalization=["Decimal financial comparison", "UTC creation instants",
                                   "target-owned aggregate update times; original update times in mappings",
                                   "unknown historical import attribution is not invented",
                                   "document bytes remain in Google Drive"])

    @staticmethod
    def _postings(connection, params, transactions, journals, checks, exceptions):
        wanted = {}
        for kind, entries in (("simple", transactions), ("journal", journals)):
            for entry in entries:
                lines = accounting_postings([entry]) if kind == "simple" else entry["postings"]
                for position, line in enumerate(lines, 1):
                    wanted[(kind, line["id"])] = dict(
                        entry_id=entry["id"], position=position, side=line["side"], amount=line["amount"],
                        account_id=line["target_id"] if line["target_type"] == "account" else "",
                        category_id=line["target_id"] if line["target_type"] == "category" else "",
                        payee_id=line.get("payee_id", ""), description=line.get("description", ""))
        actual = {(row["projection_kind"], row["id"]): dict(row) for row in connection.execute(text(
            "SELECT * FROM postings WHERE entity_id=:scope"), params).mappings()}
        checks.append(dict(domain="Postings", check="counts_and_identities", passed=set(wanted) == set(actual)))
        if set(wanted) != set(actual):
            exceptions.append(dict(domain="Postings", fields=["counts_and_identities"]))
        for key in wanted.keys() & actual.keys():
            fields = mismatched_fields(actual[key], wanted[key])
            if fields:
                exceptions.append(dict(domain="Postings", record_key=digest(key), fields=fields))
        balances = {}
        for row in actual.values():
            balances[row["entry_id"]] = balances.get(row["entry_id"], Decimal(0)) + (
                row["amount"] if row["side"] == "Debit" else -row["amount"])
        balanced = all(amount == 0 for amount in balances.values())
        checks.append(dict(domain="Postings", check="balanced_entries", passed=balanced))
        if not balanced:
            exceptions.append(dict(domain="Postings", fields=["balanced_entries"]))

    @staticmethod
    def _relationships(connection, plan, params, check):
        tables = plan.snapshot.tables
        occurrences = []
        for title, column in (("Transactions", "entry_id"), ("MixedUseExpenses", "mixed_use_source_id")):
            for row in tables[title]:
                if row["recurring_schedule_id"] and (title != "Transactions" or not row["source_type"]):
                    occurrences.append((plan.target_id("RecurringSchedules", row["recurring_schedule_id"]),
                                        row["recurring_scheduled_date"], row["recurring_source_kind"],
                                        row["recurring_occurrence_type"], column, plan.target_id(title, row["id"])))
        actual = [(row["schedule_id"], row["scheduled_date"].isoformat(), row["source_kind"], row["occurrence_type"],
                   "entry_id" if row["entry_id"] else "mixed_use_source_id", row["entry_id"] or row["mixed_use_source_id"])
                  for row in connection.execute(text("SELECT * FROM recurring_occurrences WHERE entity_id=:scope"), params).mappings()]
        check("RecurringSchedules", "occurrence_relationships", sorted(actual) == sorted(occurrences))
        links = []
        for title, column in (("Transactions", "entry_id"), ("MixedUseExpenses", "mixed_use_source_id")):
            for row in tables[title]:
                if title == "Transactions" and row["source_type"]:
                    continue
                for position, ref in enumerate(decode_receipt_references(row["receipt_references"]), 1):
                    links.append((plan.target_id("Documents", ref["id"]), column, plan.target_id(title, row["id"]), position))
        actual = [(row["document_id"], "entry_id" if row["entry_id"] else "mixed_use_source_id",
                   row["entry_id"] or row["mixed_use_source_id"], row["position"])
                  for row in connection.execute(text("SELECT * FROM document_links WHERE entity_id=:scope"), params).mappings()]
        check("Documents", "bookkeeping_links", sorted(actual) == sorted(links))
        check("Assets", "depreciation_event_count", connection.scalar(text(
            "SELECT count(*) FROM depreciation_events WHERE entity_id=:scope"), params) ==
              sum(row["source_type"] == "depreciation" for row in tables["Transactions"]))
        check("Migration", "no_invented_import_batches", connection.scalar(text(
            "SELECT count(*) FROM import_batches WHERE entity_id=:scope"), params) == 0)

    @staticmethod
    def _reports(tables, transactions, journals, target, periods, check):
        # Existing reporting owners calculate both sides. Exact postings are
        # checked independently above, before their float presentation results.
        source = (tables["Accounts"], tables["Categories"], transactions, journals)
        for rows in (source, target):
            rows[0].sort(key=lambda row: row["id"])
            rows[1].sort(key=lambda row: row["id"])
        dates = sorted({row["txn_date"] for row in transactions + journals})
        selected = [(None, None)]
        selected.extend((date.fromisoformat(month + "-01"),
                         date.fromisoformat(month + "-" + str(calendar.monthrange(int(month[:4]), int(month[5:]))[1])))
                        for month in sorted({value[:7] for value in dates}))
        selected.extend(periods)

        def output(rows, start, end):
            accounts, categories, entries, advanced = rows
            selected_entries = [row for row in entries if (start is None or row["txn_date"] >= start.isoformat()) and
                                (end is None or row["txn_date"] <= end.isoformat())]
            selected_journals = [row for row in advanced if (start is None or row["txn_date"] >= start.isoformat()) and
                                (end is None or row["txn_date"] <= end.isoformat())]
            return dict(balances=account_balances(accounts, selected_entries, journals=selected_journals),
                        balance_sheet=balance_sheet(accounts, entries, as_of=end, journals=advanced, categories=categories),
                        profit_and_loss=profit_and_loss(entries, start=start, end=end, journals=advanced, categories=categories),
                        monthly=monthly_performance(entries, start=start, end=end, journals=advanced, categories=categories),
                        categories=[category_activity_rollups(entries, categories, kind=kind, start=start, end=end, journals=advanced)
                                    for kind in ("Income", "Expense")])

        for index, (start, end) in enumerate(selected):
            try:
                a, b = output(source, start, end), output(target, start, end)
            except (ValueError, KeyError, ArithmeticError):
                check("Reports", "period_" + str(index), False)
                continue
            # Account projection extras (baselines, target mutation instants)
            # are unrelated to balance meaning and must not enter comparison.
            for results in (a, b):
                results["balances"] = [(row["id"], row["balance"]) for row in results["balances"]]
            check("Reports", "period_" + str(index), a == b)
