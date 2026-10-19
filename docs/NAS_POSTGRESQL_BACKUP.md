# NAS PostgreSQL backup operations (#294)

This is the NAS logical-backup runbook under [EPIC #223](https://github.com/Roklion/Project_Tabula_Rasa/issues/223)
and [initiative #124](https://github.com/Roklion/Project_Tabula_Rasa/issues/124).
The standalone runner uses the selected database's direct TLS connection and
requires neither Windows, the application nor a paid provider scheduler.
The runner, image and synthetic drill are implementation artifacts. They do not
establish a deployed NAS task, protected storage, actual provider usage or an
accepted recovery drill. Keep #294 open until the operator checklist below is
completed. The [managed recovery contract](POSTGRESQL_RECOVERY.md) remains
authoritative for #259's separate snapshot/PITR evidence and #298's commercial
recovery agreement, handoff and activation. #342 consumes operational evidence;
#224/#298 retain release acceptance. #299/#303 owner use remains independent.

## Selected host and compatibility checkpoint

The operator identified **Synology DS220j, DSM 7.4.1-90080**. Its Realtek RTD1296
is 64-bit ARM with 512 MB RAM ([hardware specification](https://global.download.synology.com/download/Document/Hardware/ProductSpec/DiskStation/20-year/DS220j/enu/Product_Spec_DS220j_enu.pdf)).
Synology's [Container Manager release notes](https://www.synology.com/en-us/releaseNote/ContainerManager?model=DS120j&os=DSM&version=7_x_series)
explicitly include ARMv8 DS220j/DS120j support. This establishes a documented
installation route, not execution proof on this device. Confirm Package Center
offers a supported Container Manager version for this exact model/DSM. Record
`uname -m`, package version, installed image digest, available memory/disk and
the commands' sanitized results privately. Do not install an unsupported package
or reuse DSM's internal PostgreSQL binaries. If unavailable or resource-limited,
record the concrete blocker and obtain an operator decision on an alternative.

The client-only image in `deploy/nas/Dockerfile` uses PostgreSQL 18.6, Python,
the distribution's `python3-psycopg` (using system libpq), age and timezone/CA data.
The pinned upstream manifest supports ARM64. The
runner also works with a separately maintained Python 3.9+ installation and
matching client tools and Psycopg 3, but installing a new native toolchain is not automatic.
Python compatibility here is separate from the application's Python 3.12 dev
environment. Do not install application dependencies on the NAS. Confirm all
three PostgreSQL clients match the actual server major version; the runner
refuses mismatches. Rebuild the reviewed image for a server-major change.

From a clean checkout, build on the NAS, or build ARM64 on an authorized build
host and import the image. No database server is started by this image's
entrypoint. Its dedicated Docker ignore file sends only the runner and private metadata helper to the
builder; never put credentials or backups in a build context.

```sh
docker build --platform linux/arm64 -f deploy/nas/Dockerfile -t tabula-nas-backup:294 .
```

Retain the built image ID/digest and use that immutable ID in the task command.
The apt packages receive current distribution security updates at build time;
retain/review the resulting image, rather than treating a tag as immutable.

## Protected configuration and inventory

Before enabling any recurring task, record the authorized primary/alternate
operator, exact production project/branch/direct endpoint and every intended
database, protected NAS destination, encrypted-share mount procedure and
recovery-key custodians in private operator records. Each invocation captures
**one database**. An archive containing multiple entities is a restricted
operator artifact, never an ordinary tenant/profile download.

1. Create a dedicated encrypted DSM shared folder with sufficient capacity,
   restricted to the backup OS account and authorized recovery administrators.
   Confirm effective DSM ACLs and encryption, and test remount after reboot.
   Keep its recovery material off the NAS. In that mounted share create an
   owner-only storage directory (`0700`) and a `.tabula-nas-storage` file
   containing a newly generated 32-character hex ID. Copy that ID into the
   private config. The runner requires an existing directory and matching
   marker; it never creates a fallback destination when a share is absent.
   This guard cannot prove encryption or detect a copied marker. The operator
   must verify the actual mount/ACL/encryption before enablement.
2. Create a separate private configuration directory outside the source tree
   for **each environment/database**. Copy `backup.example.json` and
   `pg_service.example.conf` from `deploy/nas/`. Replace all placeholders
   privately. All config, service, password and recipient files must be owned
   by the task UID and mode `0600`; the storage directory must be owned by that
   UID and mode `0700`. The runner rejects group/world permissions on POSIX.
   Inspect parent-directory access and DSM ACLs separately; mode bits alone
   do not attest those controls. Do not embed passwords in service files.
3. The single `[backup]` service selects the **direct/unpooled** endpoint,
   database and backup role, `sslmode=verify-full`, a trusted CA bundle,
   `channel_binding=require` and `connect_timeout=15`. Use the system CA bundle
   in the image. A non-Neon pooler alias still requires operator detection;
   the runner rejects Neon's `-pooler` hostname form. Inventory effective
   grants; the role must read all intended tables, sequences and schemas,
   including data subject to RLS, and must not silently dump a tenant subset.
   `pg_dump` retains its normal row-security protection and errors if full
   coverage is unavailable. Never enable row-security filtering for this job.
4. Store the password in the protected `pgpass` file using libpq's exact
   `host:port:database:user:password` format (escape `:` and `\` in values).
   Keep a distinct file/configuration for UAT. There is no application-secret,
   environment-variable password, `.env.local` or default-service fallback.
   The scheduled command contains paths only. Never print/copy files or
   connection strings into logs, GitHub, screenshots or error reports.
5. `source_sha256` is SHA-256 of UTF-8
   `lowercase-host:decimal-port/database`, excluding credentials. Compute it
   privately from the selected service values. This NAS namespace fingerprint
   has its own encoding; it is **not** #259's application endpoint fingerprint.
   Check Neon branch lineage independently. Never substitute the application
   verifier's hash for this value. Production and UAT use separate configs,
   secrets, and `environment/source_sha256` archive/status/lock namespaces.
6. Generate an age identity on the authorized recovery operator's protected
   system. Place only the public recipient in `recipients.txt` on the NAS.
   Keep the private identity in approved off-NAS custody accessible to the
   alternate operator, and prove decryption before scheduling. The backup task
   needs no decryption key. Record the recipient-file digest and custody/access
   evidence privately. Changing recipients affects future generations only;
   keep every identity required by retained generations. Each capture encrypts
   with a private per-run copy of the public recipient bytes and records the
   digest of those same bytes, so rotating the configured file during encryption
   cannot mislabel the generation's key custody. A failed run may retain this
   public-only copy with its other quarantined evidence.

The source role/ownership/grants, required extensions and provider-managed
roles need an independent recovery inventory. `pg_dump` captures database-local
objects and ACLs but does not recreate cluster roles or provider grants.
Retain a private reviewed role/grant recreation procedure without password
material. Do not publish `pg_dumpall --globals-only` output or automate replay
of provider roles. Inventory future identity/job/audit/control-plane objects too.

## NAS command and schedule

Use a fixed reviewed wrapper outside the source tree. Example for a configured
production database (replace UID/GID, host paths and image ID privately):

```sh
#!/bin/sh
exec docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 1026:100 \
  --mount type=bind,source=/volume1/PrivateBackupConfig/production,target=/secrets,readonly \
  --mount type=bind,source=/volume1/EncryptedRecovery/postgres,target=/backup \
  sha256:REPLACE_WITH_REVIEWED_IMAGE_ID "$@" --config /secrets/backup.json
```

Use `--mount`, which fails for a missing host source, rather than `-v`'s
automatic directory creation. Ensure the Docker execution account is authorized;
daemon access is privileged even though the process uses a restricted UID. Do
not grant ordinary application users access. The entire encrypted share must
protect scratch data: plaintext exists under `incomplete/` during the dump and
may remain there after failure/interruption. Never place that share on Cloud
Sync or expose it through application static/download routes.

Run `wrapper preflight` on the NAS. It checks real TLS, schema revision, client
major versions, age availability and reports free bytes, without publishing
connection details. It performs read-only source queries, not a dump or restore.
Then authorize and execute a controlled `wrapper run` and isolated restore.

### Client TLS and Neon proxy troubleshooting

Neon may terminate TLS at its proxy: a verified client connection can coexist
with `ssl = false` in backend `pg_stat_ssl`. That backend view describes the
proxy-to-PostgreSQL link and cannot validate the NAS-to-proxy TLS session.
The runner uses a private Psycopg subprocess with the same sanitized libpq
service/password environment as the dump. It reads `connection.pgconn.ssl_in_use`
(libpq `PQsslInUse()`) on the **same connection** that reads server/schema
metadata in a read-only transaction. It refuses a non-TLS connection. Both
configuration validation and the metadata connection require
`sslmode=verify-full` and `channel_binding=require`; certificate/hostname and
authentication failures remain fatal. The dump continues using those required
service settings. No production credentials or endpoint are printed.

Successful preflight exits zero and emits JSON with this shape (version,
schema and free-space values depend on the selected database and NAS):

```json
{"free_bytes": 123456789, "schema_version": "0005_bookkeeping_cutover", "server_version_num": 180006, "status": "compatible", "tls": true, "tools": {"pg_dump": "18.6", "pg_restore": "18.6", "psql": "18.6"}}
```

`compatible` means client TLS, required schema-revision syntax, all three
client/server majors, age availability and minimum free space passed. It does
not establish archive or restore acceptance. The schema need not equal the
example: compare it privately to the intended source release.

If `code` is `source`, privately check the selected direct endpoint, CA bundle,
hostname, role/password, channel-binding support and `public.alembic_version`.
Do not weaken TLS/channel binding or substitute backend `pg_stat_ssl` for the
client check. Missing/inaccessible Alembic metadata or malformed/empty revisions
fail. For `client`, check all three client versions against the server major.
For a newly imported image, verify its immutable ID and helper hashes below;
reusing an old wrapper image ID still runs the old check. Missing Psycopg or
helper files also fail closed as `source`; rebuild the complete image. Provider
diagnostics stay private; the runner intentionally returns only fixed guidance.

### Build and import the corrected ARM64 image

Use a development machine or CI runner with Docker Buildx and ARM64 execution
support (native or emulated), avoiding a build on the 512 MB NAS. From the
reviewed fix checkout, these PowerShell commands produce a single-platform
Docker archive; record the commit, image ID and both hashes privately:

```powershell
git rev-parse HEAD
docker buildx build --platform linux/arm64 --load -f deploy/nas/Dockerfile -t tabula-nas-backup:neon-tls .
if ($LASTEXITCODE -ne 0) { throw 'Image build failed' }
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' tabula-nas-backup:neon-tls
Get-FileHash scripts/nas_postgres_backup.py,scripts/nas_postgres_source.py -Algorithm SHA256
docker image save --output tabula-nas-backup-neon-tls-arm64.tar tabula-nas-backup:neon-tls
if ($LASTEXITCODE -ne 0) { throw 'Image export failed' }
Get-FileHash tabula-nas-backup-neon-tls-arm64.tar -Algorithm SHA256
```

The inspect result must say `linux/arm64`. Package security updates are resolved
at build time, so subsequent rebuilds can produce different IDs. Transfer this
exact archive to `/volume1/Tabula_Rasa_Postgres/` using the authorized NAS file
transfer route; keep it outside the source tree and backup-generation namespace.
Compare `sha256sum /volume1/Tabula_Rasa_Postgres/tabula-nas-backup-neon-tls-arm64.tar`
with the recorded archive hash. In Synology **Container Manager → Image → Add →
Import**, select that archive and wait for import to finish. Do not create a
database container or alter scheduled tasks.

In the authorized NAS shell, retrieve the imported immutable image ID, verify
the architecture and check the shipped scripts against the recorded hashes:

```sh
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' tabula-nas-backup:neon-tls
IMAGE_ID=$(docker image inspect --format '{{.Id}}' tabula-nas-backup:neon-tls) || exit 1
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 1027:100 --entrypoint sha256sum "$IMAGE_ID" \
  /opt/tabula/nas_postgres_backup.py /opt/tabula/nas_postgres_source.py
docker run --rm --read-only --user 1027:100 --entrypoint python3 "$IMAGE_ID" \
  -c 'import psycopg; from psycopg import pq; print("psycopg", psycopg.__version__, "libpq", pq.version())'
```

The image ID must match the build-host ID, both script hashes must match the
reviewed checkout, and libpq must support PostgreSQL 18. These inspection
containers have no credentials or archive mounts.

After these checks, the **operator** updates
`/volume1/Tabula_Rasa_Postgres/config/bin/run-production.sh`: preserve an
owner-only copy, edit only the existing `sha256:...` image reference to the
verified new `IMAGE_ID`, and retain `--user 1027:100`, current hardened flags,
production config mount and `/volume1/Tabula_Rasa_Postgres/archives` mount.
Keep the existing container mount targets, since `backup.json` uses them.
Do not change credentials, keys, UAT settings or scheduler registration. Check
the replacement image ID privately in the wrapper, then run:

```sh
/volume1/Tabula_Rasa_Postgres/config/bin/run-production.sh preflight
```

Require exit zero, `status: compatible`, `tls: true`, the intended schema
revision and matching major-18 tool/server values. This is a read-only source
check, not a backup. Keep #294 open: controlled backup execution, scheduling,
retention, failure drills and retained-archive isolated restore acceptance
remain separate operator work. These instructions do not perform deployment.

Configure **DSM Task Scheduler** with a known `America/New_York` local timezone
and working NTP; verify the displayed timezone and next-run dates. Do not
silently change a shared NAS timezone. Register the production `wrapper scheduled`
task for **Sunday and Wednesday at 22:00 America/New_York**, following DST.
On the 512 MB DS220j, stagger UAT's
scheduled capture to **22:30 Eastern** to avoid concurrent backup jobs; the
runner's due-slot calculation for both environments remains 22:00 Eastern.
If DSM cannot express both weekdays, use separate day-specific tasks. Register
separate `wrapper scheduled` catch-up and `wrapper status` health-check jobs
for each environment. The current operator-selected cadence is **every 3 hours
for production** and **every 6 hours for UAT** to limit container-launch
pressure on the DS220j; validate their actual execution history.

Give the recurring tasks explicit, distinct local-time phases. For example:

| Environment | Catch-up (`wrapper scheduled`, daily) | Health (`wrapper status`, daily) |
| --- | --- | --- |
| Production (3-hour) | 00:05, 03:05, 06:05, 09:05, 12:05, 15:05, 18:05, 21:05 | 00:15, 03:15, 06:15, 09:15, 12:15, 15:15, 18:15, 21:15 |
| UAT (6-hour) | 02:35, 08:35, 14:35, 20:35 | 02:45, 08:45, 14:45, 20:45 |

These are registration examples, not evidence of deployed minute offsets.
Do not place a UAT catch-up tick between 22:00 and its 22:30 scheduled capture:
it would consume the same due slot early and defeat the intended stagger.
Inspect DSM next-run dates and execution durations for all tasks together,
including across DST; distinct start times reduce launch contention but do not
guarantee nonoverlap if a job runs long. The runner's lock is per
environment/database, not a shared NAS lock. If observed durations overlap,
review phases and capacity with the operator before accepting the schedule.

These are slower-than-hourly checks, so detection/notification can be delayed by up to
roughly the check interval plus execution/runtime latency. Neither cadence
changes the runner's 24-hour catch-up limit nor retries an already attempted
failed slot. Configure nonzero-exit notification to the authorized operator. Healthy/no-attempt and in-progress-within-grace results exit zero;
failed, missing, stale, capacity and overdue states exit nonzero. Configure notification on abnormal
termination, not on every successful tick. In DSM Control Panel → Notification →
Email, configure the separate **Sender email** service and authorized recipient
profiles; Synology Account's successful test email alone does not establish
Task Scheduler delivery. Test both a synthetic scheduled successful task and an
`exit 1` failure-only task, verify actual emailed results, and remove the test
task. Do not test delivery by deliberately breaking real backup jobs. The archive task alone
cannot detect its own missing registration or a powered-off NAS; use an
independent external availability/check-in monitor or a recorded operator
health-check responsibility for that failure boundary. Coordinate future
central alert integration with #332; no general job framework is introduced.

The runner computes Sunday/Wednesday 22:00 in `America/New_York` from timezone
data, independently of container local time. UTC capture times are recorded in
manifests. It attempts the most recent due slot once, including a missed slot
up to **24 hours** late. It never replays a backlog. The attempt and its first-run
namespace parents are persisted before any remote call; failure/interruption consumes that slot. Further
attempts require `run` by an operator after diagnosis or the next due slot.
The local `.lock` directory excludes overlapping invocations of the same
environment/database. It has no automatic expiry. A kill/power loss may leave
it behind: confirm the old process/container has stopped, record the failure,
then remove **only that exact empty `.lock` directory** before one manual run.
Never delete a retained generation or incomplete directory to clear a lock.

## Archive and health contract

The runner executes `pg_dump -Fc`, traverses/decompresses the entire archive
with `pg_restore --file /dev/null`, encrypts it with age, hashes the ciphertext,
flushes the files and renames the generation from `incomplete/` to `complete/`.
On the POSIX NAS host it syncs the manifest, publication and namespace directory
entries before persisting the last-success pointer, and syncs status replacement
before returning success. A directory-sync failure remains an actionable failed
run, even if the complete archive is already present. Filesystem/device durability
still depends on the NAS storage honoring sync requests; this is not a substitute
for the actual device power/recovery and protected-storage checks.
Only a complete directory containing `database.dump.age` and `manifest.json`
belongs to the usable set. The manifest records UTC capture-start/completion,
environment, source fingerprint, server/schema/client versions, TLS preflight,
recipient digest, archive size/checksum and completion status. Dump parsing
and checksum checks do not prove successful SQL restore or complete business
coverage; the drill below does. Do not deploy schema changes during a capture;
the revision observation precedes the dump snapshot. Capture start is a
conservative backup-age bound, not an exact database commit timestamp.

`wrapper status` checks the last successful generation's ciphertext checksum,
capacity and current slot. A previous generation becomes stale two hours after
the latest due slot, allowing execution time. It reports capture-based age in
seconds and last-success completion; the 2-hour grace is **not** an RPO promise
or a whole-job timeout. Each long client operation has a 2-hour limit. `running`
becomes `overdue` after two hours, which may indicate interruption. A failed attempt stays
visible while the previous verified generation remains available. A failure
after publication but before status update leaves a complete recoverable
directory with conservative running/failed health; inspect it with
`verify --generation <directory-name>` before recording private evidence or
requesting another run. Do not manually report success from a partial directory.

Each successful generation is retained **indefinitely**. There is no expiry,
pruning, automatic rotation or deletion of retained artifacts. Only the current
run's transient plaintext is removed after encryption succeeds. Incomplete
artifacts are quarantined and need separately approved exact-target cleanup.
Set `minimum_free_bytes` to an operator-approved reserve sufficient for an
uncompressed working dump, encrypted output and growth. The example 1 GiB is
only an initial placeholder, not capacity certification; mid-run exhaustion
still fails safely. Inspect `status` free bytes and DSM storage trends and set
an actionable capacity notification. Unlimited retention does not mean unlimited
capacity. Preserve #259 evidence and verified copies before considering any
explicit future retention-policy change under #223/#339.

Measure the actual selected project's remaining Free compute/transfer allowance
before enabling recurrence. [Neon plans](https://neon.com/docs/introduction/plans)
currently describe shared project allowances; recheck the actual console/plan
rather than hardcoding them in this runner. Record before/after compute and
public-transfer usage for a representative backup, duration, compute size,
archive bytes, cold-start/idle overhead, other production/UAT demand and NAS
free space. Budget up to ten scheduled captures per calendar month **per
selected database**, plus controlled/manual runs and restore drills. Archive
size is not a network-transfer measurement; dump compression happens client
side. Record headroom and quota/capacity gaps, and stop enablement if inadequate.

## Isolated retained-archive restore drill

1. Record authorization, incident/drill declaration time, exact new isolated
   database target, image/application release and source lineage. Never restore
   onto production or UAT. Inventory all expected entities/databases and objects.
   Pause source writes for the representative controlled capture and retain
   independent private canonical exports for **every** expected bookkeeping
   entity, including two entities with overlapping local IDs when available.
   Resume writers only after the controlled capture finishes.
2. Select a retained complete generation. Run the runner's `verify` action with
   `--generation <directory-name>` to check source/environment, size and SHA-256.
   This verifies ciphertext integrity only. In a restricted recovery workspace,
   decrypt with the off-NAS key and validate the archive before restoring:

   ```sh
   age --decrypt --identity /protected/identity --output /protected/restore.dump /protected/database.dump.age
   pg_restore --file /dev/null /protected/restore.dump
   ```

3. Provision only the approved **new empty isolated database**, compatible
   server/extensions and reviewed roles. Inject its own explicit libpq
   service/password file using protected operator storage. Independently verify
   the destination's project/branch/database and TLS before `pg_restore`.
   Do not reuse the source backup service or default connection. Run:

   ```sh
   pg_restore --no-password --exit-on-error --dbname 'service=isolated_recovery' /protected/restore.dump
   ```

   Use explicit `PGSERVICEFILE`/`PGPASSFILE` paths for this recovery process.
   There is deliberately no automated live restore command. Do not use
   `--clean`, `--create`, automatic ownership/ACL suppression or source overwrite
   to force success. Investigate failures and retain the isolated target.
4. Compare the complete database/schema/security inventory: schemas, tables,
   sequences, all entities, constraints, functions/triggers, extensions,
   ownership, effective grants, authority, identity/job/audit/control records
   and release/Alembic revision. Restore uses the historical capture's compatible
   release; do not stamp/upgrade the target before verifying it.
5. Use #259's existing `scripts/verify_postgres_recovery.py inspect` and `verify`
   with the isolated target's explicit `TABULA_RASA_RECOVERY_DATABASE_URL` and
   independently retained source exports. Follow its distinct source/target
   fingerprint contract. Run it for every expected bookkeeping entity. Verify
   overlapping local IDs stay isolated, relationships/content are complete,
   transfers/mileage retain their semantics, and balance/accounting integrity
   holds. Separately verify objects outside its `entity_bookkeeping` scope.
6. Record elapsed declaration-to-verified recovery time including operator/key
   access, target creation, decrypt/restore and all validation; source capture
   time, actual backup age/point gap, included/excluded controlled commits and
   limitations. Retain private reports, source/target inventory and the tested
   archive. Link **sanitized** additional NAS evidence to #259 when GitHub-write
   authorization is available. Keep ongoing health/retention ownership in #294.
   Have the alternate operator repeat the documented procedure.

Sunday/Wednesday backups are approximately three/four days apart, longer after
failures; they do not meet the proposed 24-hour fallback or 5-minute PITR RPO.
They are logical database recovery points, not Neon managed snapshots or PITR.
Receipt/document bytes remain the separate DocumentStore recovery responsibility
under #223/#337/#338. Filesystem versioning protects only already captured
files. Neither this tooling nor a successful database drill supplies commercial
readiness, a live authority switch or full-service/document recovery.

## Acceptance evidence still required on the selected NAS

- [ ] Direct ARM64 execution, exact DSM/package/image versions, compatible TLS
  PostgreSQL clients and resource capacity are proven on DS220j.
- [ ] Private destination/database inventory, owners, alternate operator,
  secret/ACL/encryption/remount checks and both key-custody plans are recorded.
- [ ] Production/UAT bindings are independently checked; all intended databases
  have distinct protected configuration and complete coverage.
- [ ] Sunday/Wednesday 22:00 Eastern production and 22:30 Eastern UAT registration,
  DST next-run dates, controlled scheduled runs, **production 3-hour and UAT
  6-hour** catch-up/health ticks, and independently delivered health alerts work
  with Windows/application offline.
- [ ] Failed/interrupted/missed-run tests preserve the last usable archive;
  partials remain quarantined. Capacity visibility and no-prune retention hold.
- [ ] Actual Free-plan compute/transfer usage and backup-point gaps are measured.
- [ ] A retained NAS archive decrypts/restores into isolation and passes complete
  inventory, entity isolation, accounting integrity/content and alternate-operator
  checks. RTO/age/limitations and additional #259 evidence are recorded.


## Operator evidence checkpoint — October 18–19, 2026 (not final acceptance)

The operator confirmed that a genuine DS220j scheduled production backup at
Sunday 22:00 EDT and UAT backup at Sunday 22:30 EDT each exited `Normal (0)`,
published a complete encrypted generation and reported healthy status. The
separate DSM email sender was configured; a synthetic scheduled success email
and an abnormal-only `exit 1` Task Scheduler email were delivered. The test
task was removed, and email notifications were enabled on production/UAT
catch-up and health jobs. This tests DSM email transport, **not** an actual
NAS backup-health failure or a powered-off NAS; the independent external
check-in remains outstanding.

Retained UAT generation
`20261019T023012740769Z-6b2a00acbb1d455faa7c707fab531518`, completed
`2026-10-19T02:30:24.982350Z`, recorded PostgreSQL 18.6 and revision
`0014_document_locations`. Its ciphertext digest matched the manifest,
the privately held age identity matched the NAS public recipient, decryption
and archive traversal succeeded, and a separate empty Neon recovery database
accepted `pg_restore --single-transaction --exit-on-error --no-owner
--no-privileges` with exit zero in **25.6577183 seconds**. The restored
database has 52 public tables, 2 sequences, 106 foreign keys, 209 check
constraints (0 unvalidated), and the exact manifest revision. The application
canonical verifier matched 7 of 8 business entities exactly. The eighth
had an independently timed post-capture receipt upload (new document/link,
entry version and update timestamp). Subsequent logins explain differences
in ephemeral identity records. No unexplained financial-content differences
were identified. See [#294 operator evidence](https://github.com/Roklion/Project_Tabula_Rasa/issues/294#issuecomment-6259851298).

**Limits:** The 25.66 seconds is SQL restore execution time, **not** end-to-end
declaration-to-verified database RTO. The target was restored using ownership
and privilege suppression, so source grants, roles, authority and security
parity still require verification and recovery-role handling. Expected
bookkeeping exports were made after capture; a controlled capture with
independent exports at the recovery point remains the higher-standard test.
External DocumentStore receipt bytes are not in a PostgreSQL archive.
Genuine interrupted/missed NAS runs, offline detection, NAS encryption/remount
and operator custody, capacity/quota headroom, and alternate-operator recovery
remain open. Do not delete the recovery target or retained archive before
authorization and evidence acceptance.

## Developer validation

Focused unit tests are in `tests/test_nas_postgres_backup.py`. The self-contained
synthetic client drill starts a new private PostgreSQL cluster inside the image,
uses verified TLS/SCRAM channel binding, backs up two entities with overlapping
IDs, decrypts/restores to a new database, compares content and broader objects,
then checks real certificate/hostname/authentication failures and ciphertext corruption. It publishes
no port and cleans only its own fresh synthetic fixture. It does not substitute
for canonical application bookkeeping verification or real NAS/provider evidence.

```sh
docker build -f deploy/nas/Dockerfile -t tabula-nas-backup:test .
docker run --rm --user postgres --entrypoint python3 \
  --mount type=bind,source="$PWD/tests/tooling/nas_backup_smoke.py",target=/smoke.py,readonly \
  tabula-nas-backup:test /smoke.py
```

Primary tool references: [pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html),
[pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html),
[libpq service file](https://www.postgresql.org/docs/current/libpq-pgservice.html),
[password file](https://www.postgresql.org/docs/current/libpq-pgpass.html),
[Neon logical backups](https://neon.com/docs/manage/backup-pg-dump), and
[age](https://github.com/FiloSottile/age).
