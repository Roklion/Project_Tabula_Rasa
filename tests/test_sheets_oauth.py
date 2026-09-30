from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
from google.auth.exceptions import RefreshError

from scripts.migrate_profile_oauth import convert_profile_document
from tabula_rasa.business_profiles import load_business_profiles, select_profile_secrets
from tabula_rasa.google_drive.errors import GoogleDriveConfigurationError
from tabula_rasa.google_drive.oauth import profile_google_credentials
from tabula_rasa.google_drive_admin import select_profile_ledger
from tabula_rasa.google_drive_picker import _PICKER_JS, spreadsheet_picker
from tabula_rasa.local_profile_store import (
    LocalProfileStoreError,
    load_local_profiles,
    save_local_profile,
)
from tabula_rasa.storage import (
    GoogleSheetsStorage,
    StorageAuthenticationError,
    StorageWorkbookAccessError,
)
from tests.fakes import FakeWorkbook
from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG, google_grant


def profile(email="owner@example.test", token="fake-refresh"):
    return {
        "name": "Business",
        "spreadsheet_id": "existing-ledger-123",
        "google_drive": google_grant(email, token),
        "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
    }


@pytest.mark.parametrize("same_account", [False, True])
def test_credentials_use_shared_client_and_selected_profile_token(same_account):
    north = profile("north@example.test", "north-token")
    south = profile(
        "north@example.test" if same_account else "south@example.test", "south-token"
    )
    document = {
        "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        "business_profiles": {"north": north, "south": {**south, "name": "South"}},
    }
    north_credentials = profile_google_credentials(
        select_profile_secrets(document, "north")
    )
    south_credentials = profile_google_credentials(
        select_profile_secrets(document, "south")
    )
    assert north_credentials is not south_credentials
    assert north_credentials.refresh_token == "north-token"
    assert south_credentials.refresh_token == "south-token"
    assert north_credentials.client_id == south_credentials.client_id == "fake-client"
    assert south_credentials.scopes == ["https://www.googleapis.com/auth/drive.file"]


def test_authorized_user_credentials_refresh_with_the_profile_token():
    credentials = profile_google_credentials(profile())
    response = Mock(
        status=200,
        data=json.dumps({"access_token": "fresh-token", "expires_in": 3600}).encode(),
    )
    request = Mock(return_value=response)
    credentials.refresh(request)
    assert credentials.token == "fresh-token"
    body = request.call_args.kwargs["body"].decode()
    assert "refresh_token=fake-refresh" in body
    assert "client_id=fake-client" in body
    assert "drive.file" in body
    assert "spreadsheets" not in body


@pytest.mark.parametrize("missing", ["google_drive", "google_drive_oauth"])
def test_missing_oauth_fails_without_echoing_tokens(missing):
    settings = profile(token="do-not-echo")
    settings.pop(missing)
    with pytest.raises(GoogleDriveConfigurationError) as raised:
        profile_google_credentials(settings)
    assert "do-not-echo" not in str(raised.value)


def test_revoked_refresh_is_reported_as_profile_reconnect():
    credentials = profile_google_credentials(profile())
    client = Mock()
    client.open_by_key.side_effect = RefreshError("secret-error-do-not-echo")
    with (
        patch(
            "tabula_rasa.storage.google_sheets.client.profile_google_credentials",
            return_value=credentials,
        ),
        patch("gspread.authorize", return_value=client),
    ):
        with pytest.raises(
            StorageAuthenticationError, match="Reconnect this profile"
        ) as raised:
            GoogleSheetsStorage.from_secrets(profile())
    assert "secret-error" not in str(raised.value)


def test_revoked_token_during_read_is_actionable():
    storage = GoogleSheetsStorage(FakeWorkbook())
    with pytest.raises(StorageAuthenticationError, match="Reconnect this profile"):
        storage._api(Mock(side_effect=RefreshError("private-error")))


def test_spreadsheet_picker_sends_spreadsheet_mode():
    result = Mock(selected={"id": "chosen-ledger-123", "name": "Ledger"})
    with patch(
        "tabula_rasa.google_drive_picker._folder_picker_component", return_value=result
    ) as component:
        assert (
            spreadsheet_picker(
                access_token="short-token",
                api_key="key",
                project_number="123",
                key="profile-north",
            )
            == result.selected
        )
    assert component.call_args.kwargs["data"]["kind"] == "spreadsheet"
    assert "ViewId.SPREADSHEETS" in _PICKER_JS
    assert "application/vnd.google-apps.spreadsheet" in _PICKER_JS


