"""Private source snapshots and versioned, reproducible migration plans."""

from dataclasses import dataclass, field
from hashlib import sha256
import json
from uuid import NAMESPACE_URL, uuid5

MANIFEST_VERSION = "1"
MAPPING_VERSION = "1"
SYNTHESIZED_TIMESTAMP = "1970-01-01T00:00:00Z"


class MigrationError(ValueError):
    """Only fixed diagnostics and worksheet/row coordinates belong in errors."""


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")).hexdigest()


def stable_id(*parts):
    return str(uuid5(NAMESPACE_URL, json.dumps(parts, ensure_ascii=False)))


@dataclass(frozen=True)
class Binding:
    profile_key: str
    workbook_key: str
    entity_id: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() or value != value.strip()
               for value in (self.profile_key, self.workbook_key, self.entity_id)):
            raise MigrationError("An explicit profile, workbook and target entity binding is required.")


@dataclass(frozen=True, repr=False)
class Snapshot:
    binding: Binding
    extracted_at: str
    content: str = field(repr=False)

    @property
    def tables(self):
        return json.loads(self.content)

    @property
    def sha256(self):
        return sha256(self.content.encode("utf-8")).hexdigest()

    def __repr__(self):
        return "Snapshot(format=13, private_content=True)"


@dataclass(frozen=True)
class IdMapping:
    source_record_kind: str
    source_id: str
    target_record_kind: str
    target_id: str
    mapping_reason: str = "preserved"
    source_updated_at: str | None = None


@dataclass(frozen=True, repr=False)
class Unit:
    key: str
    kind: str
    dependencies: tuple[str, ...]
    content: str = field(repr=False)

    @property
    def rows(self):
        return json.loads(self.content)

    @property
    def sha256(self):
        return digest({"kind": self.kind, "dependencies": self.dependencies, "rows": self.rows})

    def __repr__(self):
        return "Unit(private_content=True)"


@dataclass(frozen=True, repr=False)
class Plan:
    snapshot: Snapshot
    units: tuple[Unit, ...]
    mappings: tuple[IdMapping, ...]

    @property
    def run_id(self):
        binding = self.snapshot.binding
        return stable_id("tabula-migration", MANIFEST_VERSION, MAPPING_VERSION,
                         binding.profile_key, binding.workbook_key, binding.entity_id,
                         self.snapshot.sha256)

    def target_id(self, source_kind, source_id):
        for mapping in self.mappings:
            if (mapping.source_record_kind, mapping.source_id) == (source_kind, source_id):
                return mapping.target_id
        raise MigrationError("A required source identity is absent from the migration map.")

    def report(self, supported_kinds=()):
        """Safe operator report; never cutover evidence."""
        return {"manifest_version": MANIFEST_VERSION, "mapping_version": MAPPING_VERSION,
                "source_format": 13, "run_id": self.run_id,
                "source_snapshot_sha256": self.snapshot.sha256,
                "unit_counts": {kind: sum(unit.kind == kind for unit in self.units)
                                for kind in sorted({unit.kind for unit in self.units})},
                "missing_loaders": sorted({unit.kind for unit in self.units} - set(supported_kinds)),
                "acceptance": "provisional_framework_only", "cutover_authorized": False}

    def __repr__(self):
        return f"Plan(units={len(self.units)}, private_content=True)"
