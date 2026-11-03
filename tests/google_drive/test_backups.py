from __future__ import annotations

from datetime import datetime
import hashlib

import pytest
import requests

from tabula_rasa.google_drive import (
    GoogleDriveAccessError, GoogleDriveAuthorizationError, GoogleDriveClient,
    backup_filename_and_hash, backup_is_in_local_week,
)

from ._support import FakeResponse, DriveSession, drive_error, drive_settings, oauth_config


class TestGoogleDriveBackups:
    def test_backup_retry_reuses_existing_file_and_applies_retention(self) -> None:
        existing = {
            "id": "backup123456",
            "name": "tabula-rasa-backup-20260728T120000Z.zip",
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
            "name": "tabula-rasa-backup-20260728T120000Z.zip",
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


    @pytest.mark.parametrize("status,reason", [
        (403, "rateLimitExceeded"), (403, "userRateLimitExceeded"), (429, "rateLimitExceeded"),
    ])
    def test_quota_response_retries_with_exponential_backoff(self, status, reason) -> None:
        delays: list[float] = []
        session = DriveSession(
            [
                drive_error(status, reason),
                drive_error(status, reason),
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


    @pytest.mark.parametrize("status,reason", [
        (403, "rateLimitExceeded"), (403, "userRateLimitExceeded"), (429, "rateLimitExceeded"),
    ])
    def test_exhausted_quota_retries_return_safe_temporary_error(self, status, reason) -> None:
        delays: list[float] = []
        session = DriveSession([drive_error(status, reason) for _attempt in range(4)])
        client = GoogleDriveClient(
            oauth_config(),
            drive_settings(),
            session=session,
            sleeper=delays.append,
        )

        with pytest.raises(
            GoogleDriveAccessError,
            match="temporarily unavailable",
        ) as failure:
            client.list_backups(
                profile_key="north",
                folder_id="folder123456",
            )

        assert delays == [1, 2, 4]
        assert len(session.requests) == 4
        assert failure.value.retryable
        assert "synthetic-private-provider-response" not in str(failure.value)

    @pytest.mark.parametrize("reason", ["dailyLimitExceeded", "storageQuotaExceeded"])
    def test_quota_or_capacity_failure_does_not_retry(self, reason) -> None:
        delays = []
        session = DriveSession([drive_error(403, reason)])
        client = GoogleDriveClient(oauth_config(), drive_settings(), session=session, sleeper=delays.append)
        with pytest.raises(GoogleDriveAccessError, match="quota or storage limit") as failure:
            client.folder("folder123456")
        assert not failure.value.retryable
        assert len(session.requests) == 1
        assert delays == []

    @pytest.mark.parametrize("body", [
        b"synthetic-private-provider-response",
        b'{"error":{"errors":{"reason":"rateLimitExceeded"}}}',
        b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}' + b" " * 16_384,
    ])
    def test_malformed_or_oversized_forbidden_response_uses_authorization_fallback(self, body) -> None:
        response = drive_error(403)
        response._content = body
        self._assert_authorization_fallback(response)

    @pytest.mark.parametrize("reasons", [
        ("insufficientFilePermissions",),
        ("unknown",),
        ("rateLimitExceeded", "insufficientFilePermissions"),
        ("rateLimitExceeded",) * 17,
    ])
    def test_unrecognized_or_conflicting_reasons_use_authorization_fallback(self, reasons) -> None:
        self._assert_authorization_fallback(drive_error(403, *reasons))

    def _assert_authorization_fallback(self, response) -> None:
        delays = []
        session = DriveSession([response])
        client = GoogleDriveClient(oauth_config(), drive_settings(), session=session, sleeper=delays.append)
        with pytest.raises(GoogleDriveAuthorizationError, match="Reconnect this profile") as failure:
            client.folder("folder123456")
        assert failure.value.__context__ is None
        assert "synthetic-private-provider-response" not in str(failure.value)
        assert len(session.requests) == 1
        assert delays == []


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
        filename, sha256 = backup_filename_and_hash(
            b"backup",
            {"backup_time": "2026-07-28T12:00:00+0000"},
        )

        assert filename == "tabula-rasa-backup-20260728T120000Z.zip"
        assert sha256 == hashlib.sha256(b"backup").hexdigest()
        assert backup_is_in_local_week(
            "tabula-rasa-backup-20260728T120000Z.zip",
            local_date=datetime(2026, 7, 29),
        )
        assert not backup_is_in_local_week(
            "not-a-tabula-rasa-backup.zip",
            local_date=datetime(2026, 7, 29),
        )
