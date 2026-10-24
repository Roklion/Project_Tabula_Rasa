from fastapi import APIRouter, Request

from ..errors import ERROR_RESPONSES
from ..maps_quota import MapsQuotaAdapter
from ..models.maps_quota import MapsQuotaRequest, MapsQuotaStatus
from .services import Context


router = APIRouter(prefix='/api/v1/entities/{entity_id}/maps/usage', tags=['Maps usage'], responses=ERROR_RESPONSES)


def adapter(request):
    return getattr(request.app.state.runtime, 'maps_quota', None) or MapsQuotaAdapter()


@router.get('', response_model=MapsQuotaStatus, operation_id='maps_quota_status')
def maps_quota_status(entity_id: str, request: Request, context: Context):
    return adapter(request).status()


@router.post('', response_model=MapsQuotaStatus, operation_id='load_maps_quota')
def load_maps_quota(entity_id: str, body: MapsQuotaRequest, request: Request, context: Context):
    return adapter(request).load(refresh=body.refresh)
