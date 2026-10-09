"""Canonical document IDs and same-origin bytes, independent of byte providers."""

from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from tabula_rasa.application.documents import MAX_RECEIPT_BYTES
from ..errors import ERROR_RESPONSES, TransportError
from ..models.documents import Document, DocumentLink, DocumentList, document_response
from ..models.mutations import MutationResult
from .services import Context, service_operation

router = APIRouter(prefix='/api/v1/entities/{entity_id}', tags=['Documents'], responses=ERROR_RESPONSES)


@router.get('/documents', response_model=DocumentList, operation_id='unreferenced_documents')
def unreferenced_documents(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, 'receipts') as service:
        inventory = service.unreferenced(fresh=True)
        return DocumentList(items=[document_response(doc) for doc in inventory.documents],
                            needing_integrity=inventory.needing_integrity)


@router.put('/documents/{document_id}/content', response_model=Document, operation_id='upload_document',
            openapi_extra={'requestBody': {'required': True, 'content': {
                'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
async def upload_document(entity_id: str, document_id: str, request: Request, context: Context,
                          filename: str = Query(min_length=1, max_length=255)):
    # Bound buffering before invoking the existing service validation/store.
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_RECEIPT_BYTES:
            raise TransportError('validation')
        content.extend(chunk)

    def upload():
        with request.app.state.runtime.document_upload_operation(context, document_id), \
                service_operation(request, context, 'receipts') as service:
            return document_response(service.upload(document_id, filename, bytes(content)))

    return await run_in_threadpool(upload)


@router.get('/documents/{document_id}/content', operation_id='download_document', response_class=Response,
            responses={200: {'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}})
def download_document(entity_id: str, document_id: str, request: Request, context: Context):
    with service_operation(request, context, 'receipts') as service:
        document, content = service.download(document_id)
        filename = document.metadata.original_filename or document.metadata.stored_filename
        return Response(content, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe=''),
            'X-Content-Type-Options': 'nosniff',
        })


@router.get('/transactions/{record_id}/receipts', response_model=DocumentList, operation_id='transaction_documents')
def transaction_documents(entity_id: str, record_id: str, request: Request, context: Context):
    with service_operation(request, context, 'receipts') as service:
        return DocumentList(items=[document_response(doc) for doc in service.references(record_id, fresh=True)])


@router.post('/transactions/{record_id}/receipts', response_model=MutationResult, operation_id='link_document')
def link_document(entity_id: str, record_id: str, body: DocumentLink, request: Request, context: Context):
    with service_operation(request, context, 'receipts') as service:
        service.link_document(record_id, body.document_id)
        return MutationResult(status='fully_applied')


@router.delete('/transactions/{record_id}/receipts/{document_id}', response_model=MutationResult, operation_id='unlink_document')
def unlink_document(entity_id: str, record_id: str, document_id: str, request: Request, context: Context):
    with service_operation(request, context, 'receipts') as service:
        service.unlink_document(record_id, document_id)
        return MutationResult(status='fully_applied')
