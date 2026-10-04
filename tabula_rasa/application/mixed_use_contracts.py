"""Source-authoritative mixed-use expense persistence contracts."""

from __future__ import annotations
from collections.abc import Mapping
from typing import Any, Protocol

from tabula_rasa.transaction import TransactionReferences
from .contracts import ExpectedRecord


class BuildMixedUse(Protocol):
    def __call__(
        self, data: Mapping[str, Any], references: TransactionReferences, **options: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]: ...


class MixedUseRepository(Protocol):
    """Persist a source and projection as one logical source-owned mutation.

    Invoke build after fresh expected-record, stable-identity, reference and
    relationship checks. Keep incomplete sources inspectable; never blindly
    repair partial pairs. Infrastructure owns bounded uncertainty recovery.
    """

    def list(self, *, fresh: bool = False) -> list[dict[str, Any]]: ...
    def sources(self, *, fresh: bool = False) -> list[dict[str, Any]]: ...
    def get(self, source_id: str, *, fresh: bool = False) -> dict[str, Any]: ...
    def create(
        self, data: Mapping[str, Any], *, build: BuildMixedUse, recurring: bool = False
    ) -> dict[str, Any]: ...
    def update(
        self,
        source_id: str,
        changes: Mapping[str, Any],
        *,
        expected: ExpectedRecord | None,
        build: BuildMixedUse,
    ) -> dict[str, Any]: ...
    def delete(self, source_id: str, *, expected: ExpectedRecord | None) -> None: ...
    def link_receipt(
        self,
        source_id: str,
        *,
        reference: Mapping[str, Any],
        expected: ExpectedRecord | None,
    ) -> Any: ...
    def unlink_receipt(
        self, source_id: str, *, file_id: str, expected: ExpectedRecord | None
    ) -> Any: ...
