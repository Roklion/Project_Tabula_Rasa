"""Bounded relational reads and native plans on a synthetic beta-sized ledger."""

from sqlalchemy import event, text

from tabula_rasa.infrastructure.postgres.reporting import (
    JOURNAL_POSTINGS_SQL, RECEIPT_COUNTS_SQL, SIMPLE_ENTRIES_SQL, SIMPLE_TAGS_SQL,
)
from tests.postgres.core_support import seed_core


def seed_beta_ledgers(database):
    services = seed_core(database)
    with database.transaction() as connection:
        for scope in ('alpha', 'beta'):
            params = {'scope': scope}
            connection.execute(text("""INSERT INTO tags(entity_id,id,incarnation_id,name,name_key)
                VALUES (:scope,'tag','tag','Synthetic tag','synthetic tag')"""), params)
            connection.execute(text("""INSERT INTO entries(entity_id,id,incarnation_id,txn_date,projection_kind,simple_kind)
                SELECT :scope,'entry-'||n,'entry-'||n,DATE '2026-01-01'+(n%365),
                       CASE WHEN n<=2000 THEN 'simple' ELSE 'journal' END,
                       CASE WHEN n<=2000 THEN 'Income' END
                FROM generate_series(1,2200) n"""), params)
            connection.execute(text("""INSERT INTO postings(entity_id,id,entry_id,projection_kind,position,side,amount,account_id,category_id)
                SELECT e.entity_id,e.id||chr(58)||p.position,e.id,e.projection_kind,p.position,p.side,10.00,
                       CASE WHEN p.position=1 THEN 'cash' END,CASE WHEN p.position=2 THEN 'sales' END
                FROM entries e CROSS JOIN (VALUES (1,'Debit'),(2,'Credit')) p(position,side)
                WHERE e.entity_id=:scope"""), params)
            connection.execute(text("""INSERT INTO entry_tags(entity_id,entry_id,tag_id)
                SELECT :scope,'entry-'||n,'tag' FROM generate_series(4,2000,4) n"""), params)
            connection.execute(text("""INSERT INTO documents(entity_id,id,incarnation_id,stored_filename,store_kind,storage_key)
                SELECT :scope,'document-'||n,'document-'||n,'synthetic.pdf','synthetic','document-'||n
                FROM generate_series(10,2000,10) n"""), params)
            connection.execute(text("""INSERT INTO document_links(entity_id,document_id,entry_id,position)
                SELECT :scope,'document-'||n,'entry-'||n,1 FROM generate_series(10,2000,10) n"""), params)
    return services


def test_snapshot_query_count_and_plans_at_beta_scale(database):
    alpha, beta = seed_beta_ledgers(database)
    # Statistics reflect both entities; planner choices are not forced by
    # enable_seqscan or exact node assertions that change with server versions.
    with database.transaction() as connection:
        for table in ('entries', 'postings', 'payees', 'tags', 'entry_tags', 'mixed_use_tags',
                      'recurring_occurrences', 'document_links'):
            connection.execute(text(f'ANALYZE {table}'))
    statements = []

    def count_reads(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith('SELECT'):
            statements.append(statement)

    event.listen(database.engine, 'before_cursor_execute', count_reads)
    try:
        snapshot = alpha.reporting.read_ledger()
    finally:
        event.remove(database.engine, 'before_cursor_execute', count_reads)
    assert len(snapshot.transactions) == 2000 and len(snapshot.journals) == 200
    assert len(statements) <= 8  # A fixed query budget, independent of entry count.
    assert sum(row.receipt_count for row in snapshot.transactions) == 200
    assert sum(bool(row.tag_ids) for row in snapshot.transactions) == 500
    assert alpha.reporting.period_report(snapshot).totals == {'income': 22000.0, 'expenses': 0.0, 'net': 22000.0}
    assert beta.reporting.period_report(beta.reporting.read_ledger()).totals['income'] == 22000.0

    with database.transaction(read_only=True) as connection:
        indexes = dict(connection.execute(text("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public'")).all())
        for name, keys in {
            'ix_entries_projection_date': '(entity_id, projection_kind, txn_date, id)',
            'uq_postings_entry_id_position': '(entity_id, entry_id, "position")',
            'ix_postings_account_entry': '(entity_id, account_id, entry_id)',
            'ix_postings_category_entry': '(entity_id, category_id, entry_id)',
            'ix_entry_tags_reverse': '(entity_id, tag_id, entry_id)',
            'ix_mixed_use_tags_reverse': '(entity_id, tag_id, source_id)',
        }.items():
            assert keys in indexes[name]
        for sql, rows in ((SIMPLE_ENTRIES_SQL, 2000), (SIMPLE_TAGS_SQL, 500),
                          (RECEIPT_COUNTS_SQL, 200), (JOURNAL_POSTINGS_SQL, 400)):
            plan = connection.scalar(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql), {'scope': 'alpha'})[0]
            assert plan['Plan']['Actual Rows'] == rows
            assert plan['Plan']['Actual Loops'] == 1
            assert plan['Plan']['Shared Hit Blocks'] > 0
