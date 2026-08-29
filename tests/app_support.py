"""Shared, deliberately small helpers for Streamlit AppTest scenarios."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tabula_rasa.ledger_auth import hash_password
from tabula_rasa.storage import GoogleSheetsStorage

TEST_PASSWORD = "test-password-123"
SCENARIO_ENVIRONMENT = {
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}


def by_label(elements: Any, label: str) -> Any:
    """Return the first Streamlit test element with *label*."""

    try:
        return next(element for element in elements if element.label == label)
    except StopIteration:
        raise ValueError(f"Element with label '{label}' not found") from None


def message_values(app: AppTest, message_type: str) -> list[str]:
    """Extract values from one of AppTest's message collections."""

    return [str(element.value) for element in getattr(app, message_type)]


def success_values(app: AppTest) -> list[str]:
    return message_values(app, "success")


def error_values(app: AppTest) -> list[str]:
    return message_values(app, "error")


def warning_values(app: AppTest) -> list[str]:
    return message_values(app, "warning")


def profile_config(
    *,
    name: str = "Test Business",
    spreadsheet_id: str = "test-sheet",
    **overrides: object,
) -> dict[str, object]:
    """Build the common minimal business-profile secret entry."""

    profile: dict[str, object] = {
        "name": name,
        "spreadsheet_id": spreadsheet_id,
        "gcp_service_account": {"type": "service_account"},
    }
    profile.update(overrides)
    return profile


def build_app_test(
    *,
    profiles: dict[str, dict[str, object]] | None = None,
    extra_secrets: dict[str, object] | None = None,
) -> AppTest:
    """Create an AppTest with the standard test password and profiles."""

    app = AppTest.from_file("tabula_rasa/app.py", default_timeout=30)
    app.secrets["app_password_hash"] = hash_password(TEST_PASSWORD)
    app.secrets["business_profiles"] = (
        profiles if profiles is not None else {"test": profile_config()}
    )
    if extra_secrets:
        app.secrets.update(extra_secrets)
    return app


@contextmanager
def authenticated_app(
    storage: GoogleSheetsStorage | None = None,
    *,
    profiles: dict[str, dict[str, object]] | None = None,
    extra_secrets: dict[str, object] | None = None,
    storages: dict[str, GoogleSheetsStorage] | None = None,
) -> Iterator[AppTest]:
    """Run and authenticate an AppTest with isolated local profile state.

    ``storages`` is useful for profile-isolation scenarios; keys are the
    configured spreadsheet IDs.  Additional method patches belong inside the
    context so each scenario keeps its failure injection visible at the call
    site.
    """

    app = build_app_test(profiles=profiles, extra_secrets=extra_secrets)
    if storages is not None:
        def from_secrets(secrets: dict[str, object]) -> GoogleSheetsStorage:
            return storages[str(secrets["spreadsheet_id"])]
    elif storage is not None:
        def from_secrets(_secrets: dict[str, object]) -> GoogleSheetsStorage:
            return storage
    else:
        from_secrets = None

    with TemporaryDirectory(
        prefix="test-profiles-", ignore_cleanup_errors=True
    ) as temp_dir:
        profile_store = Path(temp_dir) / "profiles.json"
        profile_patch = patch(
            "tabula_rasa.local_profile_store.LOCAL_PROFILE_STORE_PATH",
            profile_store,
        )
        storage_patch = (
            patch.object(
                GoogleSheetsStorage,
                "from_secrets",
                side_effect=from_secrets,
            )
            if from_secrets is not None
            else patch.object(GoogleSheetsStorage, "from_secrets")
        )
        with profile_patch, storage_patch:
            app.run()
            app.text_input[0].input(TEST_PASSWORD)
            app.button[0].click().run()
            yield app


def navigate_to(app: AppTest, page: str) -> None:
    """Select a top-level page and execute one rerun."""

    app.radio[0].set_value(page).run()


def account_named(storage: GoogleSheetsStorage, name: str) -> dict[str, Any]:
    """Find an account by display name in the selected profile."""

    try:
        return next(
            account
            for account in storage.list_accounts(active_only=False)
            if account["name"] == name
        )
    except StopIteration:
        raise ValueError(f"Account named '{name}' not found in storage") from None


def category_named(
    storage: GoogleSheetsStorage, name: str, kind: str | None = None
) -> dict[str, Any]:
    """Find a category by display name in the selected profile."""

    try:
        return next(
            category
            for category in storage.list_categories()
            if category["name"] == name
            and (kind is None or category["kind"] == kind)
        )
    except StopIteration:
        suffix = f" with kind '{kind}'" if kind else ""
        raise ValueError(
            f"Category named '{name}'{suffix} not found in storage"
        ) from None
