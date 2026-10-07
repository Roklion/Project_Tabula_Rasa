"""Private no-clobber artifact delivery; private contents never enter errors."""

import os
from pathlib import Path
import tempfile

from tabula_rasa.application.entity_export import ExportError
from .format import canonical_json


def private_output_path(value):
    try:
        path = Path(value).resolve()
        readable = path.parent.is_dir()
        in_repository = any((parent / ".git").exists() for parent in (path.parent, *path.parent.parents))
        existing = path.exists()
    except (OSError, RuntimeError):
        path = None
    if path is None or not readable:
        raise ExportError("output_directory")
    if in_repository:
        raise ExportError("repository_output")
    if existing:
        raise ExportError("output_exists")
    return path


def write_artifact(path, artifact):
    """Publish a fully written file atomically, without replacing an existing file.

    POSIX uses owner-only mode; Windows inherits the private directory's ACL.
    A same-directory temporary file plus a hard link keeps partial files out of
    the final destination. Filesystems without hard links fail explicitly.
    """
    path = private_output_path(path)
    temporary = None
    failed = False
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".bookkeeping-",
                                         suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            if os.name != "nt":
                os.chmod(temporary, 0o600)
            stream.write(canonical_json(artifact) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    except OSError:
        failed = True
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                # Publication status belongs to os.link; cleanup is best effort.
                pass
    if failed:
        raise ExportError("output_write")


def read_artifact(path, *, entity_id):
    from .format import parse_artifact
    try:
        payload = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        payload = None
    if payload is None:
        raise ExportError("artifact_read")
    return parse_artifact(payload, entity_id=entity_id)
