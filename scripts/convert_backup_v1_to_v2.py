"""Compatibility import for the retired format-1 converter.

Use :mod:`scripts.migrate_legacy_backup` for the single supported migration
entry point. The function alias remains available to callers that imported
the old module, but now produces a v10 archive.
"""

from __future__ import annotations

from scripts.migrate_legacy_backup import (
    default_output_path,
    migrate_backup_file,
    migrate_legacy_backup,
)


def convert_backup_v1_to_v2(backup: bytes) -> bytes:
    """Deprecated alias; migrate the format-1 archive directly to v10."""
    return migrate_legacy_backup(backup)


def convert_backup_file(source, output=None):
    """Deprecated alias for :func:`migrate_backup_file`."""
    return migrate_backup_file(source, output)


__all__ = [
    "convert_backup_file",
    "convert_backup_v1_to_v2",
    "default_output_path",
]
