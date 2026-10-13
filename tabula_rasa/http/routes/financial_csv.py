"""Thin read-capability adapters for the three retained financial CSV actions."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from starlette.responses import Response

from tabula_rasa.application.financial_csv import financial_csv_exports, selected_ledger_csv
from tabula_rasa.application.reporting_contracts import LedgerFilter

from ..errors import ERROR_RESPONSES
from .reporting import date_range
from .services import Context, service_operation

CSV_RESPONSE = {200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}}
router = APIRouter(prefix="/api/v1/entities/{entity_id}", tags=["Financial CSV"], responses=ERROR_RESPONSES)


def csv_response(content, filename):
    return Response(content, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/exports/transactions.csv", operation_id="download_transactions_csv",
            response_class=Response, responses=CSV_RESPONSE)
def transactions_csv(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, "reporting") as service:
        content = financial_csv_exports(service.read_ledger(force_refresh=True))["transactions"]
        return csv_response(content, f"tabula-rasa-{date.today()}.csv")


@router.get("/exports/journal-postings.csv", operation_id="download_journal_postings_csv",
            response_class=Response, responses=CSV_RESPONSE)
def journal_postings_csv(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, "reporting") as service:
        content = financial_csv_exports(service.read_ledger(force_refresh=True))["journals"]
        return csv_response(content, f"tabula-rasa-journals-{date.today()}.csv")


@router.get("/ledger/selected.csv", operation_id="download_selected_ledger_csv",
            response_class=Response, responses=CSV_RESPONSE)
def selected_csv(entity_id: str, request: Request, context: Context,
                 entry_ids: Annotated[list[str] | None, Query()] = None,
                 start: date | None = None, end: date | None = None,
                 kind: Literal["All", "Income", "Expense", "Transfer", "Journal"] = "All",
                 account_ids: Annotated[list[str] | None, Query()] = None,
                 category_ids: Annotated[list[str] | None, Query()] = None,
                 tag_ids: Annotated[list[str] | None, Query()] = None):
    date_range(start, end)
    with service_operation(request, context, "reporting") as service:
        query = service.query_ledger(LedgerFilter(start=start, end=end, kind=kind,
            account_ids=tuple(account_ids or ()), category_ids=tuple(category_ids or ()),
            tag_ids=tuple(tag_ids or ())), force_refresh=True)
        return csv_response(selected_ledger_csv(query, entry_ids or ()),
                            f"tabula-rasa-selected-{date.today()}.csv")
