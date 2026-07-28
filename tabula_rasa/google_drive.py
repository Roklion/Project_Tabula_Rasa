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


class GoogleDriveError(RuntimeError):
    """Base class for safe Google Drive failures."""


class GoogleDriveConfigurationError(GoogleDriveError):
    """Raised when application or profile Drive settings are incomplete."""


class GoogleDriveAuthorizationError(GoogleDriveError):
    """Raised when Google authorization is rejected, invalid, or revoked."""


class GoogleDriveAccessError(GoogleDriveError):
    """Raised when a Drive API operation cannot be completed."""


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
    for field in ("receipt_folder", "backup_folder"):
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


def safe_receipt_filename(transaction_id: str, original_name: str) -> str:
    """Return a safe receipt name that remains associated with a transaction."""
    cleaned = SAFE_RECEIPT_NAME_PATTERN.sub("_", PathName(original_name).name).strip(
        " ."
    )
    if not cleaned:
        cleaned = "receipt"
    cleaned = cleaned[:180]
    return f"{transaction_id}-{cleaned}"


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
            tuple[str, int, str],
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
            if (
                retry_transient
                and response.status_code in {429, 500, 502, 503, 504}
                and attempt < 3
            ):
                self.sleeper(2**attempt)
                continue
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
                "fields": "id,name,mimeType,trashed,webViewLink",
                "supportsAllDrives": "true",
            },
        )
        folder = dict(_json_response(response))
        if folder.get("mimeType") != FOLDER_MIME_TYPE or folder.get("trashed"):
            raise GoogleDriveAccessError(
                "The selected Google Drive destination is not an available folder."
            )
        return folder

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
    ) -> list[dict[str, Any]]:
        cache_key = (query, page_size, order_by)
        if use_cache and self.list_cache_ttl_seconds > 0:
            cached = self._list_cache.get(cache_key)
            if cached and self.clock() - cached[0] < self.list_cache_ttl_seconds:
                return [dict(item) for item in cached[1]]
        params = {
            "q": query,
            "pageSize": min(max(page_size, 1), 1000),
            "fields": (
                "files(id,name,mimeType,size,createdTime,modifiedTime,"
                "webViewLink,appProperties,parents)"
            ),
            "spaces": "drive",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if order_by:
            params["orderBy"] = order_by
        response = self._request(
            "GET",
            f"{DRIVE_API_ROOT}/files",
            params=params,
        )
        files = _json_response(response).get("files", [])
        if not isinstance(files, list):
            raise GoogleDriveAccessError(
                "Google Drive returned an unreadable file listing."
            )
        result = [dict(item) for item in files if isinstance(item, Mapping)]
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
                "fields": "id,name,size,createdTime,modifiedTime,webViewLink,appProperties",
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            data=body,
        )
        return dict(_json_response(response))

    def _replace_content(
        self,
        file_id: str,
        content: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        self._invalidate_list_cache()
        response = self._request(
            "PATCH",
            f"{DRIVE_UPLOAD_ROOT}/files/{file_id}",
            params={
                "uploadType": "media",
                "fields": "id,name,size,createdTime,modifiedTime,webViewLink,appProperties",
                "supportsAllDrives": "true",
            },
            headers={"Content-Type": mime_type},
            data=content,
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
        """Create or idempotently replace one transaction receipt."""
        if not content or len(content) > MAX_RECEIPT_BYTES:
            raise GoogleDriveAccessError(
                "Receipt files must be non-empty and no larger than 20 MB."
            )
        folder_id = self._valid_folder_id(folder_id)
        filename = safe_receipt_filename(transaction_id, original_name)
        query = " and ".join(
            [
                f"'{_escape_query_value(folder_id)}' in parents",
                "trashed = false",
                f"name = '{_escape_query_value(filename)}'",
                (
                    "appProperties has { key='tabulaRasaTransaction' and "
                    f"value='{_escape_query_value(transaction_id)}' }}"
                ),
            ]
        )
        existing = self._list(query, page_size=2)
        if existing:
            return self._replace_content(
                str(existing[0]["id"]),
                content,
                mime_type or "application/octet-stream",
            )
        metadata = {
            "name": filename,
            "parents": [folder_id],
            "appProperties": {
                "tabulaRasaKind": "receipt",
                "tabulaRasaProfile": profile_key,
                "tabulaRasaTransaction": transaction_id,
            },
        }
        try:
            return self._multipart_create(
                metadata,
                content,
                mime_type or "application/octet-stream",
            )
        except GoogleDriveAccessError:
            # A disconnected response after Google committed the upload is
            # uncertain. Query by the deterministic name and app-properties
            # before reporting failure so a retry cannot create a duplicate.
            committed = self._list(query, page_size=2)
            if committed:
                return committed[0]
            raise

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
        )

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
