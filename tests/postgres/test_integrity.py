from decimal import Decimal

import pytest
from sqlalchemy import text

from tabula_rasa.infrastructure.postgres.runtime import DatabaseError
from tests.postgres._support import account, category, entity, ledger, simple_entry


def test_simple_postings_commit_as_one_complete_entry(database):
    with database.transaction() as connection:
        ledger(connection)
        simple_entry(connection, amount="12.34")
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT sum(amount) FROM postings")) == Decimal("24.68")
        assert connection.scalar(text("SELECT projection_kind FROM entries")) == "simple"
        assert connection.scalar(text("SELECT opening_balance FROM accounts")) == Decimal("0")


@pytest.mark.parametrize("change", [
    "DELETE FROM postings WHERE position = 2", "UPDATE postings SET amount = 9 WHERE position = 2",
    "UPDATE postings SET side = 'Debit' WHERE position = 2", "UPDATE postings SET position = 3 WHERE position = 2",
    "UPDATE postings SET category_id = NULL, account_id = 'cash' WHERE position = 2",
    "UPDATE categories SET kind = 'Expense'",
    "UPDATE entries SET projection_kind = 'journal', simple_kind = NULL",
    "UPDATE accounts SET incarnation_id = 'different'",
])
def test_invalid_direct_mutations_roll_back_at_boundary(database, change):
    with database.transaction() as connection:
        ledger(connection)
        simple_entry(connection)
    with pytest.raises(DatabaseError, match="invariant"):
        with database.transaction() as connection:
            connection.execute(text(change))
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM postings")) == 2


@pytest.mark.parametrize("amount", ["0", "NaN", "-1", "1e28"])
def test_invalid_money_cannot_commit(database, amount):
    with pytest.raises(DatabaseError):
        with database.transaction() as connection:
            ledger(connection)
            simple_entry(connection, amount=amount)


def test_empty_entry_cannot_commit(database):
    with pytest.raises(DatabaseError, match="invariant"):
        with database.transaction() as connection:
            entity(connection)
            connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind)
                VALUES ('alpha','journal','journal','2026-10-05','journal')"""))


def test_two_entities_may_share_ids_but_never_references(database):
    with database.transaction() as connection:
        for scope in ["alpha", "beta"]:
            entity(connection, scope)
            account(connection, scope)
        category(connection, "beta", "beta-sales")
        account(connection, "beta", "beta-only")
    with pytest.raises(DatabaseError, match="reference"):
        with database.transaction() as connection:
            account(connection, "alpha", "alpha-child", parent="beta-only")
    with pytest.raises(DatabaseError):
        with database.transaction() as connection:
            simple_entry(connection, "alpha", category_id="beta-sales")
    with database.transaction() as connection:
        category(connection, "alpha", "alpha-sales")
        simple_entry(connection, "alpha", category_id="alpha-sales")
        simple_entry(connection, "beta", category_id="beta-sales")
    with database.transaction(read_only=True) as connection:
        assert connection.execute(text("SELECT entity_id,count(*) FROM entries GROUP BY entity_id ORDER BY entity_id")).all() == [("alpha",1),("beta",1)]


def test_hierarchy_parent_changes_revalidate_children(database):
    with database.transaction() as connection:
        entity(connection)
        account(connection, account_id="parent")
        account(connection, account_id="child", parent="parent")
        account(connection, account_id="other")
    with pytest.raises(DatabaseError, match="invariant"):
        with database.transaction() as connection:
            connection.execute(text("UPDATE accounts SET parent_id = 'other' WHERE id = 'parent'"))
    with pytest.raises(DatabaseError, match="invariant"):
        with database.transaction() as connection:
            connection.execute(text("UPDATE accounts SET classification = 'Equity' WHERE id = 'parent'"))


def test_signed_openings_and_entity_local_name_uniqueness(database):
    with database.transaction() as connection:
        entity(connection)
        account(connection, classification="Equity")
        connection.execute(text("UPDATE accounts SET opening_balance = -100.25"))
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT opening_balance FROM accounts")) == Decimal("-100.25")
    with pytest.raises(DatabaseError, match="duplicate"):
        with database.transaction() as connection:
            connection.execute(text("""INSERT INTO accounts(entity_id,id,incarnation_id,name,name_key,type,classification)
                VALUES ('alpha','duplicate','duplicate','Cash','cash','Other','Asset')"""))


def test_journal_preserves_separate_posting_namespace_and_balanced_lines(database):
    with database.transaction() as connection:
        ledger(connection)
        simple_entry(connection)
        connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind)
            VALUES ('alpha','journal','journal','2026-10-05','journal')"""))
        # Original journal posting IDs may coincide with simple-derived IDs.
        connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id)
            VALUES ('alpha',:first,'journal','journal',1,'Debit',2,'cash'),
                   ('alpha',:second,'journal','journal',2,'Credit',2,'cash')"""),
            {"first": "income:1", "second": "income:2"})
    with database.transaction(read_only=True) as connection:
        assert connection.scalar(text("SELECT count(*) FROM postings")) == 4
        assert connection.scalar(text("SELECT count(*) FROM entries WHERE projection_kind = 'journal'")) == 1
    with pytest.raises(DatabaseError, match="invariant"):
        with database.transaction() as connection:
            connection.execute(text("UPDATE postings SET amount = 0 WHERE projection_kind = 'journal'"))
