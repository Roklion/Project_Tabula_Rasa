"""Create, validate, and retain versioned Google Sheets ledger backups."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from storage import GoogleSheetsStorage
from business_profiles import load_business_profiles, select_profile_secrets


BACKUP_NAME = re.compile(r"^tabula-rosa-backup-\d{8}T\d{6}Z\.zip$")


def verified_backup_for_week(
    output_dir: Path, *, local_date: date | None = None
) -> Path | None:
    """Find a valid backup whose UTC filename falls in the requested local week."""
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
            GoogleSheetsStorage.validate_backup_zip(path.read_bytes())
        except (OSError, RuntimeError):
            continue
        return path
    return None


def resolve_backup_output_dir(
    profile_secrets: Mapping[str, Any],
    override: Path | None,
) -> Path:
    """Resolve an explicit override, profile path, or legacy local default."""
    if override is not None:
        return override
    configured = str(profile_secrets.get("backup_folder_path", "")).strip()
    return Path(configured) if configured else PROJECT_ROOT / "backups"


def write_versioned_backup(
    storage: GoogleSheetsStorage, output_dir: Path, *, keep: int = 30
) -> Path:
    """Write one verified backup and retain the newest requested generations."""
    if keep < 2:
        raise ValueError("keep must retain at least two backup generations")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    backup = storage.export_backup_zip()
    manifest = storage.validate_backup_zip(backup)
    timestamp = str(manifest["backup_time"]).replace("-", "").replace(":", "")
    timestamp = timestamp.replace("+0000", "Z")
    destination = output_dir / f"tabula-rosa-backup-{timestamp}.zip"
    with destination.open("xb") as backup_file:
        backup_file.write(backup)

    generations = sorted(
        (
            path
            for path in output_dir.iterdir()
            if path.is_file() and BACKUP_NAME.fullmatch(path.name)
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for expired in generations[keep:]:
        expired.unlink()
    return destination


def main() -> None:
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
        "--output-dir",
        type=Path,
        help=(
            "Override the profile's backup_folder_path; defaults to the profile "
            "setting or the project backups directory for legacy profiles"
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
    parser.add_argument("--profile", help="Business profile key to back up")
    args = parser.parse_args()

    with args.secrets.open("rb") as secrets_file:
        all_secrets = tomllib.load(secrets_file)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    secrets = select_profile_secrets(all_secrets, args.profile)
    output_dir = resolve_backup_output_dir(secrets, args.output_dir)

    if args.once_per_week:
        existing = verified_backup_for_week(output_dir)
        if existing is not None:
            print(f"Weekly backup already verified: {existing}")
            return

    storage = GoogleSheetsStorage.from_secrets(secrets)
    destination = write_versioned_backup(storage, output_dir, keep=args.keep)
    print(f"Verified backup created: {destination}")


if __name__ == "__main__":
    main()
