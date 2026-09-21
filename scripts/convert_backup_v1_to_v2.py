"""Compatibility import for the retired format-1 converter.

Use :mod:`scripts.migrate_legacy_backup` for the single supported migration
entry point. The function alias remains available to callers that imported
the old module, but now produces a v13 archive.
"""

from __future__ import annotations

from pathlib import Path

from scripts.migrate_legacy_backup import (
    default_output_path,
    migrate_backup_file,
    migrate_legacy_backup,
)


def convert_backup_v1_to_v2(
    backup: bytes,
    *,
    profile_key: str | None = None,
) -> bytes:
    """Deprecated alias; migrate the format-1 archive directly to v13."""
    return migrate_legacy_backup(backup, profile_key=profile_key)


def convert_backup_file(
    source: Path,
    output: Path | None = None,
    *,
    profile_key: str | None = None,
) -> Path:
    """Deprecated alias for :func:`migrate_backup_file`."""
    return migrate_backup_file(source, output, profile_key=profile_key)


__all__ = [
    "convert_backup_file",
    "convert_backup_v1_to_v2",
    "default_output_path",
]