@pytest.mark.parametrize("persist", [True, False])
def test_selected_workbook_changes_only_selected_profile_and_preserves_grant(
    tmp_path, persist
):
    path = tmp_path / "profiles.json"
    north = profile("same@example.test", "north-token")
    south = {
        **profile("same@example.test", "south-token"),
        "name": "South",
        "spreadsheet_id": "south-ledger-123",
    }
    save_local_profile("north", north, path=path)
    save_local_profile("south", south, path=path)
    before = load_local_profiles(path)
    response = Mock()
    response.json.return_value = {
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "capabilities": {"canEdit": True},
    }
    client = Mock()
    client._request.return_value = response
    with (
        patch.object(
            GoogleSheetsStorage, "_open_workbook_from_secrets", return_value=Mock()
        ) as open_workbook,
        patch("tabula_rasa.google_drive_admin.GoogleDriveClient", return_value=client),
    ):
        select_profile_ledger(
            {"google_drive_oauth": GOOGLE_OAUTH_CONFIG},
            "north",
            {"id": "chosen-ledger-123"},
            store_path=path,
            persist=persist,
        )
    after = load_local_profiles(path)
    assert after["south"] == before["south"]
    assert after["north"]["google_drive"] == before["north"]["google_drive"]
    assert after["north"]["spreadsheet_id"] == (
        "chosen-ledger-123" if persist else "existing-ledger-123"
    )
    assert (
        open_workbook.call_args.args[0]["google_drive"]["refresh_token"]
        == "north-token"
    )


@pytest.mark.parametrize("failure", ["access", "read-only"])
def test_failed_picker_selection_keeps_previous_profile(tmp_path, failure):
    path = tmp_path / "profiles.json"
    save_local_profile("north", profile(), path=path)
    before = path.read_bytes()
    client = Mock()
    client._request.return_value.json.return_value = {
        "mimeType": "application/vnd.google-apps.spreadsheet",
        "capabilities": {"canEdit": False},
    }
    error = StorageWorkbookAccessError("access") if failure == "access" else None
    with (
        patch.object(
            GoogleSheetsStorage, "_open_workbook_from_secrets", side_effect=error
        ),
        patch("tabula_rasa.google_drive_admin.GoogleDriveClient", return_value=client),
    ):
        with pytest.raises(Exception, match="access|Editor"):
            select_profile_ledger(
                {"google_drive_oauth": GOOGLE_OAUTH_CONFIG},
                "north",
                {"id": "chosen-ledger-123"},
                store_path=path,
            )
    assert path.read_bytes() == before


def test_one_time_conversion_removes_keys_preserves_grants_and_destinations():
    settings = profile()
    settings.pop("google_drive_oauth")
    settings["google_drive"]["storage_root"] = {"id": "root123456", "name": "Storage"}
    settings["gcp_service_account"] = {"private_key": "private-material"}
    document = {"version": 1, "business_profiles": {"north": settings}}
    converted = convert_profile_document(document)
    assert converted["version"] == 2
    result = converted["business_profiles"]["north"]
    assert result["google_drive"] == settings["google_drive"]
    assert result["spreadsheet_id"] == settings["spreadsheet_id"]
    assert "private-material" not in json.dumps(converted)
    assert "gcp_service_account" in settings


def test_runtime_refuses_old_profile_format(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"version": 1, "business_profiles": {"north": profile()}})
    )
    with pytest.raises(LocalProfileStoreError):
        load_local_profiles(path)
    with pytest.raises(ValueError, match="converted"):
        load_business_profiles(
            {"business_profiles": {"north": {**profile(), "gcp_service_account": {}}}}
        )


def test_profile_cannot_override_shared_oauth_client():
    settings = profile()
    settings["google_drive_oauth"] = {
        **GOOGLE_OAUTH_CONFIG,
        "client_id": "wrong-profile-client",
    }
    document = {
        "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        "business_profiles": {"north": settings},
    }
    assert (
        profile_google_credentials(select_profile_secrets(document, "north")).client_id
        == "fake-client"
    )
    document.pop("google_drive_oauth")
    with pytest.raises(GoogleDriveConfigurationError):
        profile_google_credentials(select_profile_secrets(document, "north"))


def test_initial_ledger_provision_uses_profile_grant_and_initializes(tmp_path):
    from tabula_rasa.google_drive_admin import provision_profile_ledger

    path = tmp_path / "profiles.json"
    north = {**profile(token="north-token"), "spreadsheet_id": ""}
    south = {**profile(token="south-token"), "name": "South", "spreadsheet_id": ""}
    save_local_profile("north", north, path=path)
    save_local_profile("south", south, path=path)
    client = Mock()
    client.create_ledger_spreadsheet.return_value = {
        "id": "created-ledger-123",
        "name": "Business Ledger",
    }
    with (
        patch(
            "tabula_rasa.google_drive_admin.GoogleDriveClient", return_value=client
        ) as build_client,
        patch(
            "tabula_rasa.google_drive_admin.initialize_candidate_storage"
        ) as initialize,
    ):
        provision_profile_ledger(
            {"google_drive_oauth": GOOGLE_OAUTH_CONFIG}, "north", store_path=path
        )
    result = load_local_profiles(path)
    assert result["north"]["spreadsheet_id"] == "created-ledger-123"
    assert result["south"]["spreadsheet_id"] == ""
    assert build_client.call_args.args[1]["refresh_token"] == "north-token"
    assert initialize.call_args.args[0]["spreadsheet_id"] == "created-ledger-123"
    client.create_ledger_spreadsheet.assert_called_once_with("north", "Business Ledger")


