# Least-privilege support operations

Issue [#341](https://github.com/Roklion/Project_Tabula_Rasa/issues/341) implements
the minimal internal support slice of [EPIC #223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
Billing/subscriptions remain #224. This delivers repository tooling; production
operator provisioning, hosted security evidence and #342 handoff still require
explicit human approval. It does not activate writers or establish #298 release
acceptance.

## Authority and supported use cases

Support staff use a named-user session and the restricted HTTP CLI. They need
no SQL, provider credentials, secret-store access or tenant impersonation.
The server revalidates the session, environment epoch, active identity and an
unexpired, unrevoked grant for the exact organization on every operation.
Organization/entity binding comes from PostgreSQL, independently of the selected
browser business. There is no global organization search or tenant enumeration.

A grant provides read-only metadata diagnostics and audit inspection. Its
separate `can_admin` flag permits only the preview/confirm access-containment
commands below. No tenant role, including Owner/Admin, acquires either grant.
Existing Owner/Admin member administration remains owned by the workspace
service; Editor/Reader have no extra backup, restore, credential, local profile
or audit authority. Existing recovery commands still require their independent
platform capabilities and one-execution approvals. Support grants confer none
of those capabilities. Legacy loopback-only Account settings stays separate.

| Use case | Returned metadata / effect |
| --- | --- |
| Organization/entity lookup | Exact supplied IDs, organization state; no global directory or customer/billing details |
| Account lookup | Up to 100 IDs, types, classifications and active flags; no names, balances or postings |
| Membership/session diagnosis | Up to 100 member IDs, roles, member/user state and active session counts for this organization/environment |
| Failed jobs | Latest 100 job IDs, registered type, state, attempts and fixed failure code; no job payload or idempotency key |
| Migration diagnosis | Latest 100 run IDs and states; no source paths, manifest or ledger contents |
| Document connection health | Persisted provider/status only; no network probe, grant, folder, secret reference or receipt locator |
| Export status | `synchronous_not_retained`: financial CSV exports are synchronous; there is no durable export job/status history to fabricate |
| Audit inspection | At most 100 metadata events per request with explicit continuation; no before/after values, row digests or document bytes |
| Revoke sessions | Revoke the target member's sessions currently selected into this organization and environment; other businesses/environments survive |
| Suspend member | Inactivate only that organization membership through the existing control plane; active-owner protections still apply |
| Suspend organization | Suspend the exact organization; no automatic reactivation or user-global disable |

Revoking sessions alone does not remove membership: another surviving session
or a new login can still access authorized businesses. Use membership suspension
for lasting organization access containment, or the separately approved identity
incident procedure for a compromised global identity. No support command can
restore, migrate, reset books, change credentials, fetch ledger rows or download
receipts. Administrative plans bind exact scope, reason, operation, target and
current relevant state. A changed membership or session set invalidates a stale
plan. Confirmed session rows stay locked until commit, and the update targets
only their immutable cache IDs. Sessions arriving or switching into the business
after that boundary remain outside the confirmed set; inspect and preview again
if further containment is needed. Preview is default; applying requires the
returned plan hash.

## CLI and bounded audit export

From a development environment with the API dependencies installed:

```powershell
python -m scripts.support_diagnostics diagnostics --origin https://approved.example.test --organization APPROVED_ORG --entity APPROVED_ENTITY --reason incident
python -m scripts.support_diagnostics audit --origin https://approved.example.test --organization APPROVED_ORG --entity APPROVED_ENTITY --reason audit_review --since 2026-10-01T00:00:00Z --until 2026-11-01T00:00:00Z --limit 50
python -m scripts.support_diagnostics suspend_member --origin https://approved.example.test --organization APPROVED_ORG --entity APPROVED_ENTITY --reason access_request --target-user APPROVED_USER
```

Use only the operator's own authenticated session/CSRF credentials, supplied via
hidden prompts. Never put cookies in arguments, tickets, shell history or logs.
The CLI accepts HTTPS origins (HTTP only for loopback development), refuses
redirects and prints a generic failure rather than proxy/provider response text.
It never asks for database or secret-store credentials.

Repeat the exact administrative preview command with
`--confirm-plan RETURNED_PLAN_SHA256` only after reviewing the exact target and
approved containment action. A lost response is uncertain: inspect metadata and
audit history before deciding whether to preview again.

Audit filters include `--since` (inclusive), `--until` (exclusive), entity via
`--entity`, `--actor-id`, `--source`, `--action` (create/update/delete),
`--target-type`, `--target-id`, `--batch-id` and `--operation-id`.
Dates require an explicit timezone. Use returned `next_sequence` with
`--after-sequence` and keep the first response's `through_sequence` as
`--through-sequence`; this upper bound stops the traversal chasing its own
inspection events. Concurrent transactions can commit out of sequence; these
pages are diagnostic inspection, not a complete transactional snapshot export.
Each invocation exports at most 100 events and never
automatically follows pages. A full final page may require one more query.
Redirect successful JSON to an approved private incident evidence location only.
Repeated authorized requests remain possible; the page bound is not a claim
of a lifetime export quota. Metadata diagnostics return bounded samples, not a
complete inventory for organizations with more than 100 records.

POST routes are `/api/v1/support/{organization_id}/{business_id}/diagnostics`,
`/audit` and `/administration`. They use the existing named cookie, Origin and
CSRF checks and typed, redacted response contracts. Bodies require an allowlisted
reason code: incident, access_request, job_failure, migration_failure,
connection_failure or audit_review. No arbitrary free text is stored.

Every successful diagnostic/audit query, administrative preview and applied action
writes an immutable `support_actions` record and a same-transaction #335 event.
A failed audit insert rolls back the administrative effect. Applied actions,
targets, reasons and approved provisioning details remain in immutable records.
Audit responses label support operation/reason but omit financial summaries.
Denied requests use #332's safe telemetry; no raw tenant IDs, submitted reason
text, credentials or receipt contents enter logs. Deployment-wide telemetry
activation and recipient approval retain #332 ownership. Audit recovery must
include support actions and grants in complete PostgreSQL recovery; ordinary
v1 financial exports deliberately omit them. History from before activation
retains #335's truthful unavailable boundary.

## Manual provisioning and revocation checkpoint

Only the production database administrator runs
`python -m scripts.provision_support_operator`, using separately protected
operator database access and the exact approved database binding. Support staff
must never receive that connection. Migration `0015_support_controls` creates
no grants and changes no tenant role or bookkeeping field.

1. Obtain human approval for the environment, organization/entity, existing named
   operator user ID, read-only or administrative authority, explicit expiry and
   sanitized approval reference. Confirm the administrator's own named user ID.
   Arrange the alternate operator and private incident record before live changes.
2. Follow [deployment/rollback](COMMERCIAL_DEPLOYMENT.md), apply the normal
   forward migration in the approved maintenance window and deploy compatible
   API code. The runtime needs SELECT on support_grants and support_actions,
   INSERT on support_actions and its existing scoped identity/session DML and audit
   SELECT permissions. Grant no support-grant writes, audit-event writes or table
   ownership to the runtime; its support INSERT policy requires the trusted
   entity/operator context. Provisioning uses the separate database administrator.
   Do not treat this documentation as provisioning authorization.
3. Preview with `--administrator ADMIN_USER --user OPERATOR_USER --organization
   APPROVED_ORG --entity APPROVED_ENTITY --environment production
   --approval-reference APPROVED_REFERENCE --expires-at APPROVED_ISO_INSTANT`.
   These are arguments to `python -m scripts.provision_support_operator`.
   Read-only is default; add `--admin` only for an approved containment operator.
   No identity, role, session, provider secret or tenant membership is created.
4. Review the exact binding/approval and repeat with
   `--confirm-plan RETURNED_PLAN_SHA256`. Provisioning and its immutable event
   commit together. Preserve the private approval separately; the reference
   contains only letters, digits, underscores or hyphens, never private text.
5. Verify the operator can inspect the approved business and cannot inspect a
   second synthetic organization or access ledger/document content. Verify
   revocation, denial telemetry and immutable event visibility on the deployed
   revision. Use synthetic data for hosted validation.
6. For rollback or lost authority, preview the same administrator command with
   `--revoke` and the exact user/org/environment/approval reference; review and
   confirm its plan. This works for a disabled operator too. Existing sessions
   immediately lose support access at the next request; retained tenant
   membership is independent. Use expiry as a further bound, not as a substitute
   for emergency revocation.

Forward-only rollback keeps history and schema: revoke grants, stop support
access and select an approved compatible release. Do not drop support/audit
tables or reverse bookkeeping. Use [incident response](INCIDENT_RESPONSE.md),
[secret/session containment](SECRETS_OPERATIONS.md), and
[recovery verification](POSTGRESQL_RECOVERY.md) for wider incidents. #342 consumes
sanitized current-release evidence, named primary/alternate operators, observed
limitations and unresolved hosted checks; #224/#298 retain release authority.

## Reuse and validation

The implementation extends #311/#313's existing users, sessions, memberships
and last-owner guards, #333's job diagnostic contract, #335's private
`AuditReader` and atomic append-only event triggers, and #332 HTTP telemetry.
New ownership is limited to expiring scoped support grants, bounded redacted
DTOs, confirmation plans and immutable support-action records. It introduces
no second identity store, role system, accounting engine, scheduler, document
provider or recovery state machine.

Run `tests/postgres/test_support_controls.py` against disposable PostgreSQL,
plus affected identity/authorization/audit/migration/export/recovery checks,
`tests/test_support_cli.py`, Ruff and generated API contract/type checks.
Tests cover two tenants, revoked/expired/wrong-environment authority, stale
plans, scoped session revocation, last-owner refusal, unsafe direct actions,
redacted output/logs, grant provisioning and atomic audit failure. Local
synthetic evidence does not establish hosted production provisioning or
#224/#298 release acceptance.

### Implementation evidence and operational handoff

Reviewed implementation, local diagnostics and current-candidate CI/reviewer
results are recorded in [#341](https://github.com/Roklion/Project_Tabula_Rasa/issues/341)
and [PR #396](https://github.com/Roklion/Project_Tabula_Rasa/pull/396).
[#342](https://github.com/Roklion/Project_Tabula_Rasa/issues/342) owns actual
operator provisioning, deployed denial/telemetry observations and primary/alternate
operator execution. [#332](https://github.com/Roklion/Project_Tabula_Rasa/issues/332)
retains hosted telemetry activation. Code/test delivery does not establish that
operational handoff or #224/#298 release acceptance.
