# Identity and tenant security acceptance (#320)

This repeatable synthetic gate implements the integrated verification slice of
[#320](https://github.com/Roklion/Project_Tabula_Rasa/issues/320), under
[EPIC #222](https://github.com/Roklion/Project_Tabula_Rasa/issues/222) and
[initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
It verifies React/FastAPI/PostgreSQL identity and tenant boundaries. It does not
admit unrelated beta users, execute owner migration, provision providers or
approve recovery. #224 retains the release decision; #223/#298 retain operations
and recovery acceptance.

## Repeatable local and CI gate

Use Python 3.12, `requirements-dev.txt`, Node 24 and `npm --prefix web ci`.
Follow [PostgreSQL setup](POSTGRESQL.md) for a **disposable local test
administrator** URL in `TABULA_RASA_TEST_DATABASE_URL`. Never use the application
database URL or a retained provider database. Each native test creates, migrates
and drops its own randomly named database; there is no SQLite/mock fallback.

```powershell
python -m pytest tests/http tests/test_oidc.py tests/test_local_profile_admin.py tests/tooling/test_ci_workflow.py
python -m pytest tests/postgres/test_security_acceptance.py tests/postgres/test_authorization_http.py tests/postgres/test_identity.py tests/postgres/test_identity_http.py tests/postgres/test_workspaces.py tests/postgres/test_tenant_connections.py tests/postgres/test_connection_provisioning.py tests/postgres/test_legacy_claims.py
npm --prefix web run build
python -m playwright install chromium
$env:TABULA_RASA_REQUIRE_BROWSER_TESTS = '1'
python -m pytest tests/postgres/test_identity_browser.py tests/postgres/test_workspace_browser.py
```

Run repository Ruff and `git diff --check`; regenerate OpenAPI and the TypeScript
client and require no contract drift. The pinned Starlette transport retains
compatibility with the declared HTTPX TestClient dependency after a fresh install.

Repository CI's unfiltered Python job discovers the route audit and native
matrix. Its browser job explicitly runs `test_identity_browser.py` and
`test_workspace_browser.py` after compiling the SPA with PostgreSQL and
`TABULA_RASA_REQUIRE_BROWSER_TESTS=1`; missing builds/databases fail that gate.
[Development](DEVELOPMENT.md#authoritative-ci-and-required-check) owns the
current-revision **Full test suite** requirement. Affected local checks do not
replace the hosted merge gate.

## Coverage and limits

Tests reuse `NamedIdentity`, the session/control-plane/workspace repositories,
action registry, application services, receipt workflow and `ScopeBoundary`.
No parallel identity/authorization system is introduced. The signed fake-OIDC
adapter replaces only the external provider navigation and transport. App
login/callback, opaque cookies, database sessions, HTTP, ledger persistence and
document metadata remain real. Entity-scoped fake byte stores prove application
isolation, not managed-provider durability or grant configuration.

| Threat cases from [the identity contract](COMMERCIAL_IDENTITY.md#threat-model-and-required-acceptance-cases) | Executable evidence |
| --- | --- |
| T01/T05/T10: anonymous, tampered, expired/revoked/disabled credentials and authorization outage | `test_security_acceptance.py` exercises every centrally session-protected operation, including identity/bootstrap/membership, plus docs/OpenAPI, and asserts denial before service binding. `test_authorization_http.py` also covers suspended organizations, inactive entities and removed membership. |
| T02/T07/T09: signed-provider validation, callback replay/fixation and failure | `test_oidc.py`, `test_identity.py`, `test_identity_http.py`; the acceptance matrix also verifies failed provider exchange creates no session and cannot be replayed. |
| T03/T04/T06: forged scope/roles, every API family, document keys | The acceptance matrix applies an independently stated five-role policy to every entity route; all deny a foreign entity. `test_authorization_http.py` covers route/body/header/cookie forgery, permitted/stale writes and colliding document IDs. `test_tenant_connections.py` and `test_connection_provisioning.py` verify qualified grants, refusal before secret loading and revocation. |
| T05/T11/T12/T13: overlapping memberships, concurrent changes, invites/last owner and bootstrap | The matrix checks two sessions through selection, simultaneous committed changes and user-wide revocation, HTTP invitation replay, escalation and foreign bootstrap. `test_workspaces.py` covers concurrent last-owner protection, expired/revoked/wrong-recipient/stale-auth invitations and atomic failure/retry/bootstrap with two users. |
| T08: Origin/CSRF | The matrix rejects missing/null/foreign Origin and missing/wrong CSRF on every centrally session-protected mutation before composition. Logout's separate outage-clearing/CSRF contract remains in `test_identity_http.py`. |
| T14: private browser state and login as another user | `test_identity_browser.py` signs in, switches workspace/business, creates a transaction, uploads/links/downloads a receipt, signs out and signs into the same browser context as another user at desktop/mobile widths. Foreign metadata/bytes deny; ledger, history and persistent storage retain no first-user content. Workspace browser tests cover demotion/removal and cross-tab logout; React ContextBoundary/ScopeBoundary tests cover delayed responses, drafts and cache cancellation. |
| T15/T18: stage configuration and rotation/recovery revocation | Production requires explicit `named_user`; named mode rejects alpha credentials/context. The inventory tests reject environment mistakes and missing provider settings. Existing identity/native HTTP tests cover configuration rotation and user/session revocation. Hosted restore/recovery evidence remains downstream below. |
| T16: private route or transport drift | `test_security_inventory.py` compares the complete schema with policies and rejects missing dependencies, non-API private paths and arbitrary mounted apps. Runtime authorization also denies unregistered FastAPI handlers outside `/api`. Existing authorization tests cover duplicate/method/scope/prefix defects. Authorized stale-write/domain checks remain independent. |
| T17/T19: backup/recovery/operator separation and local admin | The explicit privilege matrix tests Owner versus Admin/Accountant/Editor/Read-only, independent platform execution and recovery approval. Native tests verify unavailable remote backup/restore/migration/profile-admin paths for all roles. `test_local_profile_admin.py` and `test_legacy_claims.py` retain loopback/operator/password restrictions and approved two-profile mapping. |

Canonical roles are `owner`, `admin`, `accountant`, `editor` and `read_only`;
“bookkeeper”/“viewer” mean Editor/Read-only. Named membership never becomes a
platform operator. The privilege test supplies independent server capabilities
to the policy only; it does not invent an operator login or public recovery
endpoint. Current CSV downloads retain their supported `read` policy; complete
bookkeeping export/backup and destructive recovery retain distinct capabilities.

An already authorized in-flight request may finish; revocation governs requests
after the change commits. Tests do not claim a transaction spanning provider,
control plane, ledger and browser, or protection from an administrator modifying
the running application. All data is synthetic.

## Sanitized evidence and unresolved gap register

Local evidence identifies the tested Git revision/diff, PostgreSQL version,
commands and pass/fail totals. Hosted evidence also identifies release, schema
and current-head CI run. Retain synthetic test names, safe statuses, request/check
IDs only. Never attach cookies, invite credentials, emails, provider responses,
SQL, secrets or customer bookkeeping/downloads. Native tests assert no-store
error envelopes and correlated, redacted `identity_denied`/`authorization_denied`
signals for revoked/forbidden requests. These hooks do not complete #332.

Implementation evidence, 2026-10-15: the clean `codex/issue-320-security` worktree
is based on `d5530d9` from `origin/main`. The implementation commit containing
this guide records the tested diff. Python 3.12.10 and disposable PostgreSQL 18.4
were used locally; Repository CI retains its PostgreSQL 18.6 service.

| Affected validation | Result |
| --- | --- |
| HTTP, OIDC, retained local administration and CI-policy tests (first command above) | 563 passed |
| Native PostgreSQL acceptance and lifecycle tests (second command above) | 80 passed |
| Compiled named-identity/workspace browser tests, Chromium at 1440/390 widths | 6 passed |
| Frontend Vitest | 92 passed across 22 files |
| Ruff, ESLint, TypeScript/Vite build, dependency compatibility, generated contract drift and whitespace checks | Passed |

No full local suite, live-provider acceptance or current-head hosted CI result
is claimed. The HTTP test transport emits a deprecation notice for HTTPX; it
passes with the declared dependencies. Future transport migration can be handled
separately from tenant authorization.

The first hosted run (`38843378193`) passed Python/PostgreSQL, Windows and all
160 browser E2E cases, then exhausted the combined browser job's 20-minute
budget during the native browser suite. The job now has a bounded 30-minute
budget for setup, E2E, image inspection and native browser acceptance. Every
existing case and the required aggregate gate remain enabled; the updated head
requires a fresh passing run.

| Unresolved acceptance | Exact downstream owner / required evidence |
| --- | --- |
| Guided first-ledger onboarding absent from this base | **#317 / PR #372** (`codex/issue-317-onboarding`, inspected at `4e290bb`): after integration run its onboarding success/failure/retry/resume tests plus this matrix on the combined head. Preserve its migration/return-route and scoped resume contract. This branch does not copy its UI/migrations or declare it merged. |
| Actual ZITADEL MFA, recovery mail/factors, outage, hosted login/logout/switch/revoke and named-mode rollback | **#321**, using [the operator-authorized provider setup](COMMERCIAL_IDENTITY.md). Live credentials/accounts are not required or authorized by these tests. |
| Actor/action security events, retention/sink/alerts and hosted correlation | **#332** under **#223**: extend the safe hooks, then verify delivered telemetry with synthetic denied/revoked requests. Local request/event redaction is covered; operational completeness remains open. |
| Managed document grant/byte durability and restore evidence | **#337/#338** under **#223**: verify the selected adapter, qualified grants, byte recovery and restoration. Fake-byte success is not this evidence. |
| Future support/recovery adapters and restored-session invalidation | **#341** owns privileged support adapters; **#223/#340** own recovery/incident procedures, including invalidating restored sessions before ingress. **#298/#303** retain commercial recovery/owner execution approvals. Extend absence/policy checks when operations become exposed. |
| External-beta and paid activation | **#224/#298** consume combined #320/#321 evidence plus #223 recovery/operations and legal/privacy gates. Parent #222 and initiative #124 remain open; code/test success alone is not admission approval. |

Do not close comprehensive external acceptance until applicable gaps have
evidence on the combined revision. Verification scaffolding and local vertical
slices can advance independently of those release gates.
