"""One-time local profile conversion for the OAuth-only release (no ledger writes)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tabula_rasa.local_profile_store import (  # noqa: E402
    STORE_VERSION,
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    _atomic_write,
    _validate_stored_profiles,
)


def convert_profile_document(document: object) -> dict:
    """Remove obsolete Sheets credentials while preserving grants and destinations."""
    if (
        not isinstance(document, dict)
        or document.get("version") != 1
        or set(document) != {"version", "business_profiles"}
        or not isinstance(document["business_profiles"], dict)
    ):
        raise LocalProfileStoreError("Expected a version 1 business profile document.")
    profiles = {}
    for key, settings in document["business_profiles"].items():
        if not isinstance(settings, dict):
            raise LocalProfileStoreError("Invalid business profile settings.")
        candidate = dict(settings)
        candidate.pop("gcp_service_account", None)
        profiles[key] = candidate
    return {
        "version": STORE_VERSION,
        "business_profiles": _validate_stored_profiles(profiles),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=LOCAL_PROFILE_STORE_PATH)
    args = parser.parse_args()
    if args.profiles.is_symlink():
        raise SystemExit("Refusing to convert a symbolic-link profile store.")
    try:
        converted = convert_profile_document(
            json.loads(args.profiles.read_text(encoding="utf-8"))
        )
        _atomic_write(args.profiles, (json.dumps(converted, indent=2) + "\n").encode())
    except (OSError, ValueError):
        raise SystemExit(
            "Profile conversion failed. The original file was not replaced."
        ) from None
    print(
        "OAuth-only profile format saved. Connect Google, select each ledger in Picker, and run readiness."
    )


if __name__ == "__main__":
    main()
