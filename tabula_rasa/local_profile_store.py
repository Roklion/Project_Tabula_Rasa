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
import tomllib
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tabula_rasa.business_profiles import (
    BusinessProfileConfigurationError,
    load_business_profiles,
)
from tabula_rasa.google_drive import (
    GoogleDriveConfigurationError,
    validate_drive_profile_settings,
)
from tabula_rasa.synology_recovery import (
    SynologyRecoveryConfigurationError,
    validate_synology_recovery_settings,
)


LOCAL_PROFILE_ADMIN_ENV = "TABULA_LOCAL_PROFILE_ADMIN"
LOCAL_PROFILE_STORE_PATH = (
    Path(__file__).resolve().parents[1]
    / ".streamlit"
    / "business_profiles.json"
)
STORE_VERSION = 1
MAX_CREDENTIAL_BYTES = 64 * 1024
HOSTED_PROFILE_FIELDS = (
    "name",
    "spreadsheet_id",
    "gcp_service_account",
)
PROFILE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
SPREADSHEET_URL_PATTERN = re.compile(
    r"https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)"
)
SPREADSHEET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,}$")
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


def ensure_google_drive_disconnect_allowed(
    profile_settings: Mapping[str, Any],
) -> None:
    """Reject Drive disconnect while Synology recovery depends on it."""
    recovery = profile_settings.get("synology_recovery")
    if isinstance(recovery, Mapping):
        raise LocalProfileStoreError(
            "Disable Synology recovery before disconnecting "
            "this profile's Google Drive."
        )


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


def suggest_profile_key(value: str) -> str:
    """Suggest an editable safe profile key from a business display name."""
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    if not slug or not slug[0].isalpha():
        slug = f"business-{slug}" if slug else "business"
    return slug[:48].rstrip("-_") or "business"


