# Sealed custody admission

## Status and boundary

**Current maintenance status: green focused offline, but not release accepted.** The current source includes the whole-image/witness protocol and the root-entrypoint, running-interpreter, foundational native-library, installed `solders.solders` extension and finite solders Python-source fingerprint increments. These in-process checks do not attest code before execution, mapped-memory identity, standard library/bytecode, nested SDK modules beyond the selected manifest, other shared libraries/extensions, alternate filenames or complete installed package artifacts. Production verifies both genesis pins, checks fresh tips, and binds heartbeat address, owner and pair. Offline first-start and independently approved replacement are documented below. These controls still need a test-asset rehearsal on the target nodes and witness host; real funds are not approved. See the [October 2 review](../DEVELOPMENT_REVIEW_2026-10-02.md) and [current repair plan](../plans/2026-09-25-recovery-admission-and-capacity-fairness.md).

The October 2 review and its documentation-only publication correctly describe the custody implementation as an unpublished local candidate at that dated snapshot. The current source now implements the independent sealed-image admission gate in normal service startup and the read-only dashboard, plus a reference witness. It does **not** deploy, provision, or operate an independent witness service. `main.run()` takes the singleton lock and calls `custody_admission.claim()` before `state_db.init_db()`; workers cannot start until recovery succeeds and `Lease.complete()` succeeds. Missing configuration refuses startup in every mode. The dashboard consumes `custody_admission.dashboard_status()`; local SQLite counts never establish complete liabilities.

The control closes one specific restore gap: a runtime may execute only against the exact whole SQLite file most recently approved by an independent witness. The certificate binds every table, index, trigger, schema statement, page, freelist byte, and SQLite header through whole-file SHA-256 and byte size. It also binds a canonical schema digest, deployment configuration, and the currently implemented source manifest.

It does not reconstruct missing funds, validate chain truth, prove solvency, make an unreviewed backup coherent, or independently attest code that executes before the in-process fingerprint.

## Trust and deployment assumptions

The witness history must be on a separately administered server and storage domain with anti-rollback protection, durable backups, access review, monitoring, and an append-only export or equivalent protected audit sink. Copying the witness SQLite file beside the custody database defeats the independence assumption. Root compromise of both domains defeats the control.

Use independent operators for custody runtime access and initial witness approval. Generate two random secrets of at least 32 characters:

- `CUSTODY_WITNESS_TOKEN`: runtime capability; permits `GET head` and `POST claim/complete/seal/hold`.
- `CUSTODY_WITNESS_ADMIN_TOKEN`: distinct administrative capability; permits first issuance and independently reviewed replacement through the witness-host CLI.

The reference HTTP server binds loopback only. Place it behind a correctly authenticated TLS reverse proxy. The runtime client requires an `https://` origin, verified TLS, bounded connect/read timeouts and response size, disables environment proxy inheritance, and never follows redirects. Do not put either secret in a URL, command line, log, audit event, exception, or dashboard.

The reference store uses transactional compare-and-swap and hash-linked append-only events. Its local triggers reject audit event update/deletion. Those controls do not protect against a witness host administrator replacing the entire store; deployment anti-rollback storage and independent audit export remain required.

## Certificate

A certificate has exactly these fields and rejects booleans, coercions, unknown fields, uppercase/noncanonical hashes, and duplicate JSON keys:

```json
{
  "deployment_id": "bridge-production",
  "generation": 0,
  "permit_nonce": "64 lowercase hex characters",
  "image_sha256": "64 lowercase hex characters",
  "image_size": 4096,
  "config_sha256": "64 lowercase hex characters",
  "build_sha256": "64 lowercase hex characters",
  "schema_sha256": "64 lowercase hex characters",
  "issued_at": 1800000000,
  "approval_rationale": "reviewed coherent custody backup and current runtime terms"
}
```

`config_sha256` binds all effective public uppercase configuration settings, including production mode, limits/caps, minimums/dust, finality, fees, heartbeat and service/query owners, retry budgets and timeouts, as well as the configured pair and independently pinned immutable chain identities. Credentials/transient session values are excluded explicitly; private locations are hashed, never published. Changing safety settings, endpoints, custody identities or the build requires separate approval, not reuse of an existing permit.

The current `build_sha256` implementation binds `src/*.py`, root `swapService.py`, `requirements.txt`, and domain-separated evidence for the running Linux executable bytes (`/proc/self/exe`) plus the on-disk files backing conventional executable libpython/libc/libm/loader mappings (`/proc/self/maps`). A further domain-separated component hashes the installed `solders.solders` native extension selected by `PathFinder` without executing its package initializer or library. It requires an absolute recognized extension filename and exact loader/origin agreement, performs bounded nonblocking reads with descriptor/path metadata continuity, and repeats discovery before accepting evidence.

