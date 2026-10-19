"""Bounded operator contracts. No tenant role grants platform support authority."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

REASONS = frozenset({'incident', 'access_request', 'job_failure', 'migration_failure', 'connection_failure', 'audit_review'})


@dataclass(frozen=True)
class AccountMetadata:
    id: str
    type: str
    classification: str
    active: bool


@dataclass(frozen=True)
class MemberStatus:
    user_id: str
    role: str
    state: str
    user_state: str
    active_sessions: int


@dataclass(frozen=True)
class ConnectionHealth:
    provider: str
    status: str


@dataclass(frozen=True)
class MigrationStatus:
    id: str
    status: str


@dataclass(frozen=True)
class JobStatus:
    id: str
    job_type: str
    state: str
    attempts: int
    failure_code: str | None


@dataclass(frozen=True)
class Diagnostics:
    organization_id: str
    entity_id: str
    organization_state: str
    accounts: tuple[AccountMetadata, ...]
    members: tuple[MemberStatus, ...]
    connections: tuple[ConnectionHealth, ...]
    migrations: tuple[MigrationStatus, ...]
    jobs: tuple[JobStatus, ...]
    export_status: Literal['synchronous_not_retained'] = 'synchronous_not_retained'


@dataclass(frozen=True)
class AuditSummary:
    sequence: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    source: str
    action: str
    target_type: str
    target_key: dict[str, str | int]
    operation_id: str
    batch_id: str | None
    support_operation: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class AuditPage:
    events: tuple[AuditSummary, ...]
    next_sequence: int | None
    through_sequence: int
    export_limit: int = 100


@dataclass(frozen=True)
class AdministrativeResult:
    applied: bool
    plan_sha256: str
