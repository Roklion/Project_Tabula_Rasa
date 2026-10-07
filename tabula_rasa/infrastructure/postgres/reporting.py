"""Entity-scoped relational reads for the persistence-neutral reporting port."""

from collections import defaultdict
from itertools import groupby

from sqlalchemy import text

from tabula_rasa.application.reporting_contracts import (
    LedgerJournal, LedgerPosting, LedgerSnapshot, LedgerTransaction,
    ReportingAccount, ReportingCategory,
)
from tabula_rasa.errors import StorageNotFoundError
from .operations import repository_operation
from .repository import EntityRepository, serialized


# Simple entries have exactly two ordered postings, enforced at commit. Their
# canonical postings never enter the journal projection below.
SIMPLE_ENTRIES_SQL = """
    SELECT e.id, e.txn_date, e.simple_kind, e.description, e.reference,
           e.created_at, e.payee_id, payee.name AS payee,
           e.mixed_use_source_id, e.depreciation_asset_id,
           debit.amount, debit.account_id AS debit_account_id,
           credit.account_id AS credit_account_id,
           COALESCE(debit.category_id, credit.category_id) AS category_id,
           COALESCE(ordinary.schedule_id, mixed.schedule_id) AS schedule_id,
           COALESCE(ordinary.scheduled_date, mixed.scheduled_date) AS scheduled_date,
           COALESCE(ordinary.source_kind, mixed.source_kind) AS source_kind,
           COALESCE(ordinary.occurrence_type, mixed.occurrence_type) AS occurrence_type
    FROM entries e
    JOIN postings debit ON debit.entity_id=e.entity_id AND debit.entry_id=e.id
        AND debit.projection_kind=e.projection_kind AND debit.position=1
    JOIN postings credit ON credit.entity_id=e.entity_id AND credit.entry_id=e.id
        AND credit.projection_kind=e.projection_kind AND credit.position=2
    LEFT JOIN payees payee ON payee.entity_id=e.entity_id AND payee.id=e.payee_id
    LEFT JOIN recurring_occurrences ordinary ON ordinary.entity_id=e.entity_id
        AND ordinary.entry_id=e.id
    LEFT JOIN recurring_occurrences mixed ON mixed.entity_id=e.entity_id
        AND mixed.mixed_use_source_id=e.mixed_use_source_id
    WHERE e.entity_id=:scope AND e.projection_kind='simple'
    ORDER BY e.txn_date DESC, e.created_at DESC, e.id DESC
"""

SIMPLE_TAGS_SQL = """
    SELECT e.id AS entry_id, t.id, t.name
    FROM entries e
    JOIN entry_tags link ON link.entity_id=e.entity_id AND link.entry_id=e.id
    JOIN tags t ON t.entity_id=link.entity_id AND t.id=link.tag_id
    WHERE e.entity_id=:scope AND e.projection_kind='simple'
        AND e.mixed_use_source_id IS NULL
    UNION ALL
    SELECT e.id AS entry_id, t.id, t.name
    FROM entries e
    JOIN mixed_use_tags link ON link.entity_id=e.entity_id
        AND link.source_id=e.mixed_use_source_id
    JOIN tags t ON t.entity_id=link.entity_id AND t.id=link.tag_id
    WHERE e.entity_id=:scope AND e.projection_kind='simple'
    ORDER BY entry_id, id
"""

RECEIPT_COUNTS_SQL = """
    SELECT entry_id, mixed_use_source_id, count(*) AS receipt_count
    FROM document_links WHERE entity_id=:scope
    GROUP BY entry_id, mixed_use_source_id
"""

JOURNAL_POSTINGS_SQL = """
    SELECT e.id AS entry_id, e.txn_date, e.description AS entry_description,
           e.created_at, e.updated_at, p.id, p.position, p.account_id,
           p.category_id, p.side, p.amount, p.payee_id, payee.name AS payee,
           p.description
    FROM entries e
    JOIN postings p ON p.entity_id=e.entity_id AND p.entry_id=e.id
        AND p.projection_kind=e.projection_kind
    LEFT JOIN payees payee ON payee.entity_id=p.entity_id AND payee.id=p.payee_id
    WHERE e.entity_id=:scope AND e.projection_kind='journal'
    ORDER BY e.txn_date DESC, e.created_at DESC, e.id DESC, p.position
"""


