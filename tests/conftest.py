"""Shared pytest fixtures for stateful storage tests.

Fixtures here represent meaningful test concepts; one-off workbook setup stays
close to the test that explains its special schema or failure behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tabula_rasa.storage import GoogleSheetsStorage
from tests.fakes import FakeWorkbook


@pytest.fixture
def fake_workbook() -> FakeWorkbook:
    """An isolated in-memory workbook with the production worksheet schema."""

    return FakeWorkbook()


@pytest.fixture
def storage(fake_workbook: FakeWorkbook) -> GoogleSheetsStorage:
    """Sheets-backed storage with retries disabled for deterministic tests."""

    def no_sleep(_delay: float) -> None:
        return None

    return GoogleSheetsStorage(fake_workbook, sleeper=no_sleep)


@pytest.fixture
def default_storage(storage: GoogleSheetsStorage) -> GoogleSheetsStorage:
    """Storage seeded with the standard accounts and categories."""

    storage.ensure_defaults()
    return storage


@pytest.fixture
def profile_store_path(tmp_path: Path) -> Path:
    """An isolated local profile-store path for app and profile tests."""

    return tmp_path / "profiles.json"