A separate domain-separated source component hashes the conventional installed `solders/__init__.py`; the seven direct runtime wrappers `hash.py`, `instruction.py`, `keypair.py`, `message.py`, `pubkey.py`, `signature.py` and `transaction.py`; the eighteen additional mandatory flat wrappers `account.py`, `account_decoder.py`, `address_lookup_table_account.py`, `clock.py`, `commitment_config.py`, `compute_budget.py`, `epoch_info.py`, `epoch_rewards.py`, `epoch_schedule.py`, `errors.py`, `null_signer.py`, `presigner.py`, `rent.py`, `slot_history.py`, `stake_history.py`, `system_program.py`, `sysvar.py` and `transaction_status.py`; the eager package initializers `token/__init__.py` and `rpc/__init__.py`; and the eagerly attempted `litesvm.py` and `transaction_metadata.py` wrappers. The pinned wheel's valid empty `rpc/__init__.py` is bound by its empty-byte digest; every other selected source must be nonempty. Discovery uses `PathFinder` and exact `SourceFileLoader`/origin/package-search agreement without execution; bounded nonblocking reads recheck descriptor/path metadata, earlier files and the complete discovery result.

Nested token/RPC modules beyond their initializers, other SDK dependencies and executed bytecode remain outside this source manifest. The native/source manifests are independent of normal service/dashboard import differences. Conventional glibc/musl and `ld`/`ld64` names are recognized; alternate filenames are not generally discovered. Selected file bytes are streamed with device/inode, mode, size and timestamp continuity checks and repeated discovery/mapping snapshots. Missing, unreadable, non-regular, unexpectedly empty, changing or ambiguous evidence refuses admission before permit consumption. These hashes do **not** bind mapped-memory contents, standard library/bytecode, every shared library/extension or all installed dependency artifacts, and are not pre-execution attestation. Batch 0 must externally enforce complete artifact identity. Manifest changes invalidate prior build approvals; upgrades require independently reviewed new approval, never an automatic certificate rewrite.

`main.run()` verifies Solana `getGenesisHash` and Nexus `ledger/get/blockhash height=0` against independently approved pins before any database migration, scanner or recovery/reference lookup. Genesis is identity evidence from trusted endpoints, not proof that an untrusted endpoint is honest. Production also checks synchronization and tip freshness. Session configuration and heartbeat validation failures are fatal before lease completion. The heartbeat is addressed by its pinned register and checked against the pinned owner, service type and custody pair. Test these checks against the exact target node versions before launch.

Fees are current runtime policy, not historical authorization for individual liabilities. If fees change, an independent reviewer must explicitly approve the current runtime configuration in the certificate rationale. A new certificate cannot repair missing frozen intent in a restored row.

## State machine

A generation follows only:

```text
ready(g, permit) -> claimed(g, claim nonce) -> running(g, claim nonce)
                                           -> held(g)
running(g) -> ready(g+1, new permit)
running(g) -> held(g)
```

A permit is one-use. `claim` is idempotent only for the same random 64-hex claim nonce so an ambiguous network response can be read back. Stale generations, changed nonces, and consumed permits fail. `complete`, `seal`, and `hold` accept only the owning generation and claim nonce. A held generation cannot resume. The witness-host administrator may approve a new generation after reconciliation and signer fencing; no runtime HTTP route can do that.

Initial issuance is intentionally separate. The CLI consumes an externally prepared, independently reviewed certificate plus an explicit actor and rationale. It has no command that hashes or signs the current custody database:

```bash
export CUSTODY_WITNESS_TOKEN='<runtime capability>'
export CUSTODY_WITNESS_ADMIN_TOKEN='<separate admin capability>'
python -m src.custody_witness issue \
  --store /protected/witness/custody-witness.db \
  --certificate /reviewed/offline/certificate.json \
  --actor independent-reviewer \
  --rationale 'review board approval reference ...'
unset CUSTODY_WITNESS_ADMIN_TOKEN
```

Start the loopback runtime API behind a TLS proxy. The serving process deliberately does not load or retain the administrative capability:

```bash
export CUSTODY_WITNESS_TOKEN='<runtime capability>'
python -m src.custody_witness serve \
  --store /protected/witness/custody-witness.db \
  --host 127.0.0.1 --port 8790
```

Runtime endpoints are `GET /v1/deployments/<id>/head` and `POST .../claim`, `.../complete`, `.../seal`, and `.../hold`. Requests use bearer authentication and exact JSON field sets. Audit events contain transition identifiers and rationale, never credentials.

## Startup ordering

Configure every environment, including development and recovery runs:

```text
CUSTODY_WITNESS_URL=https://independent-witness.example
CUSTODY_WITNESS_TOKEN=<runtime capability>
CUSTODY_DEPLOYMENT_ID=<stable deployment identity>
CUSTODY_SOLANA_GENESIS_HASH=<independently approved canonical base58 hash>
CUSTODY_NEXUS_GENESIS_HASH=<independently approved height-zero hash: 256 lowercase hex>
```

There is no development/default opt-out. Missing witness configuration blocks admission.

Obtain chain pins from independently verified deployment records, never by automatically trusting the unverified runtime endpoint. The Nexus height-zero block hash is not a user's sigchain genesis. With the optional Nexus identity check enabled (default), the Nexus node must support `ledger/get/blockhash height=0` with its `-indexheight` index enabled, and unavailable indexing/query results refuse admission rather than falling back to a profile identity. Set `CUSTODY_NEXUS_IDENTITY_CHECK=false` to disable the check: admission then skips the query entirely and the operator accepts responsibility for verifying their node's LLL-TAO version. The custody host/filesystem must enforce exclusive trusted writing: no concurrent live restore or unauthorized in-place edit is supported; restoring requires a stopped service and the singleton lock. Host/root compromise is outside this control.

Required startup order:

1. Load configuration and take the singleton lock without creating or migrating the custody database.
2. Call `lease = custody_admission.claim()`.
3. Admission reads the external `ready` head and compares deployment, build, configuration, whole-file SHA-256, and size.
4. Admission consumes the permit with a fresh random claim nonce.
5. It retains an open descriptor and captures the original device/inode before hashing, rehashes the file, requires `-wal`, `-journal`, and `-shm` to be absent, runs read-only `PRAGMA integrity_check`, validates the schema digest and rechecks the original file identity. A replacement cannot become the trusted identity after hashing.
6. Verify observed immutable chain identities, revalidate the retained image immediately before database initialization/migrations, and run existing recovery. Recheck file continuity after initialization and before completion.
7. After recovery and mandatory session/heartbeat validations succeed, call `lease.complete()`. It fsyncs a local `claimed` receipt, completes the remote lease, then fsyncs the matching `running` receipt. No worker may start before this succeeds.
8. The main loop calls `lease.assert_running()` before each cycle. In production, failure to establish chain identity or freshness pauses new swaps, refunds, quarantine transfers and heartbeat writes. Read-only reconciliation and alerts continue; a backing-only pause can still settle existing obligations. Signers and the Solana submission worker independently recheck the running lease and chains. A request already handed off to a node cannot be recalled. All nested timeout/RPC threads are tracked; timed-out threads are not assumed stopped.

A local receipt is diagnostic continuity, not authority. It lives at `<STATE_DB_PATH>.admission.json`, is atomically replaced and fsynced, and cannot grant startup when copied. Healthy dashboard state requires an exact external `running` head and matching local `running` receipt for the deployment, generation, permit, claim, build, and configuration. The receipt additionally binds the database path/device/inode and the live writer's Linux boot ID, PID and process-start identity; a copied image/receipt or dead/reused PID cannot present a healthy live database. Linux `/proc` identity must be readable or admission fails closed. All other cases report `unknown` or `held`, with `liabilities_complete=false`.

The dashboard collects custody totals/counts in one read-only transaction snapshot and rechecks the exact witness generation/permit/claim after collection. An intervening transition or changed running lease suppresses healthy totals; a nonmatching held head reports unknown.

Before claim, rejection does not write the custody database or a receipt and does not consume a permit. If failure occurs after a successful claim, the generation is held whenever that can be established. For an ambiguous compare-and-swap, only an exact readback is accepted; otherwise startup fails and operator review is required.

## Graceful shutdown and sealing

The parent owns quiescence. It must stop admission of new work, signal every worker, join every worker, and prove no worker or callback can still access SQLite **before** calling `lease.seal()`. Never hold a seal permit while a worker might execute. If any thread is unresolved, call `lease.hold()` rather than seal.

`seal()` opens the existing database only, performs a truncate checkpoint, obtains an exclusive transaction, checks integrity, closes its connection, fsyncs the database and directory, rejects all ambiguous sidecars, computes the next exact certificate, and compare-and-swaps owned `running(g)` to `ready(g+1)`. There must be no database write after sealing. It finally writes a local `sealed` receipt.

A crash or unknown outcome after claim consumes the permit and blocks automatic restart. Completion/seal uncertainty is accepted only when exact remote readback proves the intended state; otherwise the lease is held. Never delete receipts, edit witness state, roll back the witness store, or seed fake source rows to bypass a hold.

## First-start and restore rehearsal (test assets only)

