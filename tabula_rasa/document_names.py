"""Canonical receipt filenames shared by upload identity and storage adapters."""

import re

from tabula_rasa.receipt_manifest import ReceiptManifestError, validate_receipt_filename


def safe_receipt_filename(original_name: str) -> str:
    """Normalize an upload basename to the supported portable filename format."""
    basename = str(original_name or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._() -]+", "_", basename).strip(" .")
    cleaned = cleaned or "receipt"
    if len(cleaned) > 180:
        stem, dot, extension = cleaned.rpartition(".")
        cleaned = stem[:179 - len(extension)] + dot + extension if dot and len(extension) < 179 else cleaned[:180]
    try:
        return validate_receipt_filename(cleaned, "Receipt filename")
    except ReceiptManifestError:
        return validate_receipt_filename(f"_{cleaned}", "Receipt filename")
