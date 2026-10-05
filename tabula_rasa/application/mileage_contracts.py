"""Persistence-neutral capabilities for the profile's mileage workflow."""

from collections.abc import Callable, Sequence
from typing import Protocol, TYPE_CHECKING

from .contracts import ExpectedRecord

if TYPE_CHECKING:
    from .mileage import MileageTag, MileageTrip

CreateTag = Callable[[str], "MileageTag"]
PrepareNewTrips = Callable[[Sequence["MileageTag"], CreateTag], Sequence["MileageTrip"]]
PrepareUpdatedTrip = Callable[
    ["MileageTrip", Sequence["MileageTag"], CreateTag], "MileageTrip"
]
PrepareImport = Callable[
    [Sequence["MileageTrip"], Sequence["MileageTag"]], Sequence["MileageTrip"]
]


class MileageRepository(Protocol):
    """Mileage operations for one selected profile.

    The three preparation callbacks run once against fresh records/references
    at the mutation boundary, before the repository persists their result.
    This keeps domain decisions in the service and lock/read/write behavior
    in the backend. Failures propagate; the service does not retry operations.
    """

    def list_trips(self, *, fresh: bool = False) -> Sequence["MileageTrip"]: ...

    def list_tags(self, *, fresh: bool = False) -> Sequence["MileageTag"]: ...

    def add_trips(self, prepare: PrepareNewTrips) -> Sequence["MileageTrip"]: ...

    def update_trip(
        self, trip_id: str, prepare: PrepareUpdatedTrip, *,
        expected: ExpectedRecord | None = None,
    ) -> "MileageTrip": ...

    def delete_trip(self, trip_id: str, *, expected: ExpectedRecord | None = None) -> None: ...

    def import_trips(self, prepare: PrepareImport) -> Sequence["MileageTrip"]: ...
