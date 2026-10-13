"""QuickBooks mileage upload adapters; the existing service owns import rules."""

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from tabula_rasa.application.import_files import read_csv_upload
from ..errors import ERROR_RESPONSES
from ..models.mileage_imports import MileageImportPreview, MileageImportResult
from .import_upload import BINARY_UPLOAD, read_import_upload
from .services import Context, service_operation

router = APIRouter(prefix='/api/v1/entities/{entity_id}/imports/quickbooks-mileage',
                   tags=['Imports'], responses=ERROR_RESPONSES)


@router.post('/preview', response_model=MileageImportPreview,
             operation_id='preview_quickbooks_mileage', openapi_extra=BINARY_UPLOAD)
async def preview_mileage(entity_id: str, request: Request, context: Context):
    content = await read_import_upload(request)

    def preview():
        rows = read_csv_upload(content)
        with service_operation(request, context, 'mileage') as service:
            prepared = service.preview_quickbooks_mileage(rows, fresh=True).as_record()
            prepared['rows'] = prepared['rows'][:50]
            return MileageImportPreview(**prepared, source_rows=rows[:50])

    return await run_in_threadpool(preview)


@router.post('', response_model=MileageImportResult,
             operation_id='import_quickbooks_mileage', openapi_extra=BINARY_UPLOAD)
async def import_mileage(entity_id: str, request: Request, context: Context):
    content = await read_import_upload(request)

    def commit():
        rows = read_csv_upload(content)
        with service_operation(request, context, 'mileage') as service:
            trips = service.import_quickbooks_mileage(rows)
            return MileageImportResult(imported=len(trips), ids=[trip.id for trip in trips])

    return await run_in_threadpool(commit)
