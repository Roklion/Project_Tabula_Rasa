"""Local-only business-profile configuration storage.

The local store is deliberately separate from Streamlit Secrets. Hosted
deployments continue to use their platform-managed secrets, while an explicitly
enabled local app can merge profiles from this ignored JSON file.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from business_profiles import BusinessProfileConfigurationError, load_business_profiles


LOCAL_PROFILE_ADMIN_ENV = "TABULA_LOCAL_PROFILE_ADMIN"
LOCAL_PROFILE_STORE_PATH = (
    Path(__file__).resolve().parent
    / ".streamlit"
    / "local_business_profiles.json"
)
STORE_VERSION = 1
MAX_CREDENTIAL_BYTES = 64 * 1024
PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
SPREADSHEET_URL_PATTERN = re.compile(
    r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)"
)
SPREADSHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
DRIVE_FOLDER_URL_PATTERN = re.compile(
    r"https://drive\.google\.com/(?:drive/(?:u/\d+/)?folders|open\?id=)/([A-Za-z0-9_-]+)"
)
DRIVE_FOLDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
REQUIRED_CREDENTIAL_FIELDS = {
    "type",
    "project_id",
    "private_key",
    "client_email",
    "token_uri",
}
_STORE_LOCK = threading.Lock()


class LocalProfileStoreError(ValueError):
    """Raised when local profile configuration is missing or malformed."""


def local_profile_admin_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether the fail-closed local profile administrator is enabled."""
    values = os.environ if environment is None else environment
    return values.get(LOCAL_PROFILE_ADMIN_ENV) == "1"


