from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
import requests

from tabula_rasa.google_drive import (
    DRIVE_SCOPE,
    GoogleDriveAccessError,
    GoogleDriveAuthorizationError,
    GoogleDriveClient,
    GoogleDriveConflictError,
    GoogleDriveOAuthConfig,
    authorization_url,
    backup_is_in_local_week,
    create_oauth_state,
    exchange_authorization_code,
    load_oauth_config,
    safe_receipt_filename,
    select_redirect_uri,
    suffixed_receipt_filename,
    validate_drive_profile_settings,
    verify_oauth_state,
)


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        content: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self.payload = payload or {}
        self.content = content

    def json(self) -> dict[str, Any]:
        return self.payload


class AuthorizationSession:
    def __init__(self) -> None:
        self.posted: dict[str, Any] | None = None

    def post(self, _url: str, **kwargs: Any) -> FakeResponse:
        self.posted = kwargs
        return FakeResponse(
            200,
            {
                "access_token": "short-lived-access",
                "refresh_token": "durable-refresh",
                "scope": DRIVE_SCOPE,
            },
        )

    def get(self, _url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(
            200,
            {
                "user": {
                    "displayName": "North Owner",
                    "emailAddress": "north@example.test",
                }
            },
        )


class DriveSession:
    def __init__(
        self,
        responses: list[FakeResponse | requests.RequestException],
        *,
        access_token: str = "short-lived-access",
    ) -> None:
        self.responses = list(responses)
        self.access_token = access_token
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.token_refreshes = 0
        self.refresh_tokens: list[str] = []

    def post(self, _url: str, **kwargs: Any) -> FakeResponse:
        self.token_refreshes += 1
        self.refresh_tokens.append(str(kwargs["data"]["refresh_token"]))
        return FakeResponse(
            200,
            {
                "access_token": self.access_token,
                "expires_in": 3600,
            },
        )

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, requests.RequestException):
            raise response
        return response


def oauth_config() -> GoogleDriveOAuthConfig:
    return GoogleDriveOAuthConfig(
        client_id="client.apps.googleusercontent.com",
        client_secret="client-secret",
        redirect_uris=(
            "http://localhost:8501/",
            "https://tabula-rasa.streamlit.app/",
        ),
        picker_api_key="picker-key",
        project_number="1234567890",
    )


def drive_settings(
    *,
    email: str = "north@example.test",
    refresh_token: str = "durable-refresh",
) -> dict[str, Any]:
    return {
        "authorized_email": email,
        "authorized_name": "North Owner",
        "refresh_token": refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": [DRIVE_SCOPE],
    }


class TestGoogleDriveOAuth:
    def test_loads_app_wide_config_and_selects_current_origin(self) -> None:
        config = load_oauth_config(
            {
                "google_drive_oauth": {
                    "client_id": "client.apps.googleusercontent.com",
                    "client_secret": "secret",
                    "redirect_uris": [
                        "http://localhost:8501/",
                        "https://tabula-rasa.streamlit.app/",
                    ],
                    "picker_api_key": "picker",
                    "project_number": "12345",
                }
            }
        )

        assert (
            select_redirect_uri(
                config,
                "https://tabula-rasa.streamlit.app/?page=profiles",
            )
            == "https://tabula-rasa.streamlit.app/"
        )
        assert config.picker_ready

    def test_state_is_profile_scoped_signed_and_expires(self) -> None:
        config = oauth_config()
        state = create_oauth_state(
            config,
            "north",
            "http://localhost:8501/",
            now=1_000,
        )

        payload = verify_oauth_state(config, state, now=1_100)
        assert payload["profile"] == "north"
        assert payload["redirect_uri"] == "http://localhost:8501/"

        with pytest.raises(GoogleDriveAuthorizationError):
            verify_oauth_state(config, state + "tampered", now=1_100)
        with pytest.raises(GoogleDriveAuthorizationError):
            verify_oauth_state(config, state, now=2_000)

    def test_authorization_requests_narrow_scope_and_offline_access(self) -> None:
        url = authorization_url(
            oauth_config(),
            "north",
            "http://localhost:8501/",
            now=1_000,
        )
        query = parse_qs(urlparse(url).query)

        assert query["scope"] == [DRIVE_SCOPE]
        assert query["access_type"] == ["offline"]
        assert query["prompt"] == ["consent"]
        assert query["redirect_uri"] == ["http://localhost:8501/"]

    def test_code_exchange_retains_refresh_token_and_safe_identity(self) -> None:
        session = AuthorizationSession()

        settings = exchange_authorization_code(
            oauth_config(),
            "authorization-code",
            "http://localhost:8501/",
            session=session,
        )

        assert settings == drive_settings()
        assert session.posted is not None
        assert session.posted["data"]["grant_type"] == "authorization_code"

    def test_profile_settings_require_drive_file_scope(self) -> None:
        invalid = drive_settings()
        invalid["scopes"] = ["https://www.googleapis.com/auth/drive"]

        with pytest.raises(Exception, match="drive.file"):
            validate_drive_profile_settings(invalid)


