from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from tabula_rasa.application.reporting_contracts import LedgerFilter

from ..errors import ERROR_RESPONSES, TransportError
from ..models.reporting import LedgerList, ReportSummary, ledger_response, report_response
from .services import Context, service_operation

router = APIRouter(prefix='/api/v1/entities/{entity_id}', tags=['Reporting'], responses=ERROR_RESPONSES)


def date_range(start, end):
    if start and end and start > end:
        raise TransportError('validation')


@router.get('/ledger', response_model=LedgerList, operation_id='query_ledger')
def query_ledger(entity_id: str, request: Request, context: Context, start: date | None = None, end: date | None = None,
                 kind: Literal['All', 'Income', 'Expense', 'Transfer', 'Journal'] = 'All',
                 account_ids: Annotated[list[str] | None, Query()] = None,
                 category_ids: Annotated[list[str] | None, Query()] = None,
                 tag_ids: Annotated[list[str] | None, Query()] = None):
    date_range(start, end)
    with service_operation(request, context, 'reporting') as service:
        return ledger_response(service.query_ledger(LedgerFilter(start=start, end=end, kind=kind,
            account_ids=tuple(account_ids or ()), category_ids=tuple(category_ids or ()), tag_ids=tuple(tag_ids or ())), force_refresh=True))


@router.get('/reports/summary', response_model=ReportSummary, operation_id='report_summary')
def report_summary(entity_id: str, request: Request, context: Context, start: date | None = None, end: date | None = None):
    date_range(start, end)
    with service_operation(request, context, 'reporting') as service:
        return report_response(service, service.read_ledger(force_refresh=True), start=start, end=end)