def local_profile_admin_available(
    server_address: object,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Require both the explicit flag and a loopback-only Streamlit bind."""
    if not local_profile_admin_enabled(environment):
        return False
    address = str(server_address or "").strip().casefold()
    if address == "localhost":
        return True
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def parse_spreadsheet_id(value: str) -> str:
    """Return a validated spreadsheet ID from a raw ID or standard Sheets URL."""
    candidate = value.strip()
    match = SPREADSHEET_URL_PATTERN.search(candidate)
    spreadsheet_id = match.group(1) if match else candidate
    if not SPREADSHEET_ID_PATTERN.fullmatch(spreadsheet_id):
        raise LocalProfileStoreError(
            "Enter a valid Google Sheets URL or spreadsheet ID."
        )
    return spreadsheet_id


def parse_drive_folder_id(value: str) -> str:
    """Return a validated folder ID from a raw ID or standard Drive URL."""
    candidate = value.strip()
    match = DRIVE_FOLDER_URL_PATTERN.search(candidate)
    folder_id = match.group(1) if match else candidate
    if not DRIVE_FOLDER_ID_PATTERN.fullmatch(folder_id):
        raise LocalProfileStoreError(
            "Enter a valid Google Drive folder URL or folder ID."
        )
    return folder_id


def validate_backup_folder_path(value: str) -> str:
    """Return a normalized absolute local backup folder path."""
    candidate = value.strip()
    if not candidate or any(ord(character) < 32 for character in candidate):
        raise LocalProfileStoreError("Enter a valid backup folder path.")
    path = Path(candidate)
    if not path.is_absolute():
        raise LocalProfileStoreError(
            "Backup folder path must be absolute, such as "
            r"G:\My Drive\Tabula Rosa Backups\business."
        )
    return str(path)


def validate_profile_key(value: str) -> str:
    """Return a normalized, safe profile key."""
    key = value.strip()
    if not PROFILE_KEY_PATTERN.fullmatch(key):
        raise LocalProfileStoreError(
            "Profile key must start with a lowercase letter and contain only "
            "lowercase letters, numbers, underscores, or hyphens (48 characters max)."
        )
    return key


def parse_service_account_json(upload: bytes) -> dict[str, str]:
    """Parse and validate an uploaded Google service-account JSON document."""
    if not upload or len(upload) > MAX_CREDENTIAL_BYTES:
        raise LocalProfileStoreError(
            "Credential JSON must be a non-empty file smaller than 64 KB."
        )
    try:
        parsed = json.loads(upload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalProfileStoreError(
            "Credential file is not valid UTF-8 JSON."
        ) from exc
    if not isinstance(parsed, dict):
        raise LocalProfileStoreError(
            "Credential JSON must contain one service-account object."
        )
    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in parsed.items()):
        raise LocalProfileStoreError(
            "Credential JSON contains an unsupported value."
        )
    missing = sorted(REQUIRED_CREDENTIAL_FIELDS - parsed.keys())
    if missing or parsed.get("type") != "service_account":
        raise LocalProfileStoreError(
            "Credential JSON is not a complete Google service-account key."
        )
    private_key = parsed.get("private_key", "")
    if (
        "-----BEGIN PRIVATE KEY-----" not in private_key
        or "-----END PRIVATE KEY-----" not in private_key
    ):
        raise LocalProfileStoreError(
            "Credential JSON does not contain a valid private-key field."
        )
    return dict(parsed)


def build_profile_settings(
    name: str,
    spreadsheet: str,
    credential_upload: bytes,
    receipt_folder: str | None = None,
    backup_folder_path: str | None = None,
) -> dict[str, Any]:
    """Validate form values and return one profile settings mapping."""
    display_name = name.strip()
    if not display_name or len(display_name) > 100:
        raise LocalProfileStoreError(
            "Business name must contain between 1 and 100 characters."
        )
    settings = {
        "name": display_name,
        "spreadsheet_id": parse_spreadsheet_id(spreadsheet),
        "gcp_service_account": parse_service_account_json(credential_upload),
    }
    if receipt_folder is not None:
        settings["receipt_folder_id"] = parse_drive_folder_id(receipt_folder)
    if backup_folder_path is not None:
        settings["backup_folder_path"] = validate_backup_folder_path(
            backup_folder_path
        )
    return settings


def _validate_stored_profiles(profiles: object) -> dict[str, dict[str, Any]]:
    if not isinstance(profiles, dict):
        raise LocalProfileStoreError("Local profile store has an invalid format.")
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_settings in profiles.items():
        key = validate_profile_key(str(raw_key))
        if not isinstance(raw_settings, dict):
            raise LocalProfileStoreError("Local profile store has an invalid format.")
        try:
            settings = build_profile_settings(
                str(raw_settings.get("name", "")),
                str(raw_settings.get("spreadsheet_id", "")),
                json.dumps(raw_settings.get("gcp_service_account", {})).encode("utf-8"),
                (
                    str(raw_settings["receipt_folder_id"])
                    if "receipt_folder_id" in raw_settings
                    else None
                ),
                (
                    str(raw_settings["backup_folder_path"])
                    if "backup_folder_path" in raw_settings
                    else None
                ),
            )
        except (TypeError, LocalProfileStoreError) as exc:
            raise LocalProfileStoreError(
                f"Local profile '{key}' is incomplete or malformed."
            ) from exc
        normalized[key] = settings
    try:
        load_business_profiles({"business_profiles": normalized})
    except BusinessProfileConfigurationError as exc:
        raise LocalProfileStoreError(str(exc)) from exc
    return normalized


def load_local_profiles(path: Path = LOCAL_PROFILE_STORE_PATH) -> dict[str, dict[str, Any]]:
    """Load and validate the local profile store, returning an empty store if absent."""
    if not path.exists():
        return {}
    if path.is_symlink():
        raise LocalProfileStoreError(
            "Refusing to read a symbolic-link local profile store."
        )
    try:
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalProfileStoreError(
            "Local profile store could not be read safely."
        ) from exc
    if (
        not isinstance(document, dict)
        or document.get("version") != STORE_VERSION
        or set(document) != {"version", "business_profiles"}
    ):
        raise LocalProfileStoreError("Local profile store has an invalid format.")
    return _validate_stored_profiles(document["business_profiles"])


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise LocalProfileStoreError(
            "Refusing to replace a symbolic-link local profile store."
        )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=".local-business-profiles-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary_path, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        raise LocalProfileStoreError(
            "Local profile store could not be written safely."
        ) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_local_profile(
    key: str,
    settings: Mapping[str, Any],
    *,
    replace: bool = False,
    path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Atomically add or replace one validated profile in the local store."""
    profile_key = validate_profile_key(key)
    candidate = _validate_stored_profiles({profile_key: dict(settings)})[profile_key]
    with _STORE_LOCK:
        profiles = load_local_profiles(path)
        if profile_key in profiles and not replace:
            raise LocalProfileStoreError(
                "That profile key already exists in the local profile store."
            )
        profiles[profile_key] = candidate
        profiles = _validate_stored_profiles(profiles)
        content = (
            json.dumps(
                {"version": STORE_VERSION, "business_profiles": profiles},
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        _atomic_write(path, content)


def merged_profile_secrets(
    base_secrets: Mapping[str, Any],
    *,
    include_local: bool,
    path: Path = LOCAL_PROFILE_STORE_PATH,
) -> Mapping[str, Any]:
    """Merge local profiles over Streamlit-managed profiles when explicitly enabled."""
    if not include_local:
        return base_secrets
    local_profiles = load_local_profiles(path)
    if not local_profiles:
        return base_secrets

    configured = base_secrets.get("business_profiles")
    if isinstance(configured, Mapping):
        profiles = {
            str(key): dict(settings)
            for key, settings in configured.items()
            if isinstance(settings, Mapping)
        }
    elif (
        "spreadsheet_id" in base_secrets
        and "gcp_service_account" in base_secrets
    ):
        profiles = {
            "default": {
                "name": str(
                    base_secrets.get("business_name", "Heathcote Advisory LLC")
                ),
                "spreadsheet_id": str(base_secrets["spreadsheet_id"]),
                "gcp_service_account": dict(base_secrets["gcp_service_account"]),
            }
        }
    else:
        profiles = {}
    profiles.update(local_profiles)
    merged = dict(base_secrets)
    merged["business_profiles"] = profiles
    return merged


def local_profile_revision(path: Path = LOCAL_PROFILE_STORE_PATH) -> str:
    """Return a non-secret cache revision for the current local store."""
    if not path.exists():
        return "absent"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise LocalProfileStoreError(
            "Local profile store could not be read safely."
        ) from exc
