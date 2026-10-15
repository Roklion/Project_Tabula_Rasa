"""Owner-safe status and explicit activation/disconnection; never token DTOs."""
from dataclasses import asdict
from fastapi import APIRouter, Request
from ..errors import ERROR_RESPONSES, TransportError
from ..models.connections import ConnectionChange, ConnectionInfo
from .services import Context

router = APIRouter(prefix='/api/v1/entities/{entity_id}/connections', tags=['Connections'], responses=ERROR_RESPONSES)


def manager(request):
    runtime = request.app.state.runtime
    if runtime.identity is None or runtime.connections is None:
        raise TransportError('unavailable')
    return runtime.connections


@router.get('/google-drive', response_model=ConnectionInfo, operation_id='connection_status')
def connection_status(entity_id: str, request: Request, context: Context):
    return ConnectionInfo(**asdict(manager(request).repository.status(context)))


@router.post('/google-drive', response_model=ConnectionInfo, operation_id='change_connection')
def change_connection(entity_id: str, body: ConnectionChange, request: Request, context: Context):
    result = manager(request).change(context, request.app.state.runtime.identity.authenticated(request),
        revision=body.revision, connect=body.connect)
    return ConnectionInfo(**asdict(result))
