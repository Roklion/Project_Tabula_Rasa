"""One transactional period policy; reversals reuse the canonical journal writer."""

from sqlalchemy import text

from tabula_rasa.errors import StorageConflictError, StorageValidationError
from tabula_rasa.ledger_validation import iso_date
from .accounting import PostgresJournalRepository
from .concurrency import check_baseline
from .repository import EntityRepository, insert


class PostgresPeriodRepository(EntityRepository):
    def gate(self, connection):
        connection.execute(text('SELECT pg_advisory_xact_lock(336,hashtext(:scope))'), {'scope': self.entity_id})

    def configure(self, *, enabled, reason):
        """Explicit trusted operator only. Existing periods survive disabling."""
        from tabula_rasa.application.periods import PeriodService
        if type(enabled) is not bool:
            raise StorageValidationError('Invalid period policy.')
        reason = PeriodService.reason(reason)
        with self.operation() as connection:
            self.gate(connection)
            connection.execute(text("SELECT require_period_authority(:scope,'configure')"), {'scope': self.entity_id})
            connection.execute(text('''INSERT INTO accounting_period_policy(entity_id,enabled,reason)
                VALUES (:scope,:enabled,:reason) ON CONFLICT(entity_id) DO UPDATE
                SET enabled=EXCLUDED.enabled,reason=EXCLUDED.reason
                WHERE accounting_period_policy.enabled IS DISTINCT FROM EXCLUDED.enabled
                   OR accounting_period_policy.reason IS DISTINCT FROM EXCLUDED.reason'''),
                {'scope': self.entity_id, 'enabled': enabled, 'reason': reason})

    def list(self):
        with self.operation(read_only=True) as connection:
            enabled = bool(connection.scalar(text('SELECT enabled FROM accounting_period_policy WHERE entity_id=:scope'),
                                             {'scope': self.entity_id}))
            periods = [dict(row) for row in connection.execute(text('''SELECT period_start,closed,version
                FROM accounting_periods WHERE entity_id=:scope ORDER BY period_start DESC LIMIT 1200'''),
                {'scope': self.entity_id}).mappings()]
            return {'enabled': enabled, 'items': periods}

    def change(self, month, *, closed, reason, expected_version):
        with self.operation() as connection:
            self.gate(connection)
            params = {'scope': self.entity_id, 'month': month, 'closed': closed, 'reason': reason}
            connection.execute(text('SELECT require_period_authority(:scope,:action)'),
                               {'scope': self.entity_id, 'action': 'close' if closed else 'unlock'})
            if not connection.scalar(text('SELECT enabled FROM accounting_period_policy WHERE entity_id=:scope'),
                                     {'scope': self.entity_id}):
                raise StorageConflictError('Accounting period enforcement is disabled.')
            current = connection.execute(text('SELECT * FROM accounting_periods WHERE entity_id=:scope AND period_start=:month'),
                                         params).mappings().first()
            if current and current['closed'] == closed and current['reason'] == reason:
                return {key: current[key] for key in ('period_start', 'closed', 'version')}
            if expected_version != (current['version'] if current else 0):
                raise StorageConflictError('The accounting period changed. Reload before trying again.', code='stale')
            return dict(connection.execute(text('''INSERT INTO accounting_periods(entity_id,period_start,closed,reason)
                VALUES (:scope,:month,:closed,:reason) ON CONFLICT(entity_id,period_start) DO UPDATE
                SET closed=EXCLUDED.closed,reason=EXCLUDED.reason RETURNING period_start,closed,version'''), params).mappings().one())

    def reverse(self, original_entry_id, *, correction_id, reversal_entry_id, txn_date, reason, expected):
        day = iso_date(txn_date)
        journal = PostgresJournalRepository(self.database, self.entity_id)
        with self.operation() as connection:
            # Acquire the shared accounting gate before root/reference locks.
            connection.execute(text('SELECT pg_advisory_xact_lock_shared(336,hashtext(:scope))'), {'scope': self.entity_id})
            connection.execute(text("SELECT require_period_authority(:scope,'correct')"), {'scope': self.entity_id})
            journal.references(connection, lock=True, entry_ids=[original_entry_id])
            row = journal.get_row(connection, 'entries', original_entry_id)
            previous = connection.execute(text('SELECT * FROM entry_corrections WHERE entity_id=:scope AND id=:id'),
                                          {'scope': self.entity_id, 'id': correction_id}).mappings().first()
            if previous:
                reversal = journal.entry(connection, previous['reversal_entry_id'])
                if (previous['original_entry_id'] != original_entry_id or previous['reversal_entry_id'] != reversal_entry_id
                        or previous['reason'] != reason or reversal['txn_date'].isoformat() != day):
                    raise StorageConflictError('The correction identity is already in use.')
                return {'correction_id': correction_id, 'journal': journal.project(connection, reversal)}
            check_baseline(journal.key('entries', original_entry_id), row,
                           expected.get('baseline') if isinstance(expected, dict) else None, required=True)
            if row['mixed_use_source_id'] or row['depreciation_asset_id']:
                raise StorageValidationError('Unlock the period and correct this entry through its source workflow.')
            if original_entry_id == reversal_entry_id:
                raise StorageValidationError('A reversal requires a distinct entry identity.')
            lines = [dict(id=f'{reversal_entry_id}:{i}', target_type='account' if line['account_id'] else 'category',
                          target_id=line['account_id'] or line['category_id'],
                          side='Credit' if line['side'] == 'Debit' else 'Debit', amount=line['amount'],
                          payee_id=line['payee_id'] or '')
                     for i, line in enumerate(journal.lines(connection, original_entry_id), 1)]
            result = journal.create(entry_id=reversal_entry_id, txn_date=day,
                                    description='Reversal', postings=lines)
            insert(connection, 'entry_corrections', dict(entity_id=self.entity_id, id=correction_id,
                original_entry_id=original_entry_id, reversal_entry_id=reversal_entry_id, reason=reason))
            return {'correction_id': correction_id, 'journal': result}
