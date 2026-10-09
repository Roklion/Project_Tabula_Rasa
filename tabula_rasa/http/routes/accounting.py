from fastapi import APIRouter, Request

from ..baselines import required_baseline
from ..errors import ERROR_RESPONSES
from ..models.accounting import (
    Journal, JournalCreate, JournalList, JournalUpdate, Transaction, TransactionCreate, TransactionList, TransactionUpdate,
    journal_response, transaction_response,
)
from ..models.mutations import MutationResult, ProtectedMutation
from .services import Context, service_operation

transactions = APIRouter(prefix='/api/v1/entities/{entity_id}/transactions', tags=['Transactions'], responses=ERROR_RESPONSES)
journals = APIRouter(prefix='/api/v1/entities/{entity_id}/journals', tags=['Journals'], responses=ERROR_RESPONSES)


@transactions.post('', response_model=Transaction, status_code=201, operation_id='create_transaction')
def create_transaction(entity_id: str, body: TransactionCreate, request: Request, context: Context):
    with service_operation(request, context, 'transactions') as service:
        return transaction_response(service.create(**body.model_dump()))


@journals.post('', response_model=Journal, status_code=201, operation_id='create_journal')
def create_journal(entity_id: str, body: JournalCreate, request: Request, context: Context):
    with service_operation(request, context, 'journals') as service:
        return journal_response(service.create(**body.model_dump()))


@transactions.get('', response_model=TransactionList, operation_id='list_transactions')
def list_transactions(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, 'transactions') as service:
        return TransactionList(items=[transaction_response(row) for row in service.list(fresh=True)])


@transactions.patch('/{record_id}', response_model=Transaction, operation_id='update_transaction')
def update_transaction(entity_id: str, record_id: str, body: TransactionUpdate, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    with service_operation(request, context, 'transactions') as service:
        return transaction_response(service.update(record_id, expected=expected, **body.changes.model_dump(exclude_unset=True)))


@transactions.delete('/{record_id}', response_model=MutationResult, operation_id='delete_transaction')
def delete_transaction(entity_id: str, record_id: str, body: ProtectedMutation, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    with service_operation(request, context, 'transactions') as service:
        service.delete(record_id, expected=expected)
        return MutationResult(status='fully_applied')


@journals.get('', response_model=JournalList, operation_id='list_journals')
def list_journals(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, 'journals') as service:
        return JournalList(items=[journal_response(row) for row in service.list(fresh=True)])


@journals.patch('/{record_id}', response_model=Journal, operation_id='update_journal')
def update_journal(entity_id: str, record_id: str, body: JournalUpdate, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    with service_operation(request, context, 'journals') as service:
        return journal_response(service.update(record_id, expected=expected, **body.changes.model_dump(exclude_unset=True)))


@journals.delete('/{record_id}', response_model=MutationResult, operation_id='delete_journal')
def delete_journal(entity_id: str, record_id: str, body: ProtectedMutation, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    with service_operation(request, context, 'journals') as service:
        service.delete(record_id, expected=expected)
        return MutationResult(status='fully_applied')
