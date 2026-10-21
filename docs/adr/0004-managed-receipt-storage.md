# ADR 0004: Drive-first receipt storage and optional managed providers

Date: 2026-10-16; amended 2026-10-17 by the owner's Drive-first direction. Status:
Google Drive remains active. S3 is optional engineering groundwork; commercial provider
adoption requires a separate review. Drive storage and byte recovery require no AWS
account, billing, bucket or credentials.

PostgreSQL owns document metadata and bookkeeping links; `DocumentStore` owns bytes and
authenticated same-origin APIs own transport. Drive and the explicit restricted-alpha
binding remain supported. Live use, hosted recovery evidence, commercial recovery
agreement and external release require separate approval.

## Focused shortlist

All three options support private server access from Render over HTTPS, managed
durability, signed requests and supported Python SDKs. Render's ephemeral disk
is not receipt storage. Cross-cloud transfers, account custody and capacity must
be included in the operator's stage budget.

| Candidate | Low-volume cost and operations | Recovery and integration tradeoff |
| --- | --- | --- |
| AWS S3 Standard | Pay for retained GB-months, PUT/LIST and GET requests, and applicable internet egress. No reliance on introductory credits. | Native version IDs, version reads, delete markers, lifecycle, IAM and optional Object Lock/replication. Boto3 and atomic conditional PUT fit stable receipt identities; regional service requires choosing the actual Render/S3 region and latency boundary. |
| Cloudflare R2 Standard | Published $0.015/GB-month, $4.50/million Class A, $0.36/million Class B, free egress; included monthly usage favors a small beta. | S3-compatible APIs and strong consistency simplify bytes, but API compatibility is operation-specific. This implementation requires AWS version-enabled buckets and version-pinned reads; R2 is not silently treated as a drop-in recovery implementation. |
| Google Cloud Storage Standard | Region-dependent storage, operation and network rates; retained generations/soft-deleted data are also billed. | Native generations/versioning and soft delete are viable. Requires another SDK/credential path rather than reusing Drive OAuth, with location/egress and soft-delete retention decisions. |

Sources checked for this decision: [S3 pricing](https://aws.amazon.com/s3/pricing/),
[AWS calculator](https://calculator.aws/),
[S3 durability/availability design](https://docs.aws.amazon.com/AmazonS3/latest/userguide/DataDurability.html),
[S3 versions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html),
[conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html),
[R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[R2 consistency/durability](https://developers.cloudflare.com/r2/how-r2-works/),
[R2 API inventory](https://developers.cloudflare.com/r2/api/s3/api/),
[GCS pricing](https://cloud.google.com/storage/pricing),
[GCS versions](https://docs.cloud.google.com/storage/docs/object-versioning), and
[GCS lifecycle](https://docs.cloud.google.com/storage/docs/lifecycle).

## Decision and stage budget

Continue **Google Drive** for the current owner-operated storage and PostgreSQL
receipt recovery path, reusing existing OAuth/folder/connection infrastructure.
The new explicit verified byte archives and isolated Drive restore do not need
AWS setup. Actual Drive capacity/access/retention and hosted recovery evidence
remain explicit selected-provider checkpoints, not assumptions.

If document-provider adoption review later elects managed object storage, **AWS S3
Standard** is the current implementation candidate for native recoverable versions and
straightforward IAM boundaries; reassess this comparison and current costs before
adoption. Its published design targets are 11 nines of durability and 99.99%
availability, not evidence of achieved application recovery. Avoid infrequent/archive
classes and their retrieval/minimum-duration costs initially. Use SSE-S3 (AES256), HTTPS
and private, version-enabled buckets. KMS, Object Lock, replication and external byte
archives require separate cost/policy approval.

For planning, at illustrative US Standard unit rates of $0.023/GB-month,
$0.005/1,000 writes/lists and $0.0004/1,000 reads:

| Stage assumption | Storage + requests/month before egress/tax |
| --- | --- |
| Synthetic staging: 1 GB, 1,000 writes/lists, 5,000 reads | $0.030 |
| Small beta: 10 GB, 10,000 writes/lists, 100,000 reads | $0.320 |
| Beta plus one complete retained byte copy at the same request volume | $0.550 |

These are budget examples, not a quote or a free-service promise. Versions,
independent copies and inventories increase stored bytes and requests; migration
and restore copy/read every selected receipt. Recalculate in the actual selected
region with current rates, Render outbound transfer, aggregate AWS egress
allowances, account consumption and alerts before provisioning. A repeated full
inventory incurs LIST plus per-object HEAD requests; set operational capacity
limits before scaling. R2's cheaper egress is attractive, but avoiding a separate
version/recovery design is the deciding factor at this workload.

## Contract and responsibility boundaries

Keys contain only an approved environment/random namespace, an entity hash and
an opaque document-derived hash. Filenames and bookkeeping data never form object
paths. A locator pins the provider version independently of the canonical ID.
Object metadata duplicates only the provenance required for orphan discovery;
SQL owns canonical metadata and links. No SQL blobs or alternate live ledger.

The browser receives canonical IDs and authenticated same-origin bytes, with fresh
server authorization and external connections membership/capability checks on every
provider operation. It gets no S3 credentials or signed bearer URLs. An S3 connection
can coexist with the retained Drive grant; explicitly installed S3 wins and never falls
back to Drive on failure/disconnect. The Google connection browser controls continue to
manage Google only; managed setup/rotation/recovery are operator actions in this scope.

Uploads are bounded by the existing receipt service, streamed to/from the SDK
with bounded reads, SHA-256 checked, and conditionally created. SDK retries are
disabled. A failed PUT receives one fresh readback; only established absence
permits one retry. Success needs no readback. A failed SQL link keeps the receipt
in provider inventory. Unlink remains reference-only. Explicit deletion creates
a marker and never deletes a version. Migration/restore verification deliberately
reads exact bytes before atomically promoting locations, retaining originals.

The object-key, S3 version-pin and IAM discussion above applies to the optional
adapter. See [Drive storage and recovery](../storage/RECEIPT_RECOVERY.md) for
the active provider's backup/restore, operator approvals and unresolved evidence,
and [optional object storage](../storage/OBJECT_STORAGE.md) for deferred S3 setup.
