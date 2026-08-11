"""Export local app secrets and business profiles for Streamlit Cloud."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from tabula_rasa.business_profiles import load_business_profiles
from tabula_rasa.google_drive import (
    GoogleDriveConfigurationError,
    validate_drive_profile_settings,
)
from tabula_rasa.local_profile_store import (
    LOCAL_PROFILE_STORE_PATH,
    LocalProfileStoreError,
    load_local_profiles,
)


DEFAULT_SECRETS_PATH = PROJECT_ROOT / ".streamlit" / "secrets.toml"
EXPORT_DIRECTORY = PROJECT_ROOT / ".streamlit"
EXPORT_PREFIX = "tabula-rasa-streamlit-secrets-"
EXPORT_SUFFIX = ".toml"
PROFILE_CONFIG_KEYS = {
    "business_name",
    "spreadsheet_id",
    "gcp_service_account",
    "business_profiles",
}
LOCAL_ONLY_APP_KEYS = {"synology_recovery_defaults"}
HOSTED_PROFILE_FIELDS = (
    "name",
    "spreadsheet_id",
    "gcp_service_account",
)
BARE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class SecretsExportError(ValueError):
    """Raised when a safe Streamlit Secrets export cannot be produced."""


def project_hosted_profiles(
    profiles: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the explicit profile subset consumed by the hosted runtime."""
    try:
        configured = load_business_profiles({"business_profiles": profiles})
    except ValueError as exc:
        raise SecretsExportError("Business profiles failed validation.") from exc

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
                raise SecretsExportError(
                    f"Google Drive settings for profile '{profile.key}' are invalid."
                ) from exc
        projected[profile.key] = hosted
    return projected


def _toml_key(value: object) -> str:
    key = str(value)
    if BARE_KEY_PATTERN.fullmatch(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SecretsExportError("Secrets cannot contain non-finite numbers.")
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    raise SecretsExportError(
        f"Secrets contain an unsupported value type: {type(value).__name__}."
    )


def _emit_table(
    lines: list[str],
    path: tuple[str, ...],
    values: Mapping[str, Any],
) -> None:
    lines.append("[" + ".".join(_toml_key(part) for part in path) + "]")
    nested: list[tuple[str, Mapping[str, Any]]] = []
    for raw_key, value in values.items():
        key = str(raw_key)
        if isinstance(value, Mapping):
            nested.append((key, value))
        else:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    lines.append("")
    for key, child in nested:
        _emit_table(lines, (*path, key), child)


def build_streamlit_secrets_toml(
    app_secrets: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
) -> str:
    """Combine app-level secrets and canonical business profiles as TOML."""
    if not profiles:
        raise SecretsExportError("No business profiles are configured.")
    combined: dict[str, Any] = {
        str(key): value
        for key, value in app_secrets.items()
        if key not in PROFILE_CONFIG_KEYS | LOCAL_ONLY_APP_KEYS
    }
    combined["business_profiles"] = project_hosted_profiles(profiles)

    lines = [
        "# Generated for Streamlit Secrets. Contains credentials; do not commit.",
        "",
    ]
    nested: list[tuple[str, Mapping[str, Any]]] = []
    for key, value in combined.items():
        if isinstance(value, Mapping):
            nested.append((key, value))
        else:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
    lines.append("")
    for key, child in nested:
        _emit_table(lines, (key,), child)

    document = "\n".join(lines).rstrip() + "\n"
    try:
        parsed = tomllib.loads(document)
        load_business_profiles(parsed)
    except (tomllib.TOMLDecodeError, ValueError) as exc:
        raise SecretsExportError(
            "Generated Streamlit Secrets failed validation."
        ) from exc
    return document


def _load_app_secrets(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as secrets_file:
            return tomllib.load(secrets_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SecretsExportError(
            "The local secrets.toml file could not be read safely."
        ) from exc


def write_secure_export(document: str, output: Path | None = None) -> Path:
    """Write a new owner-only export file without overwriting an existing file."""
    encoded = document.encode("utf-8")
    if output is None:
        EXPORT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        if EXPORT_DIRECTORY.is_symlink():
            raise SecretsExportError(
                "Refusing to write secrets through a symbolic-link .streamlit directory."
            )
        descriptor, raw_path = tempfile.mkstemp(
            dir=EXPORT_DIRECTORY,
            prefix=EXPORT_PREFIX,
            suffix=EXPORT_SUFFIX,
        )
        destination = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as export_file:
                export_file.write(encoded)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
    else:
        destination = output.resolve()
        if destination == PROJECT_ROOT or PROJECT_ROOT in destination.parents:
            allowed_directory = EXPORT_DIRECTORY.resolve()
            allowed_name = (
                destination.name.startswith(EXPORT_PREFIX)
                and destination.name.endswith(EXPORT_SUFFIX)
            )
            if destination.parent != allowed_directory or not allowed_name:
                raise SecretsExportError(
                    "In-project exports are allowed only in .streamlit with a "
                    f"{EXPORT_PREFIX}*{EXPORT_SUFFIX} filename."
                )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("xb") as export_file:
                export_file.write(encoded)
        except FileExistsError as exc:
            raise SecretsExportError(
                f"Refusing to overwrite existing file: {destination}"
            ) from exc
    try:
        os.chmod(destination, 0o600)
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise SecretsExportError(
            "Could not restrict access to the generated secrets file."
        ) from exc
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--secrets",
        type=Path,
        default=DEFAULT_SECRETS_PATH,
        help="Local app-level secrets.toml file",
    )
    parser.add_argument(
        "--profiles",
        type=Path,
        default=LOCAL_PROFILE_STORE_PATH,
        help="Canonical business_profiles.json file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional new output path; existing files are never overwritten",
    )
    args = parser.parse_args()

    try:
        app_secrets = _load_app_secrets(args.secrets)
        profiles = load_local_profiles(args.profiles)
        document = build_streamlit_secrets_toml(app_secrets, profiles)
        destination = write_secure_export(document, args.output)
    except (LocalProfileStoreError, SecretsExportError) as error:
        raise SystemExit(str(error)) from error

    print(f"Streamlit Secrets export created: {destination}")
    print("Paste its complete contents into Streamlit App settings > Secrets.")
    print("Delete the generated file immediately after Streamlit accepts it.")


if __name__ == "__main__":
    main()
