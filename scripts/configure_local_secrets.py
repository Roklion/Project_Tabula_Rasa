"""Convert a Google service-account JSON key to local Streamlit secrets."""

from __future__ import annotations

import argparse
import json
import os
import tomllib
from pathlib import Path


SERVICE_ACCOUNT_FIELDS = (
    "type",
    "project_id",
    "private_key_id",
    "private_key",
    "client_email",
    "client_id",
    "auth_uri",
    "token_uri",
    "auth_provider_x509_cert_url",
    "client_x509_cert_url",
    "universe_domain",
)


def toml_string(value: str) -> str:
    # JSON strings use the same escaping needed by TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def configure_secrets(
    key_path: Path,
    destination: Path,
    spreadsheet_id: str,
    expected_project: str,
    expected_email: str,
) -> None:
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite existing secrets: {destination}")

    with key_path.open("r", encoding="utf-8") as key_file:
        credentials = json.load(key_file)

    required = set(SERVICE_ACCOUNT_FIELDS[:10])
    missing = sorted(required - credentials.keys())
    if missing:
        raise ValueError("Credential is missing required fields: " + ", ".join(missing))
    if credentials["type"] != "service_account":
        raise ValueError("Credential type must be service_account")
    if credentials["project_id"] != expected_project:
        raise ValueError("Credential project_id does not match the expected project")
    if credentials["client_email"] != expected_email:
        raise ValueError("Credential client_email does not match the expected service account")

    lines = [
        "# Generated locally. Never commit this file.",
        f"spreadsheet_id = {toml_string(spreadsheet_id)}",
        "",
        "[gcp_service_account]",
    ]
    for field in SERVICE_ACCOUNT_FIELDS:
        if field in credentials:
            lines.append(f"{field} = {toml_string(str(credentials[field]))}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(destination, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as secrets_file:
        secrets_file.write("\n".join(lines) + "\n")

    # Parse the generated file without displaying its contents.
    with destination.open("rb") as secrets_file:
        parsed = tomllib.load(secrets_file)
    if parsed.get("spreadsheet_id") != spreadsheet_id:
        raise RuntimeError("Generated spreadsheet_id failed validation")
    if parsed.get("gcp_service_account", {}).get("client_email") != expected_email:
        raise RuntimeError("Generated service-account section failed validation")

    print(f"Created and validated local Streamlit secrets: {destination}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("key_path", type=Path)
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--expected-project", required=True)
    parser.add_argument("--expected-email", required=True)
    parser.add_argument(
        "--destination", type=Path, default=Path(".streamlit/secrets.toml")
    )
    args = parser.parse_args()
    configure_secrets(
        args.key_path,
        args.destination,
        args.spreadsheet_id,
        args.expected_project,
        args.expected_email,
    )


if __name__ == "__main__":
    main()
