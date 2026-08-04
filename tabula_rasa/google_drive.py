"""Business-scoped Google Drive OAuth and file operations."""

from __future__ import annotations

import base64
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from tabula_rasa.receipt_manifest import (
    DRIVE_ID_PATTERN as RECEIPT_DRIVE_ID_PATTERN,
    RECEIPT_ID_PATTERN,
    SHA256_PATTERN,
    ReceiptManifestError,
    receipt_reference_from_drive_file,
    validate_receipt_filename,
)


DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
DRIVE_API_ROOT = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD_ROOT = "https://www.googleapis.com/upload/drive/v3"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
STATE_MAX_AGE_SECONDS = 10 * 60
HTTP_TIMEOUT_SECONDS = 30
MAX_RECEIPT_BYTES = 20 * 1024 * 1024
PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
DRIVE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
SAFE_RECEIPT_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._() -]+")
STORAGE_CHILD_NAMES = {
    "receipts": "Receipts",
    "ledger-backups": "Ledger Backups",
}


class GoogleDriveError(RuntimeError):
    """Base class for safe Google Drive failures."""


class GoogleDriveConfigurationError(GoogleDriveError):
    """Raised when application or profile Drive settings are incomplete."""


class GoogleDriveAuthorizationError(GoogleDriveError):
    """Raised when Google authorization is rejected, invalid, or revoked."""


class GoogleDriveAccessError(GoogleDriveError):
    """Raised when a Drive API operation cannot be completed."""


class GoogleDriveConflictError(GoogleDriveAccessError):
    """Raised when recovery would overwrite or ambiguously reuse a Drive file."""


@dataclass(frozen=True)
class GoogleDriveOAuthConfig:
    """Application-wide OAuth client and Picker configuration."""

    client_id: str
    client_secret: str
    redirect_uris: tuple[str, ...]
    picker_api_key: str = ""
    project_number: str = ""

    @property
    def picker_ready(self) -> bool:
        return bool(self.picker_api_key and self.project_number)


def _mapping(value: object, message: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GoogleDriveConfigurationError(message)
    return value


def _clean_text(value: object, *, maximum: int = 4096) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or any(ord(character) < 32 for character in text):
        return ""
    return text


def _validate_redirect_uri(value: object) -> str:
    uri = _clean_text(value, maximum=2048)
    parsed = urlparse(uri)
    is_loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not uri
        or parsed.query
        or parsed.fragment
        or not parsed.netloc
        or parsed.scheme not in ({"http", "https"} if is_loopback else {"https"})
    ):
        raise GoogleDriveConfigurationError(
            "Google Drive OAuth redirect URIs are invalid."
        )
    return uri


def load_oauth_config(secrets_mapping: Mapping[str, Any]) -> GoogleDriveOAuthConfig:
    """Load and validate the app-wide Google Drive OAuth configuration."""
    raw = _mapping(
        secrets_mapping.get("google_drive_oauth"),
        "Google Drive OAuth is not configured for this deployment.",
    )
    client_id = _clean_text(raw.get("client_id"))
    client_secret = _clean_text(raw.get("client_secret"))
    redirect_values = raw.get("redirect_uris")
    if isinstance(redirect_values, str):
        redirect_values = [redirect_values]
    if (
        not client_id
        or not client_secret
        or not isinstance(redirect_values, Sequence)
        or isinstance(redirect_values, (bytes, bytearray))
    ):
        raise GoogleDriveConfigurationError(
            "Google Drive OAuth client settings are incomplete."
        )
    redirect_uris = tuple(
        dict.fromkeys(_validate_redirect_uri(value) for value in redirect_values)
    )
    if not redirect_uris:
        raise GoogleDriveConfigurationError(
            "Google Drive OAuth needs at least one redirect URI."
        )
    picker_api_key = _clean_text(raw.get("picker_api_key"))
    project_number = _clean_text(raw.get("project_number"), maximum=32)
    if bool(picker_api_key) != bool(project_number):
        raise GoogleDriveConfigurationError(
            "Google Picker needs both picker_api_key and project_number."
        )
    return GoogleDriveOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uris=redirect_uris,
        picker_api_key=picker_api_key,
        project_number=project_number,
    )


def select_redirect_uri(
    config: GoogleDriveOAuthConfig,
    current_url: str,
) -> str:
    """Select the registered redirect URI matching the current app origin."""
    current = urlparse(str(current_url))
    for candidate in config.redirect_uris:
        parsed = urlparse(candidate)
        if (parsed.scheme, parsed.netloc) == (current.scheme, current.netloc):
            return candidate
    raise GoogleDriveConfigurationError(
        "This app URL is not listed in google_drive_oauth.redirect_uris."
    )


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise GoogleDriveAuthorizationError(
            "The Google authorization state is invalid. Start the connection again."
        ) from exc


def create_oauth_state(
    config: GoogleDriveOAuthConfig,
    profile_key: str,
    redirect_uri: str,
    *,
    now: int | None = None,
) -> str:
    """Return a signed, short-lived state value for one business profile."""
    if not PROFILE_KEY_PATTERN.fullmatch(profile_key):
        raise GoogleDriveConfigurationError("The business profile key is invalid.")
    if redirect_uri not in config.redirect_uris:
        raise GoogleDriveConfigurationError(
            "The selected Google OAuth redirect URI is not registered in app secrets."
        )
    payload = {
        "v": 1,
        "profile": profile_key,
        "redirect_uri": redirect_uri,
        "issued_at": int(time.time() if now is None else now),
        "nonce": secrets.token_urlsafe(18),
    }
    encoded = _urlsafe_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        config.client_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_urlsafe_encode(signature)}"


