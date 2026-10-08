from fastapi import APIRouter, Request

from ..baselines import required_baseline
from ..errors import ERROR_RESPONSES
from ..models.mileage import Mileage, MileageList, MileageUpdate, mileage_response
from ..models.mutations import MutationResult, ProtectedMutation
from .services import Context, service_operation

router = APIRouter(prefix='/api/v1/entities/{entity_id}/mileage', tags=['Mileage'], responses=ERROR_RESPONSES)


@router.get('', response_model=MileageList, operation_id='list_mileage')
def list_mileage(entity_id: str, request: Request, context: Context):
    with service_operation(request, context, 'mileage') as service:
        return MileageList(items=[mileage_response(trip) for trip in service.list_trips(fresh=True)])


@router.patch('/{record_id}', response_model=Mileage, operation_id='update_mileage')
def update_mileage(entity_id: str, record_id: str, body: MileageUpdate, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    with service_operation(request, context, 'mileage') as service:
        return mileage_response(service.edit_trip(record_id, expected=expected, **body.changes.model_dump(exclude_unset=True)))


@router.delete('/{record_id}', response_model=MutationResult, operation_id='delete_mileage')
def delete_mileage(entity_id: str, record_id: str, body: ProtectedMutation, request: Request, context: Context):
    expected = required_baseline(body.baseline)
    with service_operation(request, context, 'mileage') as service:
        service.delete_trip(record_id, expected=expected)
        return MutationResult(status='fully_applied')
