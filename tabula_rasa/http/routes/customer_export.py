"""Session-bound, bounded synchronous delivery; no retained download credential."""

from threading import BoundedSemaphore
from typing import Literal

from fastapi import APIRouter, Request
from starlette.responses import StreamingResponse

from tabula_rasa.application.identity import IdentityError
from ..context import resolve_context
from ..errors import ERROR_RESPONSES, TransportError
from ..models.common import DTO
from .services import Context

router = APIRouter(prefix='/api/v1/entities/{entity_id}', tags=['Customer export'], responses=ERROR_RESPONSES)
_slots = BoundedSemaphore(2)


class CustomerExportRequest(DTO):
    scope: Literal['metadata_only', 'documents_inclusive']


class PrivateExportResponse(StreamingResponse):
    """Keep quota and the anonymous handle until delivery or cancellation ends."""

    def __init__(self, stream):
        self.stream = stream
        def chunks():
            while content := stream.read(64 * 1024):
                yield content
        super().__init__(chunks(), media_type='application/zip', headers={
            'Content-Disposition': 'attachment; filename="tabula-rasa-handoff.zip"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        })

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.stream.close()
            _slots.release()


@router.post('/exports/handoff', operation_id='download_customer_export', response_class=StreamingResponse,
             responses={200: {'content': {'application/zip': {'schema': {'type': 'string', 'format': 'binary'}}}}})
def customer_export(entity_id: str, body: CustomerExportRequest, request: Request, context: Context):
    runtime = request.app.state.runtime
    if not _slots.acquire(blocking=False):
        raise TransportError('unavailable')
    stream = None
    handed_off = False
    try:
        with runtime.audit_operation(context, request.state.request_id, 'customer_export'), runtime.operation():
            runtime.record_customer_export(context, request.state.request_id, 'requested')
            try:
                stream = runtime.prepare_customer_export(context, body.scope == 'documents_inclusive')
                # Provider reads can be slow. Revalidate session, selection and role
                # before any bytes are handed off; cached request context is insufficient.
                for key in ('named_session', 'authorized_context'):
                    if hasattr(request.state, key):
                        delattr(request.state, key)
                current = resolve_context(request)
                if current != context:
                    raise TransportError('forbidden')
                runtime.record_customer_export(context, request.state.request_id, 'available')
            except Exception:
                # Failure evidence never contains exception/provider text.
                try:
                    runtime.record_customer_export(context, request.state.request_id, 'failed')
                except Exception:
                    pass  # Revocation/outage may deny evidence; requested stays unconfirmed.
                raise
        response = PrivateExportResponse(stream)
        handed_off = True
        return response
    except Exception as error:
        if stream is not None:
            stream.close()
        # Shared identity/storage exceptions have safe codes. Export/provider
        # exceptions are deliberately collapsed; no private values reach errors.
        if isinstance(error, (IdentityError, TransportError)):
            raise
        raise TransportError('unavailable') from None
    finally:
        if not handed_off:
            _slots.release()
