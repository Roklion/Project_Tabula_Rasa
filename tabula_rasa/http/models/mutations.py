"""Loaded metadata travels separately from editable fields on every command."""

from pydantic import Field

from .common import DTO


class ProtectedMutation(DTO):
    # Validation handling maps omission/null to baseline_required without
    # weakening the generated request contract or exposing submitted values.
    baseline: str = Field(max_length=4096)


class MutationResult(DTO):
    status: str
    count: str | None = None
