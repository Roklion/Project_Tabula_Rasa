"""Fixed-asset records and fresh, source-owned mutation contracts."""

from __future__ import annotations
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from tabula_rasa.transaction import TransactionReferences
from .contracts import ExpectedRecord

AssetRecord = Mapping[str, Any]
AssetChange = Callable[[AssetRecord, Sequence[AssetRecord]], AssetRecord]
AssetPosting = Callable[
    [AssetRecord, TransactionReferences, Sequence[AssetRecord]], Sequence[AssetRecord]
]


class AssetRepository(Protocol):
    """One entity's assets and depreciation events.

    Mutations check expected records and invoke domain preparation with fresh
    asset/history data at the persistence boundary. Confirmed events are durable;
    infrastructure owns uncertain responses and invalidates affected caches.
    """

    def list(self, *, fresh: bool = False) -> list[dict[str, Any]]: ...
    def create(self, record: AssetRecord) -> AssetRecord: ...
    def update(
        self, asset_id: str, *, expected: ExpectedRecord | None, build: AssetChange
    ) -> AssetRecord: ...
    def delete(
        self, asset_id: str, *, expected: ExpectedRecord | None, validate: AssetChange
    ) -> None: ...
    def post(
        self, asset_id: str, *, expected: ExpectedRecord | None, build: AssetPosting
    ) -> list[dict[str, Any]]: ...
