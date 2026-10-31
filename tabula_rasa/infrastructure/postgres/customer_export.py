"""Customer delivery composition reuses the canonical snapshot and audit writer."""

from sqlalchemy import text

from tabula_rasa.application.customer_export import CustomerExportService, MAX_EXPORT_BYTES, MAX_EXPORT_RECORDS
from tabula_rasa.application.entity_export import EntityExportService, ExportError
from tabula_rasa.bookkeeping_export.schema import DOMAINS
from .entity_export import PostgresEntityExportRepository
from .operations import repository_operation


class CustomerSnapshot(PostgresEntityExportRepository):
    def __init__(self, database, entity_id):
        super().__init__(database, entity_id)
        self.history_boundary = {}

    def read_export(self):
        with repository_operation(self.database, read_only=True, require_outer=True) as connection:
            # Reject oversized supported snapshots before materializing canonical rows.
            total = 0
            size = 0
            for name in DOMAINS:
                field = 'id' if name == 'business_entities' else 'entity_id'
                count, byte_size = connection.execute(text(
                    f'SELECT count(*), COALESCE(sum(pg_column_size(t)),0) FROM {name} t WHERE {field}=:scope'
                ), {'scope': self.entity_id}).one()
                total += count
                size += byte_size
                if total > MAX_EXPORT_RECORDS or size > MAX_EXPORT_BYTES:
                    raise ExportError('export_limit')
            activated = connection.scalar(text('SELECT activated_at FROM audit_activation'))
            self.history_boundary.update({
                'activated_at': activated.isoformat() if activated else None,
                'pre_activation_history': 'unavailable',
                'mutation_history': 'excluded',
            })
            return self.read_snapshot(connection)


def prepare_customer_export(runtime, context, include_documents):
    snapshot = CustomerSnapshot(runtime.database, context.entity_id)
    receipts = runtime.services(context).receipts if include_documents else None
    # Snapshot and boundary are captured together by the canonical export owner;
    # no audit contents leave this adapter.
    return CustomerExportService(EntityExportService(snapshot), receipts, context.entity_id).prepare(
        include_documents=include_documents, history_boundary=snapshot.history_boundary)


def record_export(database, entity_id, request_id, status):
    with repository_operation(database) as connection:
        connection.execute(text('''INSERT INTO customer_export_actions(entity_id,id,status)
            VALUES (:scope,:id,:status)'''),
            {'scope': entity_id, 'id': request_id + ':' + status, 'status': status})
