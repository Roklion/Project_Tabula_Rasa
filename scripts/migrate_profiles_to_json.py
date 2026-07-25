"""Migrate legacy business profiles from secrets.toml to the canonical JSON file."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from business_profiles import load_business_profiles
from local_profile_store import LOCAL_PROFILE_STORE_PATH, save_local_profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets",
        type=Path,
        default=PROJECT_ROOT / ".streamlit" / "secrets.toml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=LOCAL_PROFILE_STORE_PATH,
    )
    args = parser.parse_args()

    if args.output.exists():
        raise SystemExit(
            f"Refusing to overwrite existing profile file: {args.output}"
        )
    with args.secrets.open("rb") as secrets_file:
        legacy_secrets = tomllib.load(secrets_file)
    profiles = load_business_profiles(legacy_secrets)
    for profile in profiles:
        settings = dict(profile.secrets)
        settings["name"] = profile.name
        save_local_profile(
            profile.key,
            settings,
            path=args.output,
        )
    print(f"Migrated {len(profiles)} profile(s) to {args.output}")
    print(
        "Verify the app, then remove business_profiles, spreadsheet_id, "
        "business_name, and gcp_service_account entries from secrets.toml."
    )


if __name__ == "__main__":
    main()
