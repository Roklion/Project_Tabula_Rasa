"""Create, validate, and retain versioned Google Sheets ledger backups."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import load_business_profiles, select_profile_secrets
from tabula_rasa.google_drive import (
    GoogleDriveClient,
    GoogleDriveConfigurationError,
    backup_filename_and_hash,
    backup_is_in_local_week,
    load_oauth_config,
)
from tabula_rasa.local_profile_store import (
    load_business_profile_document,
    validate_profile_key,
)
from tabula_rasa.receipt_backfill import prepare_backup_receipt_manifest
from tabula_rasa.storage import GoogleSheetsStorage
from tabula_rasa.storage.google_sheets import BACKUP_FORMAT_VERSION


BACKUP_NAME = re.compile(r"^tabula-rosa-backup-\d{8}T\d{6}Z\.zip$")
_PROFILE_CONFIG = object()


def verified_backup_for_week(
    output_dir: Path,
    *,
    local_date: date | None = None,
    profile_key: str | None = None,
) -> Path | None:
    """Find a valid profile backup in the requested local week."""
    output_dir = output_dir.resolve()
    if not output_dir.is_dir():
        return None
    requested_week = (local_date or date.today()).isocalendar()[:2]
    for path in sorted(output_dir.iterdir(), reverse=True):
        if not path.is_file() or not BACKUP_NAME.fullmatch(path.name):
            continue
        timestamp = path.name.removeprefix("tabula-rosa-backup-").removesuffix(
            ".zip"
        )
        backup_local_date = (
            datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ")
            .replace(tzinfo=timezone.utc)
            .astimezone()
            .date()
        )
        if backup_local_date.isocalendar()[:2] != requested_week:
            continue
        try:
            manifest = GoogleSheetsStorage.validate_backup_zip(path.read_bytes())
        except (OSError, RuntimeError):
            continue
        if (
            manifest.get("format_version") == BACKUP_FORMAT_VERSION
            and (
                profile_key is None
                or manifest.get("business_profile_key") == profile_key
            )
        ):
            return path
    return None


def resolve_backup_output_dir(
    profile_secrets: Mapping[str, Any],
    override: Path | None,
    profile_key: str | None = None,
    *,
    profile_scoped: bool = False,
) -> Path:
    """Resolve an explicit override, profile path, or profile-scoped default."""
    if override is not None:
        return override
    configured = str(profile_secrets.get("backup_folder_path", "")).strip()
    if configured:
        configured_path = Path(configured)
        if profile_scoped:
            if profile_key is None:
                raise ValueError(
                    "A profile key is required for a profile-scoped local destination."
                )
            return configured_path / validate_profile_key(profile_key)
        return configured_path
    if profile_key is None:
        raise ValueError(
            "A profile key is required when no local backup folder is configured."
        )
    return PROJECT_ROOT / "backups" / validate_profile_key(profile_key)


def write_versioned_backup(
    storage: GoogleSheetsStorage,
    output_dir: Path,
    receipt_manifest: Mapping[str, Any],
    *,
    keep: int = 30,
    profile_key: str | None = None,
) -> Path:
    """Write one verified backup and retain the newest requested generations."""
    if keep < 2:
        raise ValueError("keep must retain at least two backup generations")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    backup = storage.export_backup_zip(receipt_manifest)
    manifest = storage.validate_backup_zip(backup)
    timestamp = str(manifest["backup_time"]).replace("-", "").replace(":", "")
    timestamp = timestamp.replace("+0000", "Z")
    destination = output_dir / f"tabula-rosa-backup-{timestamp}.zip"
    with destination.open("xb") as backup_file:
        backup_file.write(backup)

    generations: list[Path] = []
    for path in output_dir.iterdir():
        if not path.is_file() or not BACKUP_NAME.fullmatch(path.name):
            continue
        if profile_key is not None:
            try:
                existing_manifest = GoogleSheetsStorage.validate_backup_zip(
                    path.read_bytes()
                )
            except (OSError, RuntimeError):
                continue
            if existing_manifest.get("business_profile_key") != profile_key:
                continue
        generations.append(path)
    generations.sort(key=lambda path: path.name, reverse=True)
    for expired in generations[keep:]:
        expired.unlink()
    return destination


def upload_versioned_backup_to_drive(
    all_secrets: Mapping[str, Any],
    profile_key: str,
    profile_secrets: Mapping[str, Any],
    storage: GoogleSheetsStorage,
    *,
    keep: int = 30,
) -> dict[str, Any]:
    """Upload one verified backup to the profile's authorized Drive folder."""
    drive_settings = profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        raise GoogleDriveConfigurationError(
            "Google Drive is not connected for this business profile."
        )
    backup_folder = drive_settings.get("backup_folder")
    if not isinstance(backup_folder, Mapping):
        raise GoogleDriveConfigurationError(
            "No Google Drive backup folder is selected for this profile."
        )
    client = GoogleDriveClient(load_oauth_config(all_secrets), drive_settings)
    receipt_manifest = build_backup_receipt_manifest(
        profile_key,
        profile_secrets,
        storage,
        client=client,
    )
    backup = storage.export_backup_zip(receipt_manifest)
    manifest = storage.validate_backup_zip(backup)
    filename, sha256 = backup_filename_and_hash(backup, manifest)
    return client.upload_backup(
        profile_key=profile_key,
        folder_id=str(backup_folder["id"]),
        filename=filename,
        content=backup,
        sha256=sha256,
        backup_time=str(manifest["backup_time"]),
        keep=keep,
    )