class TestGoogleDriveFiles:
    @staticmethod
    def _managed_folder(
        folder_id: str,
        name: str,
        *,
        profile_key: str = "north",
        storage_kind: str,
        root_id: str | None = None,
    ) -> dict[str, Any]:
        properties = {
            "tabulaRasaKind": storage_kind,
            "tabulaRasaProfile": profile_key,
        }
        folder: dict[str, Any] = {
            "id": folder_id,
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "trashed": False,
            "appProperties": properties,
        }
        if root_id is not None:
            properties["tabulaRasaStorageRoot"] = root_id
            folder["parents"] = [root_id]
        return folder

    def test_provisions_exactly_one_child_of_each_kind(self) -> None:
        root_id = "rootfolder123"
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {
                        "id": root_id,
                        "name": "North Storage",
                        "mimeType": "application/vnd.google-apps.folder",
                        "trashed": False,
                    },
                ),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "receiptchild123"}),
                FakeResponse(
                    200,
                    self._managed_folder(
                        "receiptchild123",
                        "Receipts",
                        storage_kind="receipts",
                        root_id=root_id,
                    ),
                ),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "backupchild123"}),
                FakeResponse(
                    200,
                    self._managed_folder(
                        "backupchild123",
                        "Ledger Backups",
                        storage_kind="ledger-backups",
                        root_id=root_id,
                    ),
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        children = client.provision_storage_children("north", root_id)

        assert children == {
            "receipts": {"id": "receiptchild123", "name": "Receipts"},
            "ledger-backups": {
                "id": "backupchild123",
                "name": "Ledger Backups",
            },
        }
        create_requests = [
            request for request in session.requests if request[0] == "POST"
        ]
        assert len(create_requests) == 2
        receipt_metadata = json.loads(create_requests[0][2]["data"])
        assert receipt_metadata["parents"] == [root_id]
        assert receipt_metadata["appProperties"]["tabulaRasaProfile"] == "north"
        assert receipt_metadata["appProperties"]["tabulaRasaKind"] == "receipts"

    def test_creates_an_app_managed_storage_root(self) -> None:
        root = self._managed_folder(
            "rootfolder123",
            "North Storage",
            storage_kind="storage-root",
        )
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "rootfolder123"}),
                FakeResponse(200, root),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        created = client.create_storage_root("north", "North Storage")

        assert created == {"id": "rootfolder123", "name": "North Storage"}
        metadata = json.loads(session.requests[1][2]["data"])
        assert metadata["mimeType"] == "application/vnd.google-apps.folder"
        assert metadata["appProperties"]["tabulaRasaKind"] == "storage-root"

    def test_uncertain_root_creation_reuses_the_confirmed_root(self) -> None:
        root = self._managed_folder(
            "rootfolder123",
            "North Storage",
            storage_kind="storage-root",
        )
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("root response was lost"),
                FakeResponse(200, {"files": [root]}),
                FakeResponse(200, root),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        created = client.create_storage_root("north", "North Storage")

        assert created["id"] == "rootfolder123"
        assert [request[0] for request in session.requests].count("POST") == 1

    def test_reuses_existing_children_without_creating_duplicates(self) -> None:
        root_id = "rootfolder123"
        receipt = self._managed_folder(
            "receiptchild123",
            "Receipts",
            storage_kind="receipts",
            root_id=root_id,
        )
        backup = self._managed_folder(
            "backupchild123",
            "Ledger Backups",
            storage_kind="ledger-backups",
            root_id=root_id,
        )
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {
                        "id": root_id,
                        "name": "North Storage",
                        "mimeType": "application/vnd.google-apps.folder",
                        "trashed": False,
                    },
                ),
                FakeResponse(200, {"files": [receipt]}),
                FakeResponse(200, receipt),
                FakeResponse(200, {"files": [backup]}),
                FakeResponse(200, backup),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        children = client.provision_storage_children("north", root_id)

        assert children["receipts"]["id"] == "receiptchild123"
        assert children["ledger-backups"]["id"] == "backupchild123"
        assert not any(request[0] == "POST" for request in session.requests)

    def test_uncertain_child_creation_reconciles_before_retrying(self) -> None:
        root_id = "rootfolder123"
        receipt = self._managed_folder(
            "receiptchild123",
            "Receipts",
            storage_kind="receipts",
            root_id=root_id,
        )
        backup = self._managed_folder(
            "backupchild123",
            "Ledger Backups",
            storage_kind="ledger-backups",
            root_id=root_id,
        )
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {
                        "id": root_id,
                        "name": "North Storage",
                        "mimeType": "application/vnd.google-apps.folder",
                        "trashed": False,
                    },
                ),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response was lost after create"),
                FakeResponse(200, {"files": [receipt]}),
                FakeResponse(200, receipt),
                FakeResponse(200, {"files": [backup]}),
                FakeResponse(200, backup),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        children = client.provision_storage_children("north", root_id)

        assert children["receipts"]["id"] == "receiptchild123"
        assert [request[0] for request in session.requests].count("POST") == 1

    def test_partial_provisioning_is_reusable_on_a_later_attempt(self) -> None:
        root_id = "rootfolder123"
        receipt = self._managed_folder(
            "receiptchild123",
            "Receipts",
            storage_kind="receipts",
            root_id=root_id,
        )
        backup = self._managed_folder(
            "backupchild123",
            "Ledger Backups",
            storage_kind="ledger-backups",
            root_id=root_id,
        )
        session = DriveSession(
            [
                FakeResponse(200, {"id": root_id, "name": "North Storage", "mimeType": "application/vnd.google-apps.folder", "trashed": False}),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "receiptchild123"}),
                FakeResponse(200, receipt),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("backup response was lost"),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("backup response was lost again"),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "rootfolder123", "name": "North Storage", "mimeType": "application/vnd.google-apps.folder", "trashed": False}),
                FakeResponse(200, {"files": [receipt]}),
                FakeResponse(200, receipt),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "backupchild123"}),
                FakeResponse(200, backup),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveAccessError):
            client.provision_storage_children("north", root_id)
        children = client.provision_storage_children("north", root_id)

        assert children["receipts"]["id"] == "receiptchild123"
        assert children["ledger-backups"]["id"] == "backupchild123"

    def test_managed_child_must_remain_under_its_profile_root(self) -> None:
        root_id = "rootfolder123"
        wrong_root = "otherroot123"
        child = self._managed_folder(
            "receiptchild123",
            "Receipts",
            storage_kind="receipts",
            root_id=wrong_root,
        )
        session = DriveSession(
            [
                FakeResponse(200, {"id": root_id, "name": "North Storage", "mimeType": "application/vnd.google-apps.folder", "trashed": False}),
                FakeResponse(200, {"files": [child]}),
                FakeResponse(200, child),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveAccessError, match="outside"):
            client.provision_storage_children("north", root_id)

    def test_selected_folder_is_validated_before_it_is_saved(self) -> None:
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {
                        "id": "receiptfolder123",
                        "name": "Receipts",
                        "mimeType": "application/vnd.google-apps.folder",
                        "trashed": False,
                        "webViewLink": (
                            "https://drive.google.com/drive/folders/receiptfolder123"
                        ),
                    },
                )
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        folder = client.folder("receiptfolder123")

        assert folder["id"] == "receiptfolder123"
        assert folder["name"] == "Receipts"
        request = session.requests[0]
        assert request[0] == "GET"
        assert request[1].endswith("/files/receiptfolder123")
        assert request[2]["params"]["supportsAllDrives"] == "true"

    @pytest.mark.parametrize(
        "folder",
        [
            {
                "id": "receiptfolder123",
                "name": "Not a folder",
                "mimeType": "application/pdf",
                "trashed": False,
            },
            {
                "id": "receiptfolder123",
                "name": "Deleted folder",
                "mimeType": "application/vnd.google-apps.folder",
                "trashed": True,
            },
        ],
    )
    def test_selected_folder_must_be_available_and_be_a_folder(
        self,
        folder: dict[str, Any],
    ) -> None:
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=DriveSession([FakeResponse(200, folder)]),
            sleeper=lambda _delay: None,
        )

        with pytest.raises(
            GoogleDriveAccessError,
            match="not an available folder",
        ):
            client.folder("receiptfolder123")

    def test_profile_scoped_backup_queries_use_distinct_authorizations(self) -> None:
        north_session = DriveSession(
            [FakeResponse(200, {"files": []})],
            access_token="north-access",
        )
        south_session = DriveSession(
            [FakeResponse(200, {"files": []})],
            access_token="south-access",
        )
        north_client = GoogleDriveClient(
            oauth_config(),
            drive_settings(
                email="north@example.test",
                refresh_token="north-refresh",
            ),
            session=north_session,
            sleeper=lambda _delay: None,
        )
        south_client = GoogleDriveClient(
            oauth_config(),
            drive_settings(
                email="south@example.test",
                refresh_token="south-refresh",
            ),
            session=south_session,
            sleeper=lambda _delay: None,
        )

        north_client.list_backups(
            profile_key="north",
            folder_id="northfolder123",
        )
        south_client.list_backups(
            profile_key="south",
            folder_id="southfolder123",
        )

        north_request = north_session.requests[0][2]
        south_request = south_session.requests[0][2]
        assert north_session.refresh_tokens == ["north-refresh"]
        assert south_session.refresh_tokens == ["south-refresh"]
        assert north_request["headers"]["Authorization"] == "Bearer north-access"
        assert south_request["headers"]["Authorization"] == "Bearer south-access"
        assert "'northfolder123' in parents" in north_request["params"]["q"]
        assert "value='north'" in north_request["params"]["q"]
        assert "south" not in north_request["params"]["q"]
        assert "'southfolder123' in parents" in south_request["params"]["q"]
        assert "value='south'" in south_request["params"]["q"]
        assert "north" not in south_request["params"]["q"]

    def test_receipt_upload_is_transaction_scoped_and_sanitizes_name(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(
                    200,
                    {
                        "id": "receipt123456",
                        "name": "statement.pdf",
                    },
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        uploaded = client.upload_receipt(
            profile_key="north",
            transaction_id="txn-1",
            folder_id="folder123456",
            original_name=r"..\statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
        )

        assert uploaded["id"] == "receipt123456"
        create_request = session.requests[-1]
        body = create_request[2]["data"]
        assert b'"tabulaRasaProfile":"north"' in body
        assert b'"tabulaRasaTransaction":"txn-1"' in body
        assert (
            f'"tabulaRasaSha256":"{hashlib.sha256(b"receipt").hexdigest()}"'.encode()
            in body
        )
        assert b'"tabulaRasaReceiptId":' in body
        assert uploaded["size"] == "7"
        assert b"..\\" not in body
        assert safe_receipt_filename("../../statement.pdf") == "statement.pdf"
        assert safe_receipt_filename("CON.pdf") == "_CON.pdf"
        assert suffixed_receipt_filename("statement.pdf", 2) == (
            "statement (2).pdf"
        )
        assert suffixed_receipt_filename("receipt", 3) == "receipt (3)"

    def test_receipt_upload_adds_suffix_for_case_only_name_collision(
        self,
    ) -> None:
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {
                        "files": [
                            {
                                "id": "receipt123456",
                                "name": "Statement.pdf",
                            }
                        ]
                    },
                ),
                FakeResponse(
                    200,
                    {
                        "id": "receipt234567",
                        "name": "statement (2).pdf",
                    },
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        uploaded = client.upload_receipt(
            profile_key="north",
            transaction_id="txn-2",
            folder_id="folder123456",
            original_name="statement.pdf",
            content=b"second receipt",
            mime_type="application/pdf",
        )

        assert uploaded["name"] == "statement (2).pdf"
        assert [request[0] for request in session.requests] == [
            "GET",
            "POST",
        ]
        assert "name =" not in session.requests[0][2]["params"]["q"]
        assert session.requests[0][2]["params"]["pageSize"] == 1000
        assert b'"name":"statement (2).pdf"' in (
            session.requests[1][2]["data"]
        )

    def test_receipt_upload_recovers_an_uncertain_create_response(self) -> None:
        committed = {
            "id": "receipt123456",
            "name": "statement.pdf",
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response lost"),
                FakeResponse(200, {"files": [committed]}),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        uploaded = client.upload_receipt(
            profile_key="north",
            transaction_id="txn-1",
            folder_id="folder123456",
            original_name="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
        )

        assert uploaded["id"] == committed["id"]
        assert uploaded["name"] == committed["name"]
        assert uploaded["appProperties"]["tabulaRasaSha256"] == hashlib.sha256(
            b"receipt"
        ).hexdigest()
        recovery_query = session.requests[-1][2]["params"]["q"]
        assert "name = 'statement.pdf'" in recovery_query
        assert "value='north'" in recovery_query
        assert "value='txn-1'" in recovery_query
        assert "key='tabulaRasaReceiptId'" in recovery_query
        assert "key='tabulaRasaSha256'" in recovery_query

    def test_profile_receipt_listing_is_not_transaction_scoped(self) -> None:
        receipt = {
            "id": "receipt123456",
            "name": "txn-1-statement.pdf",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaTransaction": "txn-1",
            },
        }
        session = DriveSession(
            [FakeResponse(200, {"files": [receipt]})]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        receipts = client.list_profile_receipts(
            profile_key="north",
            folder_id="folder123456",
        )

        assert receipts == [receipt]
        query = session.requests[0][2]["params"]["q"]
        assert "'folder123456' in parents" in query
        assert "value='receipt'" in query
        assert "value='north'" in query
        assert "tabulaRasaTransaction" not in query

    def test_profile_receipt_listing_fetches_every_drive_page(self) -> None:
        first = {"id": "receipt123456", "name": "first.pdf"}
        second = {"id": "receipt789012", "name": "second.pdf"}
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {"files": [first], "nextPageToken": "next-receipt-page"},
                ),
                FakeResponse(200, {"files": [second]}),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        receipts = client.list_profile_receipts(
            profile_key="north",
            folder_id="folder123456",
        )

        assert receipts == [first, second]
        assert len(session.requests) == 2
        assert "pageToken" not in session.requests[0][2]["params"]
        assert (
            session.requests[1][2]["params"]["pageToken"]
            == "next-receipt-page"
        )
        assert "nextPageToken" in session.requests[0][2]["params"]["fields"]

    def test_profile_receipt_listing_rejects_a_repeated_page_token(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": [], "nextPageToken": "repeated"}),
                FakeResponse(200, {"files": [], "nextPageToken": "repeated"}),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveAccessError, match="unreadable"):
            client.list_profile_receipts(
                profile_key="north",
                folder_id="folder123456",
            )

        assert len(session.requests) == 2

    def test_legacy_receipt_checksum_backfill_downloads_once_and_patches_metadata(
        self,
    ) -> None:
        legacy = {
            "id": "receipt123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaTransaction": "txn-1",
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": [legacy]}),
                FakeResponse(200, content=b"receipt"),
                FakeResponse(
                    200,
                    {
                        "id": legacy["id"],
                        "name": legacy["name"],
                        "mimeType": legacy["mimeType"],
                        "size": legacy["size"],
                    },
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        updated = client.backfill_receipt_checksum(
            profile_key="north",
            folder_id="folder123456",
            file_id="receipt123456",
        )

        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "PATCH",
        ]
        patch_body = session.requests[-1][2]["data"]
        expected_hash = hashlib.sha256(b"receipt").hexdigest()
        expected_receipt_id = hashlib.sha256(
            b"tabula-rasa-legacy-receipt:north:receipt123456"
        ).hexdigest()[:32]
        assert expected_hash in patch_body
        assert updated["appProperties"]["tabulaRasaSha256"] == expected_hash
        assert (
            updated["appProperties"]["tabulaRasaReceiptId"]
            == expected_receipt_id
        )

    def test_receipt_recovery_preserves_name_and_integrity_metadata(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(
                    200,
                    {"id": "restored123456", "name": "statement (2).pdf"},
                ),
                FakeResponse(
                    200,
                    {
                        "files": [
                            {
                                "id": "restored123456",
                                "name": "statement (2).pdf",
                            }
                        ]
                    },
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )
        checksum = hashlib.sha256(b"receipt").hexdigest()

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement (2).pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert reused is False
        assert restored["name"] == "statement (2).pdf"
        assert restored["appProperties"] == {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": "a" * 32,
            "tabulaRasaSha256": checksum,
            "tabulaRasaOriginalFileId": "receipt123456",
        }
        assert restored["description"] == "statement.pdf"
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
            "GET",
        ]
        upload_body = next(
            request[2]["data"]
            for request in session.requests
            if request[0] == "POST"
        )
        assert b'"name":"statement (2).pdf"' in upload_body

    def test_receipt_recovery_preserves_manifest_safe_unicode_names(self) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"id": "restored123456", "name": "résumé.pdf"}),
                FakeResponse(
                    200,
                    {"files": [{"id": "restored123456", "name": "résumé.pdf"}]},
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )
        checksum = hashlib.sha256(b"receipt").hexdigest()

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="résumé.pdf",
            original_filename="résumé original.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert reused is False
        assert restored["name"] == "résumé.pdf"
        assert restored["description"] == "résumé original.pdf"
        upload_body = next(
            request[2]["data"]
            for request in session.requests
            if request[0] == "POST"
        )
        assert json.dumps("résumé.pdf").encode() in upload_body

    def test_receipt_recovery_reuses_stable_identity_and_checksum(self) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        existing = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": checksum,
                "tabulaRasaOriginalName": "statement.pdf",
                "tabulaRasaOriginalFileId": "receipt123456",
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": [existing]}),
                FakeResponse(200, content=b"receipt"),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement.pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert restored == existing
        assert reused is True
        assert [request[0] for request in session.requests] == ["GET", "GET"]

    def test_receipt_recovery_refuses_a_case_only_filename_collision(
        self,
    ) -> None:
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(
                    200,
                    {"files": [{"id": "different123456", "name": "Statement.pdf"}]},
                ),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveConflictError, match="recovery filename"):
            client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=hashlib.sha256(b"receipt").hexdigest(),
                old_file_id="receipt123456",
            )

        assert [request[0] for request in session.requests] == ["GET", "GET"]
        assert "name =" not in session.requests[-1][2]["params"]["q"]
        assert session.requests[-1][2]["params"]["pageSize"] == 1000

    def test_receipt_recovery_refuses_corrupt_existing_identity(self) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        existing = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "description": "statement.pdf",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": checksum,
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": [existing]}),
                FakeResponse(200, content=b"corrupt"),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(GoogleDriveConflictError, match="checksum"):
            client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=checksum,
                old_file_id="receipt123456",
            )

        assert [request[0] for request in session.requests] == ["GET", "GET"]

    def test_receipt_recovery_recovers_an_uncertain_create_without_duplication(
        self,
    ) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        committed = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": "north",
                "tabulaRasaReceiptId": "a" * 32,
                "tabulaRasaSha256": checksum,
                "tabulaRasaOriginalName": "statement.pdf",
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response lost"),
                FakeResponse(200, {"files": [committed]}),
                FakeResponse(200, content=b"receipt"),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement.pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert restored["id"] == "restored123456"
        assert reused is False
        assert [request[0] for request in session.requests].count("POST") == 1

    def test_receipt_recovery_reconciles_a_lost_concurrent_create_response(
        self,
    ) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        properties = {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": "a" * 32,
            "tabulaRasaSha256": checksum,
            "tabulaRasaOriginalFileId": "receipt123456",
        }
        canonical = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "createdTime": "2026-08-01T12:00:00Z",
            "description": "statement.pdf",
            "appProperties": {
                **properties,
                "tabulaRasaRecoveryAttempt": "other-attempt",
            },
        }
        uncertain = {
            **canonical,
            "id": "restored234567",
            "createdTime": "2026-08-01T12:00:01Z",
            "appProperties": {
                **properties,
                "tabulaRasaRecoveryAttempt": "1" * 32,
            },
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response lost"),
                FakeResponse(200, {"files": [uncertain, canonical]}),
                FakeResponse(200, content=b"receipt"),
                FakeResponse(204),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with patch(
            "tabula_rasa.google_drive.secrets.token_hex",
            side_effect=["1" * 32, "2" * 32],
        ):
            restored, reused = client.restore_receipt(
                profile_key="north",
                folder_id="folder123456",
                stored_filename="statement.pdf",
                original_filename="statement.pdf",
                content=b"receipt",
                mime_type="application/pdf",
                receipt_id="a" * 32,
                sha256=checksum,
                old_file_id="receipt123456",
            )

        assert restored["id"] == canonical["id"]
        assert reused is False
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
            "GET",
            "GET",
            "DELETE",
        ]
        assert b'"tabulaRasaRecoveryAttempt":"11111111111111111111111111111111"' in (
            session.requests[2][2]["data"]
        )
        assert session.requests[5][1].endswith("/files/restored234567")

    def test_receipt_recovery_discards_its_concurrent_later_create(
        self,
    ) -> None:
        checksum = hashlib.sha256(b"receipt").hexdigest()
        properties = {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": "north",
            "tabulaRasaReceiptId": "a" * 32,
            "tabulaRasaSha256": checksum,
            "tabulaRasaOriginalFileId": "receipt123456",
        }
        canonical = {
            "id": "restored123456",
            "name": "statement.pdf",
            "mimeType": "application/pdf",
            "size": "7",
            "createdTime": "2026-08-01T12:00:00Z",
            "description": "statement.pdf",
            "appProperties": properties,
        }
        later = {
            **canonical,
            "id": "restored234567",
            "createdTime": "2026-08-01T12:00:01Z",
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                FakeResponse(200, {"files": []}),
                FakeResponse(200, later),
                FakeResponse(200, {"files": [later, canonical]}),
                FakeResponse(200, content=b"receipt"),
                FakeResponse(204),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        restored, reused = client.restore_receipt(
            profile_key="north",
            folder_id="folder123456",
            stored_filename="statement.pdf",
            original_filename="statement.pdf",
            content=b"receipt",
            mime_type="application/pdf",
            receipt_id="a" * 32,
            sha256=checksum,
            old_file_id="receipt123456",
        )

        assert restored["id"] == canonical["id"]
        assert reused is False
        assert [request[0] for request in session.requests] == [
            "GET",
            "GET",
            "POST",
            "GET",
            "GET",
            "DELETE",
        ]
        assert session.requests[5][1].endswith("/files/restored234567")

    def test_backup_retry_reuses_existing_file_and_applies_retention(self) -> None:
        existing = {
            "id": "backup123456",
            "name": "tabula-rosa-backup-20260728T120000Z.zip",
        }
        session = DriveSession(
            [
                FakeResponse(
                    200,
                    {
                        "files": [
                            existing,
                            {"id": "backup234567", "name": "older-1.zip"},
                            {"id": "backup345678", "name": "older-2.zip"},
                        ]
                    },
                ),
                FakeResponse(204),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        uploaded = client.upload_backup(
            profile_key="north",
            folder_id="folder123456",
            filename=existing["name"],
            content=b"backup",
            sha256="abc",
            backup_time="2026-07-28T12:00:00+0000",
            keep=2,
        )

        assert uploaded == existing
        assert [request[0] for request in session.requests] == [
            "GET",
            "DELETE",
        ]
        assert not any("/upload/" in request[1] for request in session.requests)

    def test_uncertain_backup_create_queries_before_reporting_failure(self) -> None:
        committed = {
            "id": "backup123456",
            "name": "tabula-rosa-backup-20260728T120000Z.zip",
        }
        session = DriveSession(
            [
                FakeResponse(200, {"files": []}),
                requests.ConnectionError("response was lost after upload"),
                FakeResponse(200, {"files": [committed]}),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        uploaded = client.upload_backup(
            profile_key="north",
            folder_id="folder123456",
            filename=committed["name"],
            content=b"backup",
            sha256="abc",
            backup_time="2026-07-28T12:00:00+0000",
            keep=30,
        )

        assert uploaded == committed
        assert [request[0] for request in session.requests].count("POST") == 1

    def test_revoked_access_reports_profile_reconnect_after_one_refresh(self) -> None:
        session = DriveSession(
            [
                FakeResponse(401),
                FakeResponse(401),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
        )

        with pytest.raises(
            GoogleDriveAuthorizationError,
            match="Reconnect this profile",
        ):
            client.list_backups(
                profile_key="north",
                folder_id="folder123456",
            )

        assert session.token_refreshes == 2
        assert len(session.requests) == 2

    def test_quota_response_retries_with_exponential_backoff(self) -> None:
        delays: list[float] = []
        session = DriveSession(
            [
                FakeResponse(429),
                FakeResponse(429),
                FakeResponse(200, {"files": []}),
            ]
        )
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=delays.append,
        )

        assert (
            client.list_backups(
                profile_key="north",
                folder_id="folder123456",
            )
            == []
        )
        assert delays == [1, 2]
        assert len(session.requests) == 3

    def test_exhausted_quota_retries_return_safe_temporary_error(self) -> None:
        delays: list[float] = []
        session = DriveSession([FakeResponse(429) for _attempt in range(4)])
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=delays.append,
        )

        with pytest.raises(
            GoogleDriveAccessError,
            match="temporarily unavailable",
        ):
            client.list_backups(
                profile_key="north",
                folder_id="folder123456",
            )

        assert delays == [1, 2, 4]
        assert len(session.requests) == 4

    def test_reuses_access_token_and_short_lived_file_list_cache(self) -> None:
        now = [1_000.0]
        session = DriveSession([FakeResponse(200, {"files": []})])
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=lambda _delay: None,
            clock=lambda: now[0],
        )

        assert client.access_token() == "short-lived-access"
        assert client.access_token() == "short-lived-access"
        client.list_backups(
            profile_key="north",
            folder_id="folder123456",
        )
        client.list_backups(
            profile_key="north",
            folder_id="folder123456",
        )

        assert session.token_refreshes == 1
        assert len(session.requests) == 1

        now[0] += 3_541
        assert client.access_token() == "short-lived-access"
        assert session.token_refreshes == 2

    def test_week_detection_uses_canonical_utc_filename(self) -> None:
        assert backup_is_in_local_week(
            "tabula-rosa-backup-20260728T120000Z.zip",
            local_date=datetime(2026, 7, 29),
        )
        assert not backup_is_in_local_week(
            "not-a-tabula-rasa-backup.zip",
            local_date=datetime(2026, 7, 29),
        )