def test_existing_ledger_cannot_be_replaced_by_initial_provision(tmp_path):
    from tabula_rasa.google_drive_admin import provision_profile_ledger

    path = tmp_path / "profiles.json"
    save_local_profile("north", profile(), path=path)
    with patch("tabula_rasa.google_drive_admin.GoogleDriveClient") as client:
        with pytest.raises(LocalProfileStoreError, match="already has a ledger"):
            provision_profile_ledger({}, "north", store_path=path)
    client.assert_not_called()


def test_initialization_failure_keeps_created_id_for_repair(tmp_path):
    from tabula_rasa.google_drive_admin import provision_profile_ledger

    path = tmp_path / "profiles.json"
    save_local_profile("north", {**profile(), "spreadsheet_id": ""}, path=path)
    client = Mock()
    client.create_ledger_spreadsheet.return_value = {"id": "created-ledger-123"}
    with (
        patch("tabula_rasa.google_drive_admin.GoogleDriveClient", return_value=client),
        patch(
            "tabula_rasa.google_drive_admin.initialize_candidate_storage",
            side_effect=StorageWorkbookAccessError("init failed"),
        ),
    ):
        with pytest.raises(StorageWorkbookAccessError):
            provision_profile_ledger(
                {"google_drive_oauth": GOOGLE_OAUTH_CONFIG}, "north", store_path=path
            )
    assert load_local_profiles(path)["north"]["spreadsheet_id"] == "created-ledger-123"
    client.delete_file.assert_not_called()


@pytest.mark.parametrize("uncertain", [False, True])
def test_drive_ledger_create_uses_stable_profile_identity_and_bounded_readback(
    uncertain,
):
    from tabula_rasa.google_drive import (
        GoogleDriveClient,
        load_oauth_config,
        GoogleDriveAccessError,
    )

    client = GoogleDriveClient(
        load_oauth_config({"google_drive_oauth": GOOGLE_OAUTH_CONFIG}), google_grant()
    )
    created = {"id": "created-ledger-123", "name": "Business Ledger"}
    with (
        patch.object(
            client, "_list", side_effect=[[], [created]] if uncertain else [[]]
        ) as listing,
        patch.object(
            client,
            "_metadata_create",
            side_effect=GoogleDriveAccessError("response lost") if uncertain else None,
            return_value=created,
        ) as create,
    ):
        assert client.create_ledger_spreadsheet("north", "Business Ledger") == created
    assert listing.call_count == (2 if uncertain else 1)
    create.assert_called_once()
    assert create.call_args.args[0]["appProperties"] == {
        "tabulaRasaKind": "ledger",
        "tabulaRasaProfile": "north",
    }
    assert "value='north'" in listing.call_args.args[0]


def test_uncertain_ledger_create_without_readback_stops_without_retry():
    from tabula_rasa.google_drive import (
        GoogleDriveClient,
        load_oauth_config,
        GoogleDriveAccessError,
    )

    client = GoogleDriveClient(
        load_oauth_config({"google_drive_oauth": GOOGLE_OAUTH_CONFIG}), google_grant()
    )
    with (
        patch.object(client, "_list", return_value=[]) as listing,
        patch.object(
            client,
            "_metadata_create",
            side_effect=GoogleDriveAccessError("response lost"),
        ) as create,
    ):
        with pytest.raises(
            GoogleDriveAccessError, match="Inspect Google Drive"
        ) as raised:
            client.create_ledger_spreadsheet("north", "Business Ledger")
    assert raised.value.upload_attempted
    assert listing.call_count == 2
    create.assert_called_once()


def test_ledger_provision_recovers_prior_created_file_without_second_create():
    from tabula_rasa.google_drive import GoogleDriveClient, load_oauth_config

    client = GoogleDriveClient(
        load_oauth_config({"google_drive_oauth": GOOGLE_OAUTH_CONFIG}), google_grant()
    )
    with (
        patch.object(
            client,
            "_list",
            return_value=[{"id": "created-ledger-123", "name": "Business Ledger"}],
        ),
        patch.object(client, "_metadata_create") as create,
    ):
        assert (
            client.create_ledger_spreadsheet("north", "Business Ledger")["id"]
            == "created-ledger-123"
        )
    create.assert_not_called()


