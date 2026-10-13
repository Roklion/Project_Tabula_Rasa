"""Pure copy provenance shared by internal and commercial workflows."""

from collections.abc import Mapping
import re


def copied_transaction_description(transaction: Mapping[str, object]) -> str:
    """Build copy provenance while retaining the user's current memo."""
    source_id = str(transaction.get("id") or "").strip()
    description = str(transaction.get("description", "") or "").strip()
    provenance_prefix = re.compile(
        r"^Copy From\s+(?:[^\s]+|" + re.escape(source_id) + r")(?:\s*:\s+|\.\s+)"
        r"|^Copied from transaction\s+(?:[^\s]+|" + re.escape(source_id) + r")(?:\s*:\s+|\.\s+)"
    )
    provenance_prefix_only = re.compile(
        r"^(?:Copy From|Copied from transaction)\s+(?:[^\s]+|" + re.escape(source_id) + r")$"
    )
    provenance_suffix = re.compile(
        r"\.\s+(?:Copy From|Copied from transaction)\s+(?:[^\s]+|" + re.escape(source_id) + r")$"
    )
    while description:
        stripped = provenance_prefix.sub("", description, count=1).strip()
        if stripped != description:
            description = stripped
            continue
        stripped = provenance_prefix_only.sub("", description, count=1).strip()
        if stripped != description:
            description = stripped
            continue
        match = provenance_suffix.search(description)
        if match is None:
            break
        description = description[:match.start()].rstrip(" .:")
    provenance = f"Copy From {source_id}" if source_id else "Copy From"
    if not description:
        return provenance
    if not description.endswith("."):
        description += "."
    return f"{description} {provenance}"