def verify_oauth_state(
    config: GoogleDriveOAuthConfig,
    state: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Verify and return a signed OAuth state payload."""
    try:
        encoded, supplied_signature = state.split(".", 1)
    except ValueError as exc:
        raise GoogleDriveAuthorizationError(
            "The Google authorization state is invalid. Start the connection again."
        ) from exc
    expected_signature = hmac.new(
        config.client_secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(
        _urlsafe_encode(expected_signature),
        supplied_signature,
    ):
        raise GoogleDriveAuthorizationError(
            "The Google authorization state is invalid. Start the connection again."
        )
    try:
        payload = json.loads(_urlsafe_decode(encoded).decode("utf-8"))
        issued_at = int(payload["issued_at"])
        profile_key = str(payload["profile"])
        redirect_uri = str(payload["redirect_uri"])
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise GoogleDriveAuthorizationError(
            "The Google authorization state is invalid. Start the connection again."
        ) from exc
    current_time = int(time.time() if now is None else now)
    if (
        payload.get("v") != 1
        or not PROFILE_KEY_PATTERN.fullmatch(profile_key)
        or redirect_uri not in config.redirect_uris
        or issued_at > current_time + 30
        or current_time - issued_at > STATE_MAX_AGE_SECONDS
    ):
        raise GoogleDriveAuthorizationError(
            "The Google authorization request expired. Start the connection again."
        )
    return payload


def authorization_url(
    config: GoogleDriveOAuthConfig,
    profile_key: str,
    redirect_uri: str,
    *,
    login_hint: str = "",
    now: int | None = None,
) -> str:
    """Build a Google web-server authorization URL with offline access."""
    state = create_oauth_state(
        config,
        profile_key,
        redirect_uri,
        now=now,
    )
    parameters = {
        "client_id": config.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": DRIVE_SCOPE,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    if login_hint:
        parameters["login_hint"] = login_hint
    return f"{AUTHORIZATION_ENDPOINT}?{urlencode(parameters)}"


def _json_response(response: requests.Response) -> Mapping[str, Any]:
    try:
        parsed = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise GoogleDriveAccessError(
            "Google Drive returned an unreadable response. Retry the request."
        ) from exc
    if not isinstance(parsed, Mapping):
        raise GoogleDriveAccessError(
            "Google Drive returned an unreadable response. Retry the request."
        )
    return parsed


def exchange_authorization_code(
    config: GoogleDriveOAuthConfig,
    code: str,
    redirect_uri: str,
    *,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code and return sanitized persistent settings."""
    if not _clean_text(code):
        raise GoogleDriveAuthorizationError(
            "Google did not return an authorization code. Start the connection again."
        )
    client = session or requests.Session()
    try:
        response = client.post(
            TOKEN_ENDPOINT,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GoogleDriveAuthorizationError(
            "Google authorization is temporarily unavailable. Retry the connection."
        ) from exc
    if response.status_code != 200:
        raise GoogleDriveAuthorizationError(
            "Google rejected the authorization response. Start the connection again."
        )
    token = _json_response(response)
    refresh_token = _clean_text(token.get("refresh_token"))
    access_token = _clean_text(token.get("access_token"))
    if not refresh_token or not access_token:
        raise GoogleDriveAuthorizationError(
            "Google did not issue offline access. Revoke the prior grant and reconnect."
        )
    granted_scopes = str(token.get("scope") or DRIVE_SCOPE).split()
    if DRIVE_SCOPE not in granted_scopes:
        raise GoogleDriveAuthorizationError(
            "Google Drive file access was not granted. Reconnect and approve access."
        )
    user = _authorized_user(access_token, session=client)
    return {
        "authorized_email": _clean_text(user.get("emailAddress"), maximum=320),
        "authorized_name": _clean_text(user.get("displayName"), maximum=200),
        "refresh_token": refresh_token,
        "token_uri": TOKEN_ENDPOINT,
        "scopes": sorted(set(granted_scopes)),
    }


def _authorized_user(
    access_token: str,
    *,
    session: requests.Session,
) -> Mapping[str, Any]:
    try:
        response = session.get(
            f"{DRIVE_API_ROOT}/about",
            params={"fields": "user(displayName,emailAddress,permissionId)"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GoogleDriveAuthorizationError(
            "Google Drive could not confirm the authorized account."
        ) from exc
    if response.status_code != 200:
        raise GoogleDriveAuthorizationError(
            "Google Drive could not confirm the authorized account."
        )
    user = _json_response(response).get("user")
    if not isinstance(user, Mapping):
        raise GoogleDriveAuthorizationError(
            "Google Drive could not confirm the authorized account."
        )
    return user


def validate_drive_profile_settings(value: object) -> dict[str, Any]:
    """Validate persisted per-profile Drive authorization and folder settings."""
    raw = _mapping(value, "Google Drive profile settings are invalid.")
    allowed = {
        "authorized_email",
        "authorized_name",
        "refresh_token",
        "token_uri",
        "scopes",
        "storage_root",
        "receipt_folder",
        "backup_folder",
    }
    if set(raw) - allowed:
        raise GoogleDriveConfigurationError(
            "Google Drive profile settings contain unsupported fields."
        )
    refresh_token = _clean_text(raw.get("refresh_token"))
    token_uri = _clean_text(raw.get("token_uri"))
    scopes = raw.get("scopes")
    if (
        not refresh_token
        or token_uri != TOKEN_ENDPOINT
        or not isinstance(scopes, Sequence)
        or isinstance(scopes, (str, bytes, bytearray))
    ):
        raise GoogleDriveConfigurationError(
            "Google Drive profile authorization is incomplete."
        )
    normalized_scopes = sorted(
        {
            scope
            for raw_scope in scopes
            if (scope := _clean_text(raw_scope, maximum=500))
        }
    )
    if DRIVE_SCOPE not in normalized_scopes:
        raise GoogleDriveConfigurationError(
            "Google Drive profile authorization lacks drive.file access."
        )
    normalized: dict[str, Any] = {
        "authorized_email": _clean_text(raw.get("authorized_email"), maximum=320),
        "authorized_name": _clean_text(raw.get("authorized_name"), maximum=200),
        "refresh_token": refresh_token,
        "token_uri": TOKEN_ENDPOINT,
        "scopes": normalized_scopes,
    }
    for field in ("storage_root", "receipt_folder", "backup_folder"):
        folder = raw.get(field)
        if folder is None:
            continue
        folder_mapping = _mapping(folder, "Google Drive folder settings are invalid.")
        folder_id = _clean_text(folder_mapping.get("id"), maximum=256)
        folder_name = _clean_text(folder_mapping.get("name"), maximum=255)
        if (
            set(folder_mapping) != {"id", "name"}
            or not DRIVE_ID_PATTERN.fullmatch(folder_id)
            or not folder_name
        ):
            raise GoogleDriveConfigurationError(
                "Google Drive folder settings are invalid."
            )
        normalized[field] = {"id": folder_id, "name": folder_name}
    return normalized


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def safe_receipt_filename(original_name: str) -> str:
    """Return a safe Drive filename without encoding transaction identity."""
    cleaned = SAFE_RECEIPT_NAME_PATTERN.sub("_", PathName(original_name).name).strip(
        " ."
    )
    if not cleaned:
        cleaned = "receipt"
    cleaned = cleaned[:180]
    try:
        return validate_receipt_filename(cleaned, "Receipt filename")
    except ReceiptManifestError:
        return validate_receipt_filename(f"_{cleaned}", "Receipt filename")


def suffixed_receipt_filename(filename: str, occurrence: int) -> str:
    """Add a numeric duplicate suffix before a filename extension."""
    if occurrence <= 1:
        return filename
    dot_index = filename.rfind(".")
    if dot_index > 0:
        stem = filename[:dot_index]
        extension = filename[dot_index:]
    else:
        stem = filename
        extension = ""
    return f"{stem} ({occurrence}){extension}"


class PathName:
    """Minimal cross-platform basename parser for untrusted upload names."""

    def __init__(self, value: object) -> None:
        self.value = str(value or "").replace("\\", "/")

    @property
    def name(self) -> str:
        return self.value.rsplit("/", 1)[-1]


class GoogleDriveClient:
    """Narrow Drive REST client backed by a per-profile refresh token."""

    def __init__(
        self,
        config: GoogleDriveOAuthConfig,
        profile_settings: Mapping[str, Any],
        *,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        list_cache_ttl_seconds: float = 10.0,
    ) -> None:
        self.config = config
        self.profile_settings = validate_drive_profile_settings(profile_settings)
        self.session = session or requests.Session()
        self.sleeper = sleeper
        self.clock = clock
        self.list_cache_ttl_seconds = list_cache_ttl_seconds
        self._access_token = ""
        self._access_token_expires_at = 0.0
        self._list_cache: dict[
            tuple[str, int, str, bool],
            tuple[float, list[dict[str, Any]]],
        ] = {}

    def access_token(self) -> str:
        """Return a valid short-lived access token for Drive or Google Picker."""
        self._ensure_access_token()
        return self._access_token

    def revoke(self) -> None:
        """Revoke the profile refresh token at Google."""
        try:
            response = self.session.post(
                REVOCATION_ENDPOINT,
                data={"token": self.profile_settings["refresh_token"]},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise GoogleDriveAuthorizationError(
                "Google could not confirm token revocation. Retry disconnecting."
            ) from exc
        if response.status_code not in {200, 400}:
            raise GoogleDriveAuthorizationError(
                "Google could not confirm token revocation. Retry disconnecting."
            )

    def _refresh(self) -> None:
        try:
            response = self.session.post(
                TOKEN_ENDPOINT,
                data={
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                    "refresh_token": self.profile_settings["refresh_token"],
                    "grant_type": "refresh_token",
                },
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise GoogleDriveAuthorizationError(
                "Google Drive authorization is temporarily unavailable."
            ) from exc
        if response.status_code != 200:
            raise GoogleDriveAuthorizationError(
                "Google Drive authorization was revoked or expired. Reconnect this profile."
            )
        token = _json_response(response)
        access_token = _clean_text(token.get("access_token"))
        if not access_token:
            raise GoogleDriveAuthorizationError(
                "Google Drive authorization was revoked or expired. Reconnect this profile."
            )
        self._access_token = access_token
        try:
            expires_in = max(float(token.get("expires_in", 3600)), 60.0)
        except (TypeError, ValueError):
            expires_in = 3600.0
        self._access_token_expires_at = self.clock() + max(expires_in - 60.0, 1.0)

    def _ensure_access_token(self) -> None:
        if (
            not self._access_token
            or self.clock() >= self._access_token_expires_at
        ):
            self._refresh()

    def _request(
        self,
        method: str,
        url: str,
        *,
        expected: tuple[int, ...] = (200,),
        retry_transient: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        self._ensure_access_token()
        refreshed_after_unauthorized = False
        supplied_headers = dict(kwargs.pop("headers", {}))
        for attempt in range(4):
            headers = dict(supplied_headers)
            headers["Authorization"] = f"Bearer {self._access_token}"
            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=HTTP_TIMEOUT_SECONDS,
                    **kwargs,
                )
            except requests.RequestException as exc:
                if not retry_transient or attempt == 3:
                    raise GoogleDriveAccessError(
                        "Google Drive is temporarily unavailable. Retry the request."
                    ) from exc
                self.sleeper(2**attempt)
                continue
            if response.status_code in expected:
                return response
            if response.status_code == 401 and not refreshed_after_unauthorized:
                self._refresh()
                refreshed_after_unauthorized = True
                continue
            if retry_transient and response.status_code in {429, 500, 502, 503, 504}:
                if attempt < 3:
                    self.sleeper(2**attempt)
                    continue
                raise GoogleDriveAccessError(
                    "Google Drive is temporarily unavailable. Retry the request."
                )
            if response.status_code in {401, 403}:
                raise GoogleDriveAuthorizationError(
                    "Google Drive access was revoked or is insufficient. Reconnect this profile."
                )
            raise GoogleDriveAccessError(
                "Google Drive could not complete the request. No success was reported."
            )
        raise GoogleDriveAccessError(
            "Google Drive is temporarily unavailable. Retry the request."
        )

    def folder(self, folder_id: str) -> dict[str, Any]:
        """Validate and return one authorized Drive folder."""
        folder_id = self._valid_folder_id(folder_id)
        response = self._request(
            "GET",
            f"{DRIVE_API_ROOT}/files/{folder_id}",
            params={
                "fields": "id,name,mimeType,trashed,webViewLink,parents,appProperties",
                "supportsAllDrives": "true",
            },
        )
        folder = dict(_json_response(response))
        if folder.get("mimeType") != FOLDER_MIME_TYPE or folder.get("trashed"):
            raise GoogleDriveAccessError(
                "The selected Google Drive destination is not an available folder."
            )
        return folder

    def _managed_folder_query(
        self,
        *,
        profile_key: str,
        storage_kind: str,
        root_id: str | None = None,
    ) -> str:
        if not PROFILE_KEY_PATTERN.fullmatch(profile_key):
            raise GoogleDriveConfigurationError("The business profile key is invalid.")
        if storage_kind not in {"storage-root", *STORAGE_CHILD_NAMES}:
            raise GoogleDriveConfigurationError("The storage folder kind is invalid.")
        properties = [
            "appProperties has { key='tabulaRasaKind' and "
            f"value='{_escape_query_value(storage_kind)}' }}",
            "appProperties has { key='tabulaRasaProfile' and "
            f"value='{_escape_query_value(profile_key)}' }}",
        ]
        if root_id is not None:
            root_id = self._valid_folder_id(root_id)
            properties.append(
                "appProperties has { key='tabulaRasaStorageRoot' and "
                f"value='{_escape_query_value(root_id)}' }}"
            )
            properties.append(
                "'{0}' in parents".format(_escape_query_value(root_id))
            )
        return " and ".join(
            [
                "trashed = false",
                f"mimeType = '{FOLDER_MIME_TYPE}'",
                *properties,
            ]
        )

    def _list_managed_folders(
        self,
        *,
        profile_key: str,
        storage_kind: str,
        root_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._list(
            self._managed_folder_query(
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=root_id,
            ),
            page_size=1000,
            fetch_all=True,
        )

    def _validate_managed_folder(
        self,
        folder: Mapping[str, Any],
        *,
        profile_key: str,
        storage_kind: str,
        root_id: str | None = None,
    ) -> dict[str, str]:
        folder_id = self._valid_folder_id(str(folder.get("id", "")))
        if (
            folder.get("mimeType") != FOLDER_MIME_TYPE
            or folder.get("trashed")
            or not str(folder.get("name") or "").strip()
        ):
            raise GoogleDriveAccessError(
                "The managed Google Drive folder is not available."
            )
        parents = folder.get("parents")
        if not isinstance(parents, list):
            parents = []
        if root_id is not None and root_id not in parents:
            raise GoogleDriveAccessError(
                "The managed Google Drive folder is outside its profile storage root."
            )
        properties = folder.get("appProperties")
        if not isinstance(properties, Mapping):
            raise GoogleDriveAccessError(
                "The managed Google Drive folder is missing its identity metadata."
            )
        if (
            properties.get("tabulaRasaKind") != storage_kind
            or properties.get("tabulaRasaProfile") != profile_key
            or (
                root_id is not None
                and properties.get("tabulaRasaStorageRoot") != root_id
            )
        ):
            raise GoogleDriveAccessError(
                "The managed Google Drive folder identity does not match this profile."
            )
        return {"id": folder_id, "name": str(folder["name"])}

    def _metadata_create(self, metadata: Mapping[str, Any]) -> dict[str, Any]:
        self._invalidate_list_cache()
        response = self._request(
            "POST",
            f"{DRIVE_API_ROOT}/files",
            expected=(200, 201),
            retry_transient=False,
            params={
                "fields": "id,name,mimeType,trashed,parents,appProperties",
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": "application/json"},
            data=json.dumps(metadata, separators=(",", ":")).encode("utf-8"),
        )
        return dict(_json_response(response))

    def _ensure_managed_folder(
        self,
        *,
        profile_key: str,
        storage_kind: str,
        name: str,
        root_id: str | None = None,
    ) -> dict[str, str]:
        matches = self._list_managed_folders(
            profile_key=profile_key,
            storage_kind=storage_kind,
            root_id=root_id,
        )
        if len(matches) > 1:
            raise GoogleDriveConflictError(
                "Google Drive contains duplicate managed storage folders."
            )
        if matches:
            return self._validate_managed_folder(
                matches[0],
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=root_id,
            )

        metadata: dict[str, Any] = {
            "name": name,
            "mimeType": FOLDER_MIME_TYPE,
            "appProperties": {
                "tabulaRasaKind": storage_kind,
                "tabulaRasaProfile": profile_key,
            },
        }
        if root_id is not None:
            metadata["parents"] = [self._valid_folder_id(root_id)]
            metadata["appProperties"]["tabulaRasaStorageRoot"] = root_id

        for attempt in range(2):
            try:
                created = self._metadata_create(metadata)
            except GoogleDriveAccessError:
                reconciled = self._list_managed_folders(
                    profile_key=profile_key,
                    storage_kind=storage_kind,
                    root_id=root_id,
                )
                if len(reconciled) > 1:
                    raise GoogleDriveConflictError(
                        "Google Drive contains duplicate managed storage folders."
                    )
                if reconciled:
                    return self._validate_managed_folder(
                        reconciled[0],
                        profile_key=profile_key,
                        storage_kind=storage_kind,
                        root_id=root_id,
                    )
                if attempt == 1:
                    raise
                self.sleeper(1.0)
                continue
            created_id = str(created.get("id", ""))
            if not created_id:
                raise GoogleDriveAccessError(
                    "Google Drive did not return the managed folder identity."
                )
            return self._validate_managed_folder(
                created,
                profile_key=profile_key,
                storage_kind=storage_kind,
                root_id=root_id,
            )

    def create_storage_root(self, profile_key: str, name: str) -> dict[str, str]:
        """Create or reuse one app-managed storage root for a profile."""
        clean_name = _clean_text(name, maximum=255)
        if not clean_name:
            raise GoogleDriveConfigurationError("Storage root name is required.")
        return self._ensure_managed_folder(
            profile_key=profile_key,
            storage_kind="storage-root",
            name=clean_name,
        )

    def provision_storage_children(
        self,
        profile_key: str,
        root_id: str,
    ) -> dict[str, dict[str, str]]:
        """Create or reuse the receipt and ledger-backup children under a root."""
        root = self.folder(root_id)
        self._valid_folder_id(str(root.get("id", "")))
        children: dict[str, dict[str, str]] = {}
        for storage_kind, name in STORAGE_CHILD_NAMES.items():
            children[storage_kind] = self._ensure_managed_folder(
                profile_key=profile_key,
                storage_kind=storage_kind,
                name=name,
                root_id=root_id,
            )
        return children

    @staticmethod
    def _valid_folder_id(folder_id: str) -> str:
        folder_id = str(folder_id)
        if not DRIVE_ID_PATTERN.fullmatch(folder_id):
            raise GoogleDriveAccessError("The selected Google Drive folder is invalid.")
        return folder_id

    def _invalidate_list_cache(self) -> None:
        self._list_cache.clear()

    def _list(
        self,
        query: str,
        *,
        page_size: int = 100,
        order_by: str = "",
        use_cache: bool = False,
        fetch_all: bool = False,
    ) -> list[dict[str, Any]]:
        cache_key = (query, page_size, order_by, fetch_all)
        if use_cache and self.list_cache_ttl_seconds > 0:
            cached = self._list_cache.get(cache_key)
            if cached and self.clock() - cached[0] < self.list_cache_ttl_seconds:
                return [dict(item) for item in cached[1]]
        params = {
            "q": query,
            "pageSize": min(max(page_size, 1), 1000),
            "fields": (
                "nextPageToken,files(id,name,mimeType,trashed,size,createdTime,modifiedTime,"
                "description,webViewLink,appProperties,parents)"
            ),
            "spaces": "drive",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if order_by:
            params["orderBy"] = order_by
        result: list[dict[str, Any]] = []
        page_token = ""
        seen_page_tokens: set[str] = set()
        while True:
            page_params = dict(params)
            if page_token:
                page_params["pageToken"] = page_token
            response = self._request(
                "GET",
                f"{DRIVE_API_ROOT}/files",
                params=page_params,
            )
            payload = _json_response(response)
            files = payload.get("files", [])
            if not isinstance(files, list):
                raise GoogleDriveAccessError(
                    "Google Drive returned an unreadable file listing."
                )
            result.extend(
                dict(item) for item in files if isinstance(item, Mapping)
            )
            if not fetch_all:
                break
            next_page_token = payload.get("nextPageToken")
            if next_page_token is None:
                break
            if (
                not isinstance(next_page_token, str)
                or not next_page_token
                or next_page_token in seen_page_tokens
            ):
                raise GoogleDriveAccessError(
                    "Google Drive returned an unreadable file listing."
                )
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token
        if use_cache and self.list_cache_ttl_seconds > 0:
            self._list_cache[cache_key] = (self.clock(), result)
        return [dict(item) for item in result]

    def _multipart_create(
        self,
        metadata: Mapping[str, Any],
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        self._invalidate_list_cache()
        boundary = f"tabula-rasa-{secrets.token_hex(16)}"
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        ).encode("utf-8")
        body += json.dumps(metadata, separators=(",", ":")).encode("utf-8")
        body += (
            f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")
        body += content
        body += f"\r\n--{boundary}--\r\n".encode("utf-8")
        response = self._request(
            "POST",
            f"{DRIVE_UPLOAD_ROOT}/files",
            expected=(200, 201),
            retry_transient=False,
            params={
                "uploadType": "multipart",
                "fields": (
                    "id,name,mimeType,size,createdTime,modifiedTime,description,"
                    "webViewLink,appProperties"
                ),
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
        )
        return dict(_json_response(response))

    def delete_file(self, file_id: str) -> None:
        """Delete a file created and managed by the app."""
        self._invalidate_list_cache()
        self._request(
            "DELETE",
            f"{DRIVE_API_ROOT}/files/{file_id}",
            expected=(200, 204),
            params={"supportsAllDrives": "true"},
        )

    def upload_receipt(
        self,
        *,
        profile_key: str,
        transaction_id: str,
        folder_id: str,
        original_name: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        """Create one receipt without replacing a same-named Drive file."""
        if not content or len(content) > MAX_RECEIPT_BYTES:
            raise GoogleDriveAccessError(
                "Receipt files must be non-empty and no larger than 20 MB."
            )
        folder_id = self._valid_folder_id(folder_id)
        base_filename = safe_receipt_filename(original_name)
        original_filename = safe_receipt_filename(original_name)
        content_sha256 = hashlib.sha256(content).hexdigest()
        inventory_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
            ]
        )
        existing_names = {
            str(item.get("name", "")).casefold()
            for item in self._list(
                inventory_query,
                page_size=1000,
                fetch_all=True,
            )
            if item.get("name")
        }
        filename = ""
        for occurrence in range(1, 1001):
            candidate = suffixed_receipt_filename(
                base_filename,
                occurrence,
            )
            if candidate.casefold() not in existing_names:
                filename = candidate
                break
        if not filename:
            raise GoogleDriveAccessError(
                "Google Drive contains too many receipts with this filename. "
                "Rename the local file and retry."
            )
        receipt_id = secrets.token_hex(16)
        committed_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                f"name = '{_escape_query_value(filename)}'",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='receipt' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaTransaction' and "
                    f"value='{_escape_query_value(transaction_id)}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaReceiptId' and "
                    f"value='{receipt_id}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaSha256' and "
                    f"value='{content_sha256}' }}"
                ),
            ]
        )
        metadata = {
            "name": filename,
            "parents": [folder_id],
            "description": original_filename,
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": profile_key,
                "tabulaRasaTransaction": transaction_id,
                "tabulaRasaReceiptId": receipt_id,
                "tabulaRasaSha256": content_sha256,
            },
        }
        try:
            uploaded = self._multipart_create(
                metadata,
                content,
                mime_type or "application/octet-stream",
            )
        except GoogleDriveAccessError:
            # A disconnected response after Google committed the upload is
            # uncertain. Query by the deterministic name and app-properties
            # before reporting failure so a retry cannot create a duplicate.
            committed = self._list(committed_query, page_size=2)
            if committed:
                uploaded = committed[0]
            else:
                raise
        uploaded.setdefault("name", filename)
        uploaded.setdefault("mimeType", mime_type or "application/octet-stream")
        uploaded.setdefault("size", str(len(content)))
        uploaded.setdefault("description", original_filename)
        uploaded["appProperties"] = {
            **metadata["appProperties"],
            **(
                dict(uploaded.get("appProperties", {}))
                if isinstance(uploaded.get("appProperties"), Mapping)
                else {}
            ),
        }
        return uploaded

    def list_receipts(
        self,
        *,
        profile_key: str,
        transaction_id: str,
        folder_id: str,
    ) -> list[dict[str, Any]]:
        """List app-managed receipts for one transaction."""
        folder_id = self._valid_folder_id(folder_id)
        query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='receipt' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaTransaction' and "
                    f"value='{_escape_query_value(transaction_id)}' }}"
                ),
            ]
        )
        return self._list(
            query,
            page_size=100,
            order_by="createdTime desc",
            use_cache=True,
            fetch_all=True,
        )

    def list_profile_receipts(
        self,
        *,
        profile_key: str,
        folder_id: str,
        _force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """List every app-managed receipt available to one profile."""
        folder_id = self._valid_folder_id(folder_id)
        query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='receipt' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
            ]
        )
        return self._list(
            query,
            page_size=1000,
            order_by="createdTime desc",
            use_cache=not _force_refresh,
            fetch_all=True,
        )

    def backfill_receipt_checksum(
        self,
        *,
        profile_key: str,
        folder_id: str,
        file_id: str,
    ) -> dict[str, Any]:
        """Download one legacy receipt once and persist verified integrity metadata."""
        receipts = self.list_profile_receipts(
            profile_key=profile_key,
            folder_id=folder_id,
            _force_refresh=True,
        )
        matches = [item for item in receipts if str(item.get("id")) == str(file_id)]
        if len(matches) != 1:
            raise GoogleDriveAccessError(
                "The legacy receipt is not in this profile's selected receipt folder."
            )
        receipt = matches[0]
        try:
            receipt_reference_from_drive_file(receipt)
        except ReceiptManifestError:
            pass
        else:
            return receipt

        content = self.download_file(str(file_id))
        if not content or len(content) > MAX_RECEIPT_BYTES:
            raise GoogleDriveAccessError(
                "The legacy receipt is empty or exceeds the supported receipt size."
            )
        properties = receipt.get("appProperties")
        existing_properties = (
            dict(properties) if isinstance(properties, Mapping) else {}
        )
        existing_receipt_id = _clean_text(
            existing_properties.get("tabulaRasaReceiptId"), maximum=32
        )
        deterministic_legacy_id = hashlib.sha256(
            (
                "tabula-rasa-legacy-receipt:"
                f"{profile_key}:{file_id}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        receipt_id = (
            existing_receipt_id
            if RECEIPT_ID_PATTERN.fullmatch(existing_receipt_id)
            else deterministic_legacy_id
        )
        patch_properties = {
            **existing_properties,
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": receipt_id,
            "tabulaRasaSha256": hashlib.sha256(content).hexdigest(),
        }
        original_filename = safe_receipt_filename(
            str(
                receipt.get("description")
                or existing_properties.get("tabulaRasaOriginalName")
                or receipt.get("name")
                or "receipt"
            )
        )
        self._invalidate_list_cache()
        response = self._request(
            "PATCH",
            f"{DRIVE_API_ROOT}/files/{file_id}",
            params={
                "fields": (
                    "id,name,mimeType,size,createdTime,modifiedTime,"
                    "description,webViewLink,appProperties,parents"
                ),
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": "application/json; charset=UTF-8"},
            data=json.dumps(
                {
                    "appProperties": patch_properties,
                    "description": original_filename,
                }
            ),
        )
        updated = dict(_json_response(response))
        updated.setdefault("id", str(file_id))
        updated.setdefault("name", str(receipt.get("name") or "receipt"))
        updated.setdefault(
            "mimeType", str(receipt.get("mimeType") or "application/octet-stream")
        )
        updated.setdefault("size", str(len(content)))
        updated.setdefault("description", original_filename)
        updated["appProperties"] = patch_properties
        try:
            receipt_reference_from_drive_file(updated)
        except ReceiptManifestError as exc:
            raise GoogleDriveAccessError(
                "Google Drive did not confirm the receipt integrity backfill."
            ) from exc
        return updated

    def restore_receipt(
        self,
        *,
        profile_key: str,
        folder_id: str,
        stored_filename: str,
        original_filename: str,
        content: bytes,
        mime_type: str,
        receipt_id: str,
        sha256: str,
        old_file_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create or reuse one verified recovery file without suffixing its name."""
        try:
            stored_filename = validate_receipt_filename(
                stored_filename,
                "Receipt stored filename",
            )
            original_filename = validate_receipt_filename(
                original_filename,
                "Receipt original filename",
            )
        except ReceiptManifestError as exc:
            raise GoogleDriveAccessError(
                "Receipt recovery metadata or content failed integrity validation."
            ) from exc
        if (
            not content
            or len(content) > MAX_RECEIPT_BYTES
            or hashlib.sha256(content).hexdigest() != sha256
            or not RECEIPT_ID_PATTERN.fullmatch(str(receipt_id))
            or not SHA256_PATTERN.fullmatch(str(sha256))
            or not RECEIPT_DRIVE_ID_PATTERN.fullmatch(str(old_file_id))
        ):
            raise GoogleDriveAccessError(
                "Receipt recovery metadata or content failed integrity validation."
            )
        folder_id = self._valid_folder_id(folder_id)
        identity_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='receipt' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaReceiptId' and "
                    f"value='{receipt_id}' }}"
                ),
                (
                    "appProperties has { key='tabulaRasaSha256' and "
                    f"value='{sha256}' }}"
                ),
            ]
        )
        existing_identity = self._list(identity_query, page_size=2)
        if len(existing_identity) > 1:
            raise GoogleDriveConflictError(
                "Google Drive contains duplicate files for this receipt identity."
            )
        if existing_identity:
            existing = existing_identity[0]
            try:
                reference = receipt_reference_from_drive_file(existing)
            except ReceiptManifestError as exc:
                raise GoogleDriveConflictError(
                    "An existing recovered receipt has inconsistent metadata."
                ) from exc
            if (
                reference["name"] != stored_filename
                or reference["original_filename"] != original_filename
                or reference["mime_type"] != mime_type
                or reference["byte_size"] != len(content)
            ):
                raise GoogleDriveConflictError(
                    "An existing recovered receipt conflicts with the manifest."
                )
            existing_content = self.download_file(str(reference["id"]))
            if (
                len(existing_content) != len(content)
                or hashlib.sha256(existing_content).hexdigest() != sha256
            ):
                raise GoogleDriveConflictError(
                    "An existing recovered receipt failed checksum verification."
                )
            return existing, True

        filename_inventory_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
            ]
        )
        existing_names = {
            str(item.get("name", "")).casefold()
            for item in self._list(
                filename_inventory_query,
                page_size=1000,
                fetch_all=True,
            )
            if item.get("name")
        }
        if stored_filename.casefold() in existing_names:
            raise GoogleDriveConflictError(
                "A different Google Drive file already uses the recovery filename."
            )
        properties = {
            "tabulaRasaKind": "receipt",
            "tabulaRasaProfile": profile_key,
            "tabulaRasaReceiptId": receipt_id,
            "tabulaRasaSha256": sha256,
            "tabulaRasaOriginalFileId": old_file_id,
        }
        recovery_attempt_id = secrets.token_hex(16)
        metadata = {
            "name": stored_filename,
            "parents": [folder_id],
            "description": original_filename,
            "appProperties": {
                **properties,
                "tabulaRasaRecoveryAttempt": recovery_attempt_id,
            },
        }
        recovered_after_uncertain_response = False
        created_file_id = ""
        redundant_created_file_id = ""
        try:
            uploaded = self._multipart_create(metadata, content, mime_type)
            created_file_id = str(uploaded.get("id", ""))
        except GoogleDriveAccessError:
            recovered_after_uncertain_response = True
        committed = self._list(identity_query, page_size=1000)
        if not committed:
            raise GoogleDriveAccessError(
                "Google Drive did not confirm the recovered receipt upload."
            )
        attempt_matches = [
            item
            for item in committed
            if isinstance(item.get("appProperties"), Mapping)
            and item["appProperties"].get("tabulaRasaRecoveryAttempt")
            == recovery_attempt_id
        ]
        if len(attempt_matches) > 1:
            raise GoogleDriveConflictError(
                "Google Drive contains duplicate files for this recovery attempt."
            )
        if not created_file_id and attempt_matches:
            created_file_id = str(attempt_matches[0].get("id", ""))
        uploaded = min(
            committed,
            key=lambda item: (
                str(item.get("createdTime", "")),
                str(item.get("id", "")),
            ),
        )
        if created_file_id and str(uploaded.get("id", "")) != created_file_id:
            redundant_created_file_id = created_file_id
            recovered_after_uncertain_response = True
        uploaded.setdefault("name", stored_filename)
        uploaded.setdefault("mimeType", mime_type)
        uploaded.setdefault("size", str(len(content)))
        uploaded.setdefault("description", original_filename)
        uploaded["appProperties"] = {
            **properties,
            **(
                dict(uploaded.get("appProperties", {}))
                if isinstance(uploaded.get("appProperties"), Mapping)
                else {}
            ),
        }
        try:
            reference = receipt_reference_from_drive_file(uploaded)
        except ReceiptManifestError as exc:
            raise GoogleDriveAccessError(
                "Google Drive did not confirm the recovered receipt metadata."
            ) from exc
        if (
            reference["name"] != stored_filename
            or reference["original_filename"] != original_filename
            or reference["mime_type"] != mime_type
            or reference["byte_size"] != len(content)
        ):
            raise GoogleDriveConflictError(
                "A concurrent recovered receipt conflicts with the manifest."
            )
        if recovered_after_uncertain_response:
            committed_content = self.download_file(str(uploaded["id"]))
            if (
                len(committed_content) != len(content)
                or hashlib.sha256(committed_content).hexdigest() != sha256
            ):
                raise GoogleDriveConflictError(
                    "The recovered Google Drive upload failed checksum verification."
                )
        if redundant_created_file_id:
            # A concurrent recovery created the same stable identity first.
            # Only discard this invocation's later file after the canonical
            # object is fully validated, so callers converge without orphaning
            # a reference returned by another recovery command.
            self.delete_file(redundant_created_file_id)
        return uploaded, False

    def upload_backup(
        self,
        *,
        profile_key: str,
        folder_id: str,
        filename: str,
        content: bytes,
        sha256: str,
        backup_time: str,
        keep: int = 30,
    ) -> dict[str, Any]:
        """Idempotently upload a verified backup and apply retention."""
        if keep < 2:
            raise ValueError("keep must retain at least two backup generations")
        folder_id = self._valid_folder_id(folder_id)
        name_query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                f"name = '{_escape_query_value(filename)}'",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='backup' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
            ]
        )
        generations = self.list_backups(
            profile_key=profile_key,
            folder_id=folder_id,
            limit=1000,
            _force_refresh=True,
        )
        existing = [item for item in generations if item.get("name") == filename]
        if existing:
            uploaded = existing[0]
        else:
            try:
                uploaded = self._multipart_create(
                    {
                        "name": filename,
                        "parents": [folder_id],
                        "appProperties": {
                            "tabulaRasaKind": "backup",
                            "tabulaRasaProfile": profile_key,
                            "tabulaRasaSha256": sha256,
                            "tabulaRasaBackupTime": backup_time,
                        },
                    },
                    content,
                    "application/zip",
                )
            except GoogleDriveAccessError:
                committed = self._list(name_query, page_size=2)
                if not committed:
                    raise
                uploaded = committed[0]
            generations.insert(0, uploaded)
        for expired in generations[keep:]:
            self.delete_file(str(expired["id"]))
        return uploaded

    def list_backups(
        self,
        *,
        profile_key: str,
        folder_id: str,
        limit: int = 100,
        _force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """List app-managed cloud backups newest first."""
        folder_id = self._valid_folder_id(folder_id)
        query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                (
                    "appProperties has { key='tabulaRasaKind' and "
                    "value='backup' }"
                ),
                (
                    "appProperties has { key='tabulaRasaProfile' and "
                    f"value='{_escape_query_value(profile_key)}' }}"
                ),
            ]
        )
        return self._list(
            query,
            page_size=limit,
            order_by="createdTime desc",
            use_cache=not _force_refresh,
        )

    def download_file(self, file_id: str) -> bytes:
        """Download an authorized file for validation or recovery."""
        response = self._request(
            "GET",
            f"{DRIVE_API_ROOT}/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
        )
        return response.content


def backup_filename_and_hash(
    backup: bytes,
    manifest: Mapping[str, Any],
) -> tuple[str, str]:
    """Return the canonical cloud filename and SHA-256 for a verified backup."""
    timestamp = str(manifest["backup_time"]).replace("-", "").replace(":", "")
    timestamp = timestamp.replace("+0000", "Z")
    return (
        f"tabula-rosa-backup-{timestamp}.zip",
        hashlib.sha256(backup).hexdigest(),
    )


def backup_is_in_local_week(
    filename: str,
    *,
    local_date: datetime | None = None,
) -> bool:
    """Return whether a canonical UTC backup filename falls in the local week."""
    match = re.fullmatch(r"tabula-rosa-backup-(\d{8}T\d{6}Z)\.zip", filename)
    if not match:
        return False
    backup_date = (
        datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ")
        .replace(tzinfo=timezone.utc)
        .astimezone()
        .date()
    )
    requested = (local_date or datetime.now().astimezone()).date()
    return backup_date.isocalendar()[:2] == requested.isocalendar()[:2]