def project_hosted_profiles(
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the explicit profile subset consumed by the hosted runtime."""
    configured = load_business_profiles({"business_profiles": profiles})
    projected: dict[str, dict[str, Any]] = {}
    for profile in configured:
        settings = profile.secrets
        hosted = {
            key: settings[key]
            for key in HOSTED_PROFILE_FIELDS
            if key in settings
        }
        hosted["name"] = profile.name
        if "google_drive" in settings:
            try:
                hosted["google_drive"] = validate_drive_profile_settings(
                    settings["google_drive"]
                )
            except GoogleDriveConfigurationError as exc:
                raise GoogleDriveConfigurationError(
                    f"Google Drive settings for profile '{profile.key}' are invalid: "
                    f"{exc}"
                ) from exc
        projected[profile.key] = hosted
    return projected


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
    backup_folder_path: str | None = None,
    google_drive: Mapping[str, Any] | None = None,
    synology_recovery: Mapping[str, Any] | None = None,
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
    if backup_folder_path is not None and backup_folder_path.strip():
        settings["backup_folder_path"] = validate_backup_folder_path(
            backup_folder_path
        )
    if google_drive is not None:
        try:
            settings["google_drive"] = validate_drive_profile_settings(google_drive)
        except GoogleDriveConfigurationError as exc:
            raise LocalProfileStoreError(str(exc)) from exc
    if synology_recovery is not None:
        try:
            settings["synology_recovery"] = validate_synology_recovery_settings(
                synology_recovery
            )
        except SynologyRecoveryConfigurationError as exc:
            raise LocalProfileStoreError(str(exc)) from exc
    return settings


def _validate_stored_profiles(profiles: object) -> dict[str, dict[str, Any]]:
    if not isinstance(profiles, dict):
        raise LocalProfileStoreError("Local profile store has an invalid format.")
    normalized: dict[str, dict[str, Any]] = {}
    storage_roots: dict[str, str] = {}
    synology_destinations: dict[str, str] = {}
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
                    str(raw_settings["backup_folder_path"])
                    if "backup_folder_path" in raw_settings
                    else None
                ),
                (
                    raw_settings["google_drive"]
                    if "google_drive" in raw_settings
                    else None
                ),
                (
                    raw_settings["synology_recovery"]
                    if "synology_recovery" in raw_settings
                    else None
                ),
            )
        except (TypeError, LocalProfileStoreError) as exc:
            raise LocalProfileStoreError(
                f"Local profile '{key}' is incomplete or malformed: {exc}"
            ) from exc
        drive_settings = settings.get("google_drive")
        storage_root = (
            drive_settings.get("storage_root")
            if isinstance(drive_settings, Mapping)
            else None
        )
        root_id = (
            str(storage_root.get("id", ""))
            if isinstance(storage_root, Mapping)
            else ""
        )
        if root_id and root_id in storage_roots:
            raise LocalProfileStoreError(
                "A Google Drive storage root can belong to only one business "
                "profile."
            )
        if root_id:
            storage_roots[root_id] = key
        recovery = settings.get("synology_recovery")
        if isinstance(recovery, Mapping):
            destination = str(recovery["destination_path"]).casefold()
            for other_key, other_destination in synology_destinations.items():
                if (
                    destination == other_destination
                    or destination.startswith(other_destination + "/")
                    or other_destination.startswith(destination + "/")
                ):
                    raise LocalProfileStoreError(
                        "Synology recovery destinations for profiles "
                        f"'{other_key}' and '{key}' must not share or overlap."
                    )
            synology_destinations[key] = destination
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
        _write_local_profiles(path, profiles)


def _write_local_profiles(
    path: Path,
    profiles: Mapping[str, Mapping[str, Any]],
) -> None:
    validated = _validate_stored_profiles(dict(profiles))
    content = (
        json.dumps(
            {"version": STORE_VERSION, "business_profiles": validated},
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write(path, content)


def build_profile_edit_settings(
    existing: Mapping[str, Any],
    name: str,
    spreadsheet: str,
    backup_folder_path: str | None,
    credential_upload: bytes | None = None,
) -> dict[str, Any]:
    """Build validated settings while preserving omitted profile-scoped values."""
    if credential_upload is None:
        credential = existing.get("gcp_service_account")
        if not isinstance(credential, Mapping):
            raise LocalProfileStoreError(
                "The existing profile does not contain a valid service-account key."
            )
        try:
            credential_upload = json.dumps(dict(credential)).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise LocalProfileStoreError(
                "The existing profile credential could not be validated safely."
            ) from exc
    return build_profile_settings(
        name,
        spreadsheet,
        credential_upload,
        backup_folder_path,
        existing.get("google_drive"),
        existing.get("synology_recovery"),
    )


def update_local_profile(
    key: str,
    *,
    name: str,
    spreadsheet: str,
    backup_folder_path: str | None,
    credential_upload: bytes | None = None,
    path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Atomically edit profile settings without changing the immutable key."""
    profile_key = validate_profile_key(key)
    with _STORE_LOCK:
        profiles = load_local_profiles(path)
        existing = profiles.get(profile_key)
        if existing is None:
            raise LocalProfileStoreError(
                "Only a stored local business profile can be edited."
            )
        candidate = build_profile_edit_settings(
            existing,
            name,
            spreadsheet,
            backup_folder_path,
            credential_upload,
        )
        folded_name = candidate["name"].casefold()
        if any(
            other_key != profile_key
            and str(other_settings.get("name", "")).casefold() == folded_name
            for other_key, other_settings in profiles.items()
        ):
            raise LocalProfileStoreError(
                "Business display names must be unique."
            )
        profiles[profile_key] = candidate
        _write_local_profiles(path, profiles)


def update_local_profile_google_drive(
    key: str,
    google_drive: Mapping[str, Any] | None,
    *,
    path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Atomically replace or remove one local profile's Drive authorization."""
    profile_key = validate_profile_key(key)
    with _STORE_LOCK:
        profiles = load_local_profiles(path)
        if profile_key not in profiles:
            raise LocalProfileStoreError(
                "Google Drive can only be connected to a local business profile."
            )
        candidate = dict(profiles[profile_key])
        if google_drive is None:
            ensure_google_drive_disconnect_allowed(candidate)
            candidate.pop("google_drive", None)
        else:
            try:
                validated_drive = validate_drive_profile_settings(google_drive)
            except GoogleDriveConfigurationError as exc:
                raise LocalProfileStoreError(str(exc)) from exc
            recovery = candidate.get("synology_recovery")
            if isinstance(recovery, Mapping):
                if any(
                    not isinstance(validated_drive.get(field), Mapping)
                    for field in ("storage_root", "receipt_folder", "backup_folder")
                ):
                    raise LocalProfileStoreError(
                        "Disable Synology recovery before saving "
                        "Google Drive settings without its storage root and both "
                        "child folders."
                    )
                existing_drive = candidate.get("google_drive")
                existing_root = (
                    existing_drive.get("storage_root")
                    if isinstance(existing_drive, Mapping)
                    else None
                )
                proposed_root = validated_drive.get("storage_root")
                existing_root_id = (
                    str(existing_root.get("id", ""))
                    if isinstance(existing_root, Mapping)
                    else ""
                )
                proposed_root_id = (
                    str(proposed_root.get("id", ""))
                    if isinstance(proposed_root, Mapping)
                    else ""
                )
                if existing_root_id != proposed_root_id:
                    raise LocalProfileStoreError(
                        "Disable Synology recovery before changing "
                        "this profile's Google Drive storage root."
                    )
            candidate["google_drive"] = validated_drive
        profiles[profile_key] = candidate
        _write_local_profiles(path, profiles)


def update_local_profile_synology_recovery(
    key: str,
    synology_recovery: Mapping[str, Any] | None,
    *,
    path: Path = LOCAL_PROFILE_STORE_PATH,
) -> None:
    """Atomically replace or remove one profile's Synology recovery metadata."""
    profile_key = validate_profile_key(key)
    with _STORE_LOCK:
        profiles = load_local_profiles(path)
        if profile_key not in profiles:
            raise LocalProfileStoreError(
                "Synology recovery can only be configured for a local business "
                "profile."
            )
        candidate = dict(profiles[profile_key])
        if synology_recovery is None:
            candidate.pop("synology_recovery", None)
        else:
            try:
                recovery = validate_synology_recovery_settings(synology_recovery)
            except SynologyRecoveryConfigurationError as exc:
                raise LocalProfileStoreError(str(exc)) from exc
            drive = candidate.get("google_drive")
            if not isinstance(drive, Mapping) or any(
                not isinstance(drive.get(field), Mapping)
                for field in ("storage_root", "receipt_folder", "backup_folder")
            ):
                raise LocalProfileStoreError(
                    "Provision the profile storage root and both Google Drive "
                    "children before enabling its Synology recovery copy."
                )
            candidate["synology_recovery"] = recovery
        profiles[profile_key] = candidate
        _write_local_profiles(path, profiles)


def merged_profile_secrets(
    base_secrets: Mapping[str, Any],
    *,
    path: Path = LOCAL_PROFILE_STORE_PATH,
) -> Mapping[str, Any]:
    """Merge canonical local JSON profiles into app-level secrets."""
    local_profiles = load_local_profiles(path)
    if not local_profiles:
        return base_secrets
    merged = dict(base_secrets)
    merged.pop("spreadsheet_id", None)
    merged.pop("business_name", None)
    merged.pop("gcp_service_account", None)
    merged["business_profiles"] = local_profiles
    return merged


def load_business_profile_document(
    secrets_path: Path,
    *,
    profiles_path: Path = LOCAL_PROFILE_STORE_PATH,
) -> Mapping[str, Any]:
    """Load app secrets plus canonical JSON business profiles."""
    try:
        with secrets_path.open("rb") as secrets_file:
            base_secrets = tomllib.load(secrets_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LocalProfileStoreError(
            "Application secrets could not be read safely."
        ) from exc
    return merged_profile_secrets(
        base_secrets,
        path=profiles_path,
    )


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