class PostgresLedgerQueryRepository(EntityRepository):
    """Return native projections from one committed REPEATABLE READ snapshot.

    Reads are batched by relation, without per-entry queries or a process cache.
    Filtering and financial calculations remain in ReportingService/domain code.
    """

    def read_ledger(self, *, force_refresh: bool = False) -> LedgerSnapshot:
        # A nested mutation uses READ COMMITTED and may contain incomplete,
        # uncommitted aggregates. Refuse it instead of weakening this contract.
        with repository_operation(self.database, read_only=True, require_outer=True) as connection:
            return self.project_ledger(connection)

    def project_ledger(self, connection):
        """Project a caller-owned coherent read snapshot (migration tooling)."""
        params = {'scope': self.entity_id}
        if connection.scalar(text('SELECT id FROM business_entities WHERE id=:scope'), params) is None:
            raise StorageNotFoundError('The selected business entity does not exist.')
        accounts = tuple(sorted((
            ReportingAccount(
                id=row['id'], name=row['name'], type=row['type'],
                classification=row['classification'], opening_balance=row['opening_balance'],
                active=row['active'], parent_id=row['parent_id'] or '',
            )
            for row in connection.execute(text(
                'SELECT id,name,type,classification,opening_balance,active,parent_id '
                'FROM accounts WHERE entity_id=:scope ORDER BY id'
            ), params).mappings()
        ), key=lambda row: row.name.casefold()))
        categories = tuple(sorted((
            ReportingCategory(
                id=row['id'], name=row['name'], kind=row['kind'], parent_id=row['parent_id'] or '',
            )
            for row in connection.execute(text(
                'SELECT id,name,kind,parent_id FROM categories WHERE entity_id=:scope ORDER BY id'
            ), params).mappings()
        ), key=lambda row: (row.kind, row.name.casefold())))
        transactions = self._transactions(connection, params)
        journals = self._journals(connection, params)
        return LedgerSnapshot(accounts, categories, transactions, journals)

    @staticmethod
    def _transactions(connection, params):
        tags = defaultdict(list)
        for row in connection.execute(text(SIMPLE_TAGS_SQL), params).mappings():
            tags[row['entry_id']].append((row['id'], row['name']))
        receipts = {
            (row['entry_id'], row['mixed_use_source_id']): row['receipt_count']
            for row in connection.execute(text(RECEIPT_COUNTS_SQL), params).mappings()
        }
        return tuple(
            LedgerTransaction(
                id=row['id'], date=row['txn_date'], kind=row['simple_kind'], amount=row['amount'],
                account_id=(row['debit_account_id'] if row['simple_kind'] == 'Income'
                            else row['credit_account_id']),
                to_account_id=row['debit_account_id'] if row['simple_kind'] == 'Transfer' else '',
                category_id=row['category_id'] or '', payee_id=row['payee_id'] or '',
                payee=row['payee'] or '', description=row['description'], reference=row['reference'],
                created_at=serialized(row['created_at']),
                tag_ids=tuple(identity for identity, _ in tags[row['id']]),
                tags=tuple(name for _, name in tags[row['id']]),
                receipt_count=receipts.get(
                    (None, row['mixed_use_source_id']) if row['mixed_use_source_id'] else (row['id'], None), 0,
                ),
                source_type=('mixed_use_expense' if row['mixed_use_source_id'] else
                             'depreciation' if row['depreciation_asset_id'] else ''),
                source_id=row['mixed_use_source_id'] or row['depreciation_asset_id'] or '',
                recurring_schedule_id=row['schedule_id'] or '',
                recurring_scheduled_date=row['scheduled_date'],
                recurring_source_kind=row['source_kind'] or '',
                recurring_occurrence_type=row['occurrence_type'] or '',
            )
            for row in connection.execute(text(SIMPLE_ENTRIES_SQL), params).mappings()
        )

    @staticmethod
    def _journals(connection, params):
        journals = []
        for identity, lines in groupby(
            connection.execute(text(JOURNAL_POSTINGS_SQL), params).mappings(),
            key=lambda row: row['entry_id'],
        ):
            lines = list(lines)
            header = lines[0]
            journals.append(LedgerJournal(
                id=identity, date=header['txn_date'], description=header['entry_description'],
                created_at=serialized(header['created_at']), updated_at=serialized(header['updated_at']),
                postings=tuple(LedgerPosting(
                    id=line['id'], position=line['position'], side=line['side'], amount=line['amount'],
                    target_type='account' if line['account_id'] is not None else 'category',
                    target_id=line['account_id'] or line['category_id'], payee_id=line['payee_id'] or '',
                    payee=line['payee'] or '', description=line['description'],
                ) for line in lines),
            ))
        return tuple(journals)
