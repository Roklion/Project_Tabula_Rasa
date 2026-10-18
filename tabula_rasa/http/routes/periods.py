"""Narrow accounting controls behind the normal membership and CSRF seam."""

from datetime import date

from fastapi import APIRouter, Request
from pydantic import Field

from ..baselines import required_baseline
from ..errors import ERROR_RESPONSES
from ..models.accounting import Journal, journal_response
from ..models.common import DTO
from .services import Context, service_operation


router = APIRouter(prefix='/api/v1/entities/{entity_id}', tags=['Accounting periods'], responses=ERROR_RESPONSES)


class Period(DTO):
    period_start: date
    closed: bool
    version: int


class PeriodList(DTO):
    enabled: bool
    items: list[Period]


class PeriodCommand(DTO):
    period_start: date
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=1000)


class ReversalCommand(DTO):
    correction_id: str = Field(min_length=1, max_length=200)
    reversal_entry_id: str = Field(min_length=1, max_length=200)
    txn_date: date
    reason: str = Field(min_length=1, max_length=1000)
    baseline: str


class ReversalResult(DTO):
    correction_id: str
    journal: Journal


@router.get('/accounting-periods', response_model=PeriodList, operation_id='list_accounting_periods')
def list_periods(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, 'periods') as service:
        return service.list()


def change_period(request, context, body, *, closed):
    with service_operation(request, context, 'periods') as service:
        return service.change(body.period_start, closed=closed, reason=body.reason, expected_version=body.expected_version)


@router.post('/accounting-periods/close', response_model=Period, operation_id='close_accounting_period')
def close_period(entity_id: str, body: PeriodCommand, request: Request, context: Context):
    return change_period(request, context, body, closed=True)


@router.post('/accounting-periods/unlock', response_model=Period, operation_id='unlock_accounting_period')
def unlock_period(entity_id: str, body: PeriodCommand, request: Request, context: Context):
    return change_period(request, context, body, closed=False)


@router.post('/entries/{record_id}/reverse', response_model=ReversalResult, operation_id='reverse_accounting_entry')
def reverse_entry(entity_id: str, record_id: str, body: ReversalCommand, request: Request, context: Context):
    with service_operation(request, context, 'periods') as service:
        result = service.reverse(record_id, correction_id=body.correction_id, reversal_entry_id=body.reversal_entry_id,
                                 txn_date=body.txn_date, reason=body.reason, expected=required_baseline(body.baseline))
        return ReversalResult(correction_id=result['correction_id'], journal=journal_response(result['journal']))
