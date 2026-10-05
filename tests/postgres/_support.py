"""Synthetic records; never load profiles or application secrets."""

from sqlalchemy import text


def entity(connection, scope="alpha"):
    connection.execute(text("INSERT INTO business_entities(id,name,incarnation_id) VALUES (:id,:id,:id)"), {"id": scope})


def account(connection, scope="alpha", account_id="cash", *, parent=None, classification="Asset"):
    connection.execute(text("""INSERT INTO accounts(entity_id,id,name,name_key,type,classification,incarnation_id,parent_id)
        VALUES (:scope,:id,:id,:id,'Other',:classification,:id,:parent)"""),
        {"scope": scope, "id": account_id, "classification": classification, "parent": parent})


def category(connection, scope="alpha", category_id="sales", *, kind="Income"):
    connection.execute(text("""INSERT INTO categories(entity_id,id,name,name_key,kind,incarnation_id)
        VALUES (:scope,:id,:id,:id,:kind,:id)"""), {"scope": scope, "id": category_id, "kind": kind})


def simple_entry(connection, scope="alpha", entry_id="income", *, amount="10.00", category_id="sales"):
    connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,simple_kind)
        VALUES (:scope,:id,:id,'2026-10-05','simple','Income')"""), {"scope": scope, "id": entry_id})
    connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id,category_id)
        VALUES (:scope,:id||chr(58)||'1',:id,'simple',1,'Debit',:amount,'cash',NULL),
               (:scope,:id||chr(58)||'2',:id,'simple',2,'Credit',:amount,NULL,:category)"""),
        {"scope": scope, "id": entry_id, "amount": amount, "category": category_id})


def ledger(connection):
    entity(connection)
    account(connection)
    category(connection)