**First start.** Use a new deployment ID, dedicated never-used custody accounts, a new pinned heartbeat register with independently verified initial checkpoints, and a token with a reviewed unused debit-reference range. Keep deposits closed. Record the evidence, then on the custody host use `python -m src.custody_bootstrap prepare --image PATH --deployment ID --nexus-waterline N --solana-waterline S --reference-floor R`. `R` is the last reserved reference (use `0` only if that namespace is unused). This command refuses an existing path. The deployment-bound marker permits an empty certified image, not an empty replacement database, and never clears a recovery hold. Normal on-chain recovery still runs. Use `python -m src.custody_bootstrap describe --image PATH --deployment ID --generation 0 --rationale EVIDENCE_ID` in the intended runtime environment to emit a candidate certificate. An independent reviewer compares the exact image, config, build, heartbeat and empty-liability evidence before issuing it on the witness host with `custody_witness issue`. An idle restart must succeed without inserting fake transactions.

**Restore.** Close deposit intake. Stop the old process, confirm there are no pending workers, and disable its access to both signers and the witness before permitting a replacement. Preserve the old image, sidecars, logs and witness head for investigation. Use a coherent whole SQLite backup; never combine a database with unrelated sidecars. Compare both chain histories against the backup: deposits, confirmed and ambiguous payments, frozen terms, reference counter, held principal and rolling cap reservations. Resolve any gap from authoritative evidence or keep the service closed. A certificate does not fix missing liabilities. Prepare a candidate using `custody_bootstrap describe` with the same deployment ID and the current witness generation plus one. On the independent witness host run `python -m src.custody_witness restore --store PATH --certificate JSON --prior-permit-nonce CURRENT --actor REVIEWER --fencing-evidence RECORD_ID --reconciliation-evidence RECORD_ID`. Use non-secret evidence IDs. The witness records approval and replaces exactly the prior permit; it cannot prove that the old site physically disabled signing.

**Acceptance.** Start the replacement with test assets only. Verify both swap directions, interrupt a payout before recording the RPC response, and reconcile it by chain evidence without sending again. Verify witness refusal of the old permit, retention of pending principal and cap reservations, alerts on a signer pause, and recovery over the full intended history. Record the target build IDs, asset IDs, transaction IDs, backup and witness evidence, and reviewer approval. Reopen intake only after the rehearsal succeeds.

## Nexus recovery bound

Startup recovery and production deposit polling read the treasury owner's linked Nexus transaction history, not mutable register offsets. Mint reconciliation and interrupted mint recovery use the linked history of the pinned token register's owner. Use dedicated Nexus profiles (one may serve both roles) that created and continuously own their respective registers, each with no more than 5,000 transactions. A gap, unproven ownership, or truncation prevents the affected scan from authorizing progress. A fresh local database is not proof of zero mints: reconciliation requires a complete token history with no unmatched debits or unresolved local mint intents. A mint with a recorded txid is checked directly for exact, confirmed debit terms.

Startup deposit recovery rejects unconfirmed transactions other than writes to the pinned heartbeat (and their fees); a recent heartbeat alone must not prevent a clean restart. Live ingestion can process confirmed credits behind a mempool head but does not advance the checkpoint past shallow credits. Production publishes liveness and proposed checkpoints in one throttled write (`HEARTBEAT_MIN_INTERVAL_SEC`, use 300 seconds or more for the pilot). Use synchronous updates: the response must acknowledge the pinned register and return a transaction ID. The 5,000-row cap bounds the response, not node traversal. Check transaction counts on both custody profiles daily and close admission at 4,500 transactions on either profile, before the hard bound, leaving room for settlement and recovery. On the intended build and with test assets only, rehearse first start, idle restart with a pending heartbeat, both swap directions, history beyond 100 records, interruption after mint submission, a held refund, alert delivery, and restore with the old signer fenced.

The standalone `nexus_transfer_operator.py execute` command is test-only. In production it refuses before recording or claiming execution. Keep refund obligations held until there is an independently reviewed disposition path; do not disable production mode to send a refund.

## Verification scope

Focused offline tests cover strict certificate and JSON types, one-time permits, stale/replayed claims, permanent holds, hash-linked audit events, authenticated bounded HTTP behavior, exact normal images, online-backup clones, mutation of dynamically discovered user tables, missing images, ambiguous SQLite sidecars, uncertified existing databases, claim/complete uncertainty, repeated permit consumption, clean next-generation sealing, copied receipts, missing configuration and the selected executable/dependency drift boundaries. The latest recorded local maintenance gates are **558 focused tests** and **1443 complete-suite tests plus 77 subtests**; the October 2 unpublished runtime candidate's separate historical gate was 947 tests plus 77 subtests. These are offline local evidence, not committed-runtime history for the documentation-only candidate, live-chain acceptance or release approval. Tests use local stores and injected HTTP sessions; there is no insecure runtime transport switch and no live-chain activity.