def test_onboarding_create_action_initializes_and_hides_after_save(tmp_path):
    from streamlit.testing.v1 import AppTest

    path = tmp_path / "profiles.json"
    save_local_profile("north", {**profile(), "spreadsheet_id": ""}, path=path)
    fake_storage = GoogleSheetsStorage(FakeWorkbook())
    client = Mock()
    client.access_token.return_value = "short-token"
    client.create_ledger_spreadsheet.return_value = {
        "id": "created-ledger-123",
        "name": "Business Ledger",
    }
    source = f"""
from pathlib import Path
from tabula_rasa.google_drive_admin import render_google_drive_admin
from tabula_rasa.local_profile_store import load_local_profiles
from tests.google_auth_fixtures import GOOGLE_OAUTH_CONFIG
path = Path({str(path)!r})
render_google_drive_admin({{"google_drive_oauth": GOOGLE_OAUTH_CONFIG}}, load_local_profiles(path),
                         current_url="http://localhost:8501/", selected_profile_key="north", store_path=path)
"""
    with (
        patch(
            "tabula_rasa.google_drive_admin._cached_drive_client", return_value=client
        ),
        patch("tabula_rasa.google_drive_admin.GoogleDriveClient", return_value=client),
        patch(
            "tabula_rasa.google_drive_admin.initialize_candidate_storage",
            return_value=fake_storage,
        ) as initialize,
    ):
        app = AppTest.from_string(source).run()
        next(
            button
            for button in app.button
            if button.label == "Create ledger spreadsheet"
        ).click().run()
    assert len(app.exception) == 0
    assert load_local_profiles(path)["north"]["spreadsheet_id"] == "created-ledger-123"
    assert not any(button.label == "Create ledger spreadsheet" for button in app.button)
    assert any(button.label == "Validate ledger" for button in app.button)
    assert any("created and initialized" in item.value for item in app.success)
    initialize.assert_called_once()


@pytest.mark.parametrize("same_account", [False, True])
def test_oauth_open_read_write_keep_two_profiles_isolated(same_account):
    north = {
        **profile("north@example.test", "north-token"),
        "spreadsheet_id": "north-ledger-123",
    }
    south = {
        **profile(
            "north@example.test" if same_account else "south@example.test",
            "south-token",
        ),
        "name": "South",
        "spreadsheet_id": "south-ledger-123",
    }
    document = {
        "google_drive_oauth": GOOGLE_OAUTH_CONFIG,
        "business_profiles": {"north": north, "south": south},
    }
    workbooks = {"north-ledger-123": FakeWorkbook(), "south-ledger-123": FakeWorkbook()}
    authorized_tokens = []

    def authorize(credentials):
        authorized_tokens.append(credentials.refresh_token)
        client = Mock()
        client.open_by_key.side_effect = lambda key: workbooks[key]
        return client

    with patch(
        "tabula_rasa.storage.google_sheets.client.gspread.authorize",
        side_effect=authorize,
    ):
        north_storage = GoogleSheetsStorage.from_secrets(
            select_profile_secrets(document, "north")
        )
        south_storage = GoogleSheetsStorage.from_secrets_read_only(
            select_profile_secrets(document, "south")
        )
    north_storage.create_account("North checking", "Bank")
    assert authorized_tokens == ["north-token", "south-token"]
    assert len(north_storage.list_accounts()) == 1
    assert south_storage.list_accounts() == []


@pytest.mark.parametrize("operation", ["select", "provision"])
def test_ledger_setup_without_connection_stops_before_remote_or_local_writes(
    tmp_path, operation
):
    from tabula_rasa.google_drive_admin import provision_profile_ledger

    path = tmp_path / "profiles.json"
    disconnected = {"name": "North", "spreadsheet_id": ""}
    save_local_profile("north", disconnected, path=path)
    save_local_profile("south", {**profile(), "name": "South"}, path=path)
    before = path.read_bytes()
    expected_error = (
        StorageAuthenticationError if operation == "select"
        else GoogleDriveConfigurationError
    )
    with patch("requests.Session") as session:
        with pytest.raises(expected_error):
            if operation == "select":
                select_profile_ledger(
                    {"google_drive_oauth": GOOGLE_OAUTH_CONFIG}, "north",
                    {"id": "chosen-ledger-123"}, store_path=path,
                )
            else:
                provision_profile_ledger(
                    {"google_drive_oauth": GOOGLE_OAUTH_CONFIG}, "north",
                    store_path=path,
                )
    session.assert_not_called()
    assert path.read_bytes() == before