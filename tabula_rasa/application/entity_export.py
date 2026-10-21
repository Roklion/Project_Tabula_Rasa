"""Application-owned export boundary. Provider connections/rows never escape."""

from dataclasses import dataclass
from typing import Protocol


class ExportError(ValueError):
    """A fixed failure code, never a private value or provider error."""

    def __init__(self, code):
        self.code = code
        super().__init__(f"Bookkeeping export failed ({code}).")


@dataclass(frozen=True)
class EntityExportSnapshot:
    entity_id: str
    database_schema_version: str
    snapshot_at: str
    domains: dict[str, tuple[dict[str, object], ...]]


class EntityExportRepository(Protocol):
    def read_export(self) -> EntityExportSnapshot: ...


class EntityExportService:
    """Produce verified canonical content; callers enforce export and delivery policy."""

    def __init__(self, repository: EntityExportRepository):
        self.repository = repository

    def export(self) -> dict:
        from tabula_rasa.bookkeeping_export.format import build_artifact
        return build_artifact(self.repository.read_export())
