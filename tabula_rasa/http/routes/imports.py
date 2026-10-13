"""Explicit file preparation and confirmed entity-scoped import commands."""

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from tabula_rasa.application.import_files import prepare_csv_import, prepare_quickbooks_import
from tabula_rasa.errors import StorageValidationError
from ..errors import ERROR_RESPONSES
from ..models.imports import (
    ImportAccountProposal, ImportCategoryProposal, ImportSummary, QuickBooksImportPreview,
    TransactionCsvPreview, TransactionImportResult,
)
from .services import Context, service_operation
from .import_upload import BINARY_UPLOAD, read_import_upload


router = APIRouter(prefix="/api/v1/entities/{entity_id}/imports", tags=["Imports"], responses=ERROR_RESPONSES)


@router.post("/csv/prepare", response_model=TransactionCsvPreview,
             operation_id="prepare_transaction_csv", openapi_extra=BINARY_UPLOAD)
async def prepare_transaction_csv(entity_id: str, request: Request, context: Context):
    try:
        prepared = await run_in_threadpool(prepare_csv_import, await read_import_upload(request))
    except StorageValidationError as error:
        # File preparation errors contain only fixed guidance and required column
        # names, so the authorized preview can display them safely.
        return TransactionCsvPreview(columns=[], source_rows=[], total_rows=0, errors=[str(error)])
    return TransactionCsvPreview(columns=prepared.columns, source_rows=prepared.rows[:20], total_rows=len(prepared.rows))


@router.post("/quickbooks/preview", response_model=QuickBooksImportPreview,
             operation_id="preview_quickbooks_transactions", openapi_extra=BINARY_UPLOAD)
async def preview_quickbooks_transactions(entity_id: str, request: Request, context: Context,
                                         filename: str = Query(min_length=1, max_length=255), auto_create: bool = False):
    content = await read_import_upload(request)

    def preview():
        try:
            prepared = prepare_quickbooks_import(filename, content)
        except StorageValidationError as error:
            return QuickBooksImportPreview(columns=[], source_rows=[], total_rows=0,
                summary=ImportSummary(ready=0, duplicates=0, Income=0, Expense=0, Transfer=0,
                                      validation_errors=1, conversion_errors=0),
                errors=[str(error)], conversion_errors=[], duplicate_rows=[], new_accounts=[], new_categories=[])
        with service_operation(request, context, "imports") as service:
            result = service.preview_quickbooks(prepared.rows, auto_create=auto_create)
        return QuickBooksImportPreview(
            columns=prepared.columns, source_rows=prepared.rows[:50], total_rows=len(prepared.rows),
            summary=ImportSummary(**result["summary"], validation_errors=len(result["errors"]),
                                  conversion_errors=len(prepared.conversion_errors)),
            errors=result["errors"], conversion_errors=prepared.conversion_errors,
            duplicate_rows=result["duplicate_rows"],
            new_accounts=[ImportAccountProposal(name=name, type=result["new_account_types"][name],
                         classification=result["new_account_classifications"][name]) for name in result["new_accounts"]],
            new_categories=[ImportCategoryProposal(name=name, kind=kind) for name, kind in result["new_categories"]],
        )
    return await run_in_threadpool(preview)


@router.post("/csv", response_model=TransactionImportResult, operation_id="import_transaction_csv", openapi_extra=BINARY_UPLOAD)
async def import_transaction_csv(entity_id: str, request: Request, context: Context):
    content = await read_import_upload(request)

    def commit():
        prepared = prepare_csv_import(content)
        with service_operation(request, context, "imports") as service:
            rows = service.import_csv(prepared.rows)
        return TransactionImportResult(imported_count=len(rows), transaction_ids=[row["id"] for row in rows])
    return await run_in_threadpool(commit)


@router.post("/quickbooks", response_model=TransactionImportResult,
             operation_id="import_quickbooks_transactions", openapi_extra=BINARY_UPLOAD)
async def import_quickbooks_transactions(entity_id: str, request: Request, context: Context,
                                        filename: str = Query(min_length=1, max_length=255), auto_create: bool = False):
    content = await read_import_upload(request)

    def commit():
        prepared = prepare_quickbooks_import(filename, content)
        if prepared.conversion_errors:
            raise StorageValidationError("Correct the QuickBooks conversion errors before submitting.")
        with service_operation(request, context, "imports") as service:
            rows = service.import_quickbooks(prepared.rows, auto_create=auto_create)
        return TransactionImportResult(imported_count=len(rows), transaction_ids=[row["id"] for row in rows])
    return await run_in_threadpool(commit)
