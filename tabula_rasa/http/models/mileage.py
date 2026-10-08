from pydantic import Field

from .accounts import DecimalString
from .common import DTO
from .mutations import ProtectedMutation


class MileageChanges(DTO):
    trip_date: str
    miles: DecimalString
    vehicle: str
    start_location: str
    destination: str
    business_purpose: str
    notes: str = ''
    tag_ids: list[str] = Field(default_factory=list)
    new_tag_name: str = ''


class Mileage(DTO):
    id: str
    trip_date: str
    miles: DecimalString
    vehicle: str
    start_location: str
    destination: str
    business_purpose: str
    notes: str
    tag_ids: list[str]
    created_at: str
    baseline: str


class MileageList(DTO):
    items: list[Mileage]


class MileageUpdate(ProtectedMutation):
    changes: MileageChanges


def mileage_response(trip):
    row = trip.as_record()
    return Mileage(**{name: row[name] for name in Mileage.model_fields})
