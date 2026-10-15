from fastapi import APIRouter, Request

from ..baselines import required_baseline
from ..errors import ERROR_RESPONSES
from ..models.mileage import (
    Mileage, MileageCreate, MileageList, MileageUpdate, MileageMaps,
    MileageRoute, MileageRouteRequest, mileage_response,
)
from ..models.mutations import MutationResult, ProtectedMutation
from .services import Context, service_operation

router = APIRouter(prefix='/api/v1/entities/{entity_id}/mileage', tags=['Mileage'], responses=ERROR_RESPONSES)


@router.get('/maps', response_model=MileageMaps, operation_id='mileage_maps')
def mileage_maps(entity_id: str, request: Request, context: Context):
    maps = getattr(request.app.state.runtime, 'maps', None)
    return maps.configuration() if maps is not None else MileageMaps()


@router.post('/routes', response_model=MileageRoute, operation_id='calculate_mileage_route')
def calculate_mileage_route(entity_id: str, body: MileageRouteRequest, request: Request, context: Context):
    maps = getattr(request.app.state.runtime, 'maps', None)
    return (maps.calculate(body.origin_place_id, body.destination_place_id, round_trip=body.round_trip)
            if maps is not None else MileageRoute(error_code='unavailable'))


@router.get('', response_model=MileageList, operation_id='list_mileage')
def list_mileage(entity_id: str, request: Request, context: Context, start: str | None = None, end: str | None = None):
    with service_operation(request, context, 'mileage') as service:
        return MileageList(items=[mileage_response(trip) for trip in service.list_trips(start=start, end=end, fresh=True)])


@router.get('/{record_id}', response_model=Mileage, operation_id='get_mileage')
def get_mileage(entity_id: str, record_id: str, request: Request, context: Context):
    with service_operation(request, context, 'mileage') as service:
        return mileage_response(service.get_trip(record_id))


@router.post('', response_model=MileageList, status_code=201, operation_id='create_mileage')
def create_mileage(entity_id: str, body: MileageCreate, request: Request, context: Context):
    with service_operation(request, context, 'mileage') as service:
        data = body.model_dump(exclude={'round_trip', 'return_miles'})
        trips = (service.create_round_trip(return_miles=body.return_miles, **data)
                 if body.round_trip else (service.create_trip(**data),))
        return MileageList(items=[mileage_response(trip) for trip in trips])


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