def build_backup_receipt_manifest(
    profile_key: str,
    profile_secrets: Mapping[str, Any],
    storage: GoogleSheetsStorage,
    *,
    client: GoogleDriveClient | None = None,
) -> dict[str, Any]:
    """Build a fresh inventory for the selected profile's receipt folder."""
    drive_settings = profile_secrets.get("google_drive")
    receipt_folder = (
        drive_settings.get("receipt_folder")
        if isinstance(drive_settings, Mapping)
        else None
    )
    if not isinstance(receipt_folder, Mapping):
        raise GoogleDriveConfigurationError(
            "A current-format backup requires a selected Google Drive receipt "
            "folder so its receipt inventory is complete."
        )
    if client is None:
        raise GoogleDriveConfigurationError(
            "A Google Drive client is required to inventory receipts."
        )
    return prepare_backup_receipt_manifest(
        storage,
        client,
        profile_key=profile_key,
        folder_id=str(receipt_folder["id"]),
    )


def verified_drive_backup_for_week(
    all_secrets: Mapping[str, Any],
    profile_key: str,
    profile_secrets: Mapping[str, Any],
    *,
    local_date: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the newest verified current-format backup in the local week."""
    drive_settings = profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        return None
    backup_folder = drive_settings.get("backup_folder")
    if not isinstance(backup_folder, Mapping):
        return None
    client = GoogleDriveClient(load_oauth_config(all_secrets), drive_settings)
    for item in client.list_backups(
        profile_key=profile_key,
        folder_id=str(backup_folder["id"]),
        limit=30,
    ):
        if not backup_is_in_local_week(
            str(item.get("name", "")),
            local_date=local_date,
        ):
            continue
        try:
            backup = client.download_file(str(item.get("id", "")))
            manifest = GoogleSheetsStorage.validate_backup_zip(backup)
        except RuntimeError:
            continue
        if manifest.get("format_version") == BACKUP_FORMAT_VERSION:
            return item
    return None


def _profile_destination_is_configured(
    profile_secrets: Mapping[str, Any], *, local: bool
) -> bool:
    """Return whether an all-profile run can attempt this destination.

    A profile without a Drive receipt folder cannot produce the current backup
    format in either mode. Cloud mode additionally requires a Drive backup
    folder. Unconfigured profiles are reported as skipped so one disconnected
    profile does not hide backups for the remaining configured profiles.
    """
    drive_settings = profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        return False
    receipt_folder = drive_settings.get("receipt_folder")
    receipt_id = (
        receipt_folder.get("id") if isinstance(receipt_folder, Mapping) else None
    )
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        return False
    if local:
        return True
    backup_folder = drive_settings.get("backup_folder")
    backup_id = (
        backup_folder.get("id") if isinstance(backup_folder, Mapping) else None
    )
    return isinstance(backup_id, str) and bool(backup_id.strip())


def _sanitized_profile_result(
    profile_key: str, status: str, detail: str | None = None
) -> dict[str, str]:
    """Build a result that contains no exception text or private data."""
    result = {"profile": profile_key, "status": status}
    if detail:
        result["detail"] = detail
    return result


def backup_all_profiles(
    all_secrets: Mapping[str, Any],
    profiles: list[Any],
    *,
    local: bool = False,
    keep: int = 30,
    once_per_week: bool = False,
) -> list[dict[str, str]]:
    """Back up every eligible profile, continuing after individual failures.

    The profile mapping is passed directly to each storage and Drive helper;
    no selected-profile fallback is used. This keeps credentials, tokens,
    folders, receipt inventories, and local destinations isolated.
    """
    results: list[dict[str, str]] = []
    for profile in profiles:
        profile_key = str(profile.key)
        profile_secrets = profile.secrets
        if not _profile_destination_is_configured(profile_secrets, local=local):
            destination = (
                "local receipt folder"
                if local
                else "required Google Drive folders"
            )
            verb = "is" if local else "are"
            result = _sanitized_profile_result(
                profile_key,
                "skip",
                f"{destination} {verb} not configured",
            )
            results.append(result)
            print(f"Profile {profile_key}: skipped ({result['detail']})")
            continue

        try:
            if local:
                output_dir = resolve_backup_output_dir(
                    profile_secrets,
                    None,
                    profile_key,
                    profile_scoped=True,
                )
                if (
                    once_per_week
                    and verified_backup_for_week(
                        output_dir,
                        profile_key=profile_key,
                    )
                    is not None
                ):
                    result = _sanitized_profile_result(
                        profile_key,
                        "skip",
                        "weekly backup already verified",
                    )
                    results.append(result)
                    print(f"Profile {profile_key}: skipped (weekly backup already verified)")
                    continue
                storage = GoogleSheetsStorage.from_secrets(profile_secrets)
                drive_settings = profile_secrets.get("google_drive")
                drive_client = GoogleDriveClient(
                    load_oauth_config(all_secrets), drive_settings
                )
                receipt_manifest = build_backup_receipt_manifest(
                    profile_key,
                    profile_secrets,
                    storage,
                    client=drive_client,
                )
                destination = write_versioned_backup(
                    storage,
                    output_dir,
                    receipt_manifest,
                    keep=keep,
                    profile_key=profile_key,
                )
                result = _sanitized_profile_result(
                    profile_key,
                    "success",
                    f"local archive {destination.name} created",
                )
            else:
                if once_per_week and verified_drive_backup_for_week(
                    all_secrets,
                    profile_key,
                    profile_secrets,
                ) is not None:
                    result = _sanitized_profile_result(
                        profile_key,
                        "skip",
                        "weekly backup already verified",
                    )
                    results.append(result)
                    print(f"Profile {profile_key}: skipped (weekly backup already verified)")
                    continue
                storage = GoogleSheetsStorage.from_secrets(profile_secrets)
                upload_versioned_backup_to_drive(
                    all_secrets,
                    profile_key,
                    profile_secrets,
                    storage,
                    keep=keep,
                )
                result = _sanitized_profile_result(
                    profile_key,
                    "success",
                    "Google Drive backup created",
                )
            results.append(result)
            print(f"Profile {profile_key}: success ({result['detail']})")
        except Exception as exc:  # noqa: BLE001 - continue independent profiles
            result = _sanitized_profile_result(
                profile_key,
                "failure",
                f"{type(exc).__name__}"
            )
            results.append(result)
            print(f"Profile {profile_key}: failure ({result['detail']})")

    failures = sum(result["status"] == "failure" for result in results)
    successes = sum(result["status"] == "success" for result in results)
    skips = sum(result["status"] == "skip" for result in results)
    print(
        "All-profile backup summary: "
        f"success={successes} skipped={skips} failed={failures}"
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Back up the live ledger to a versioned ZIP archive"
    )
    parser.add_argument(
        "--secrets",
        type=Path,
        default=PROJECT_ROOT / ".streamlit" / "secrets.toml",
        help="Streamlit secrets file containing the spreadsheet credentials",
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        nargs="?",
        const=_PROFILE_CONFIG,
        metavar="PATH",
        help=(
            "Write a local backup instead of using Google Drive; optionally "
            "override the profile's backup_folder_path"
        ),
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=30,
        help="Number of timestamped generations to retain (minimum 2)",
    )
    parser.add_argument(
        "--once-per-week",
        action="store_true",
        help="Exit successfully when this folder already has a verified backup for the local ISO week",
    )
    parser.add_argument(
        "--google-drive",
        action="store_true",
        help=(
            "Upload through the Drive API using the selected profile folder "
            "instead of writing a local archive"
        ),
    )
    parser.add_argument("--profile", help="Business profile key to back up")
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Back up every eligible configured profile independently",
    )
    args = parser.parse_args()

    all_secrets = load_business_profile_document(args.secrets)
    profiles = load_business_profiles(all_secrets)
    if args.all_profiles and args.profile:
        raise SystemExit("--all-profiles cannot be combined with --profile")
    if args.all_profiles and args.google_drive and args.local_dir is not None:
        raise SystemExit("--local-dir cannot be combined with --google-drive")
    if args.all_profiles and args.local_dir not in (None, _PROFILE_CONFIG):
        raise SystemExit(
            "An explicit --local-dir PATH is only available for single-profile backups"
        )
    if args.all_profiles:
        results = backup_all_profiles(
            all_secrets,
            profiles,
            local=args.local_dir is _PROFILE_CONFIG,
            keep=args.keep,
            once_per_week=args.once_per_week,
        )
        return int(any(result["status"] == "failure" for result in results))
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    if args.google_drive and args.local_dir is not None:
        raise SystemExit("--local-dir cannot be combined with --google-drive")
    selected_profile_key = args.profile or profiles[0].key
    secrets = select_profile_secrets(all_secrets, args.profile)

    if args.local_dir is None or args.google_drive:
        if args.once_per_week:
            existing_drive = verified_drive_backup_for_week(
                all_secrets,
                selected_profile_key,
                secrets,
            )
            if existing_drive is not None:
                print(
                    "Weekly Google Drive backup already verified: "
                    f"{existing_drive.get('name', 'backup')}"
                )
                return 0
        storage = GoogleSheetsStorage.from_secrets(secrets)
        uploaded = upload_versioned_backup_to_drive(
            all_secrets,
            selected_profile_key,
            secrets,
            storage,
            keep=args.keep,
        )
        print(f"Verified Google Drive backup created: {uploaded.get('name', 'backup')}")
        return 0

    output_dir = resolve_backup_output_dir(
        secrets,
        None if args.local_dir is _PROFILE_CONFIG else args.local_dir,
        selected_profile_key,
    )
    if args.once_per_week:
        existing = verified_backup_for_week(
            output_dir,
            profile_key=selected_profile_key,
        )
        if existing is not None:
            print(f"Weekly backup already verified: {existing}")
            return 0
    storage = GoogleSheetsStorage.from_secrets(secrets)
    drive_settings = secrets.get("google_drive")
    drive_client = (
        GoogleDriveClient(load_oauth_config(all_secrets), drive_settings)
        if isinstance(drive_settings, Mapping)
        and isinstance(drive_settings.get("receipt_folder"), Mapping)
        else None
    )
    receipt_manifest = build_backup_receipt_manifest(
        selected_profile_key,
        secrets,
        storage,
        client=drive_client,
    )
    destination = write_versioned_backup(
        storage,
        output_dir,
        receipt_manifest,
        keep=args.keep,
        profile_key=selected_profile_key,
    )
    print(f"Verified backup created: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
