"""Backfill SHA-256 and stable identities for one profile's legacy receipts."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import load_business_profiles, select_profile_secrets
from tabula_rasa.google_drive import GoogleDriveClient, load_oauth_config
from tabula_rasa.local_profile_store import load_business_profile_document
from tabula_rasa.receipt_backfill import backfill_profile_receipts
from tabula_rasa.storage import GoogleSheetsStorage


def _profile_drive_settings(profile_secrets: Mapping[str, Any]) -> tuple[Mapping[str, Any], str]:
    drive_settings = profile_secrets.get("google_drive")
    if not isinstance(drive_settings, Mapping):
        raise ValueError("Google Drive is not connected for this business profile.")
    receipt_folder = drive_settings.get("receipt_folder")
    if not isinstance(receipt_folder, Mapping):
        raise ValueError("No Google Drive receipt folder is selected for this profile.")
    return drive_settings, str(receipt_folder.get("id") or "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets",
        type=Path,
        default=PROJECT_ROOT / ".streamlit" / "secrets.toml",
    )
    parser.add_argument("--profile", help="Business profile key to backfill")
    args = parser.parse_args()

    all_secrets = load_business_profile_document(args.secrets)
    profiles = load_business_profiles(all_secrets)
    if len(profiles) > 1 and not args.profile:
        raise SystemExit("Multiple profiles are configured; pass --profile PROFILE_KEY")
    profile_key = args.profile or profiles[0].key
    profile_secrets = select_profile_secrets(all_secrets, profile_key)
    drive_settings, folder_id = _profile_drive_settings(profile_secrets)
    storage = GoogleSheetsStorage.from_secrets(profile_secrets)
    drive = GoogleDriveClient(load_oauth_config(all_secrets), drive_settings)
    report = backfill_profile_receipts(
        storage,
        drive,
        profile_key=profile_key,
        folder_id=folder_id,
    )
    print(
        "Receipt checksum backfill: "
        f"examined={report['examined']}, "
        f"drive_backfilled={report['drive_backfilled']}, "
        f"references_updated={report['references_updated']}, "
        f"errors={len(report['errors'])}"
    )
    for error in report["errors"]:
        print(f"Skipped {error['file_id']}: {error['error']}")
    if report["errors"]:
        raise SystemExit("Some receipts could not be backfilled.")


if __name__ == "__main__":
    main()
