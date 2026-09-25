# Recovery admission and capacity-fairness repair plan — 2026-09-25

## Decision and scope

Reviewed source: `17f65a3e3b45281162c1604cd0a695a36dc55991`, compared with
`184f5d6a45ecd8f53ae37cfdd09e4b63092d1842`.

Keep the two new controls:

- the durable empty-custody startup latch; and
- dashboard suppression of apparently healthy backing/fee/cap values while that latch is held or unreadable.

They are narrow containment, not complete recovery admission. Production and real funds remain blocked.
This plan makes no dependency upgrade, provider-v2 cutover, receipt enablement, live transaction, commit,
or publication authorization.

## Repair order

### Batch 1 — prove a complete or conservatively held restore

**Priority: P0 financial authorization.**

A database with one surviving source row is not proof that every other obligation and frozen decision
survived. Replace the current `any(source row)` exemption with an admission protocol that can distinguish:

1. a verified coherent restore;
2. a genuinely new deployment approved through an audited bootstrap;
3. a partial, stale, conflicting or unknown restore; and
4. a deployment already populated by pre-fix replay.

For cases 3 and 4, do not classify rediscovered principal under current terms. Either reconstruct exact
historical authorization from an independent durable source or create a quantified, source-specific,
non-sendable recovery hold. Preserve network, vault, mint, token program, commitment, source signature,
source timestamp/account/memo, exact integer principal and the missing/conflicting authorization reason.
Count it in liabilities and pin recovery progress.

#### Collected RED acceptance

Use the real startup caller, deposit page commit, deposit worker and both disposition workers with only
chain/address/send boundaries replaced. Cover:

- a stale restore containing one unrelated processed source while an older policy or capacity obligation
  is absent;
- partial restores retaining only source rows, only capacity evidence, only terminal rows, or only cap
  events;
- a database populated by the old unsafe replay before upgrade;
- below-minimum and nonpositive policy decisions plus refund and quarantine capacity holds;
- fee, minimum, maximum, destination, quarantine-account and cap drift;
- multiple pages, equal timestamps, more obligations than each worker limit, restart and duplicate replay;
- missing/corrupt/conflicting backup identity and restore manifests; and
- positive online-backup and copied DB+WAL restores.

For every incomplete case require startup refusal or explicit source-specific recovery holds, zero Nexus
and Solana transport, full integer liability, no inferred fee/reservation/terminal row, and no current-term
replacement authorization. For a verified restore require the original decision, destination, amount,
memo, fee and terms evidence exactly once.

#### Implementation constraints

- Do not use table non-emptiness, schema existence, a recent mtime, current configuration or source
  rediscovery as restore proof.
- Bind any restore manifest to deployment identity, database generation, both custody/query identities,
  complete lifecycle/cap/fee evidence and an independently retained integrity value.
- Do not add a manual latch-delete or dummy-row bootstrap bypass.
- Keep the existing empty-database latch as immediate containment until this stronger gate is accepted.

### Batch 2 — make all startup admission outcomes durable and truthful

**Priority: P1 operator safety.**

The current dashboard sees only the empty-database latch. Other startup failures can leave
`recovery_admission.status=not_held`, show a retained healthy ratio and report zero recovery issues even
though `main.run()` refused service. Replace absence-of-latch semantics with one durable admission state
owned by startup, for example `pending`, `held` and `complete`.

Persist a sanitized reason, attempt/start/update/completion timestamps, validated waterlines and the
admission/restore identity needed for audit. Set `pending` before external recovery reads, set `held` on
every failure that can be written safely, and set `complete` only after all recovery phases succeed.
Initialization and dashboard reads must never clear or advance it. If the state cannot be read, the
dashboard remains `unknown`.

#### Collected RED acceptance

- heartbeat missing/malformed/exception and zero checkpoint;
- terminal-provenance audit failure;
- Solana and Nexus incomplete/malformed scans, cap-window failure and reference-seed failure;
- empty, partial and verified restored databases;
- crash after `pending`, after each chain rebuild and immediately before/after `complete`;
- repeated startup, concurrent dashboard reads and database read/write failures; and
- retained healthy metrics from an earlier run.

For every non-complete state require the banner and `/api/issues` entry, unknown backing/open-obligation/
fee/cap totals, no “refunds continue” claim and zero poller starts. A dashboard result may call admission
complete only when the same read snapshot contains a valid durable `complete` record.

### Batch 3 — move invalid capacity rows outside automatic eligible FIFO

**Priority: P1 progress without weakening transport safety.**

Only transactionally validated frozen holds may participate in automatic global FIFO. When frozen intent
is malformed, source/terminal lifecycle conflicts, submission state is unknown, or another non-retryable
condition is found, atomically classify the row into a durable operator-action scheduler state. Retain the
original blob, full principal, diagnostics and non-sendability. Do not repair evidence from current terms.

Eligible FIFO remains global across refund and quarantine kinds. Impossible-under-current-cap rows retain
the existing special handling and become eligible again only after a sufficient reviewed cap change.

#### Collected RED acceptance

- malformed refund and quarantine rows ahead of valid same-kind and cross-kind work;
- source missing, source drift, opposing terminal and already-submitted conflicts;
- more operator-action rows than each worker limit;
- cap `0`, exact boundary, cap decrease/increase, rolling-window aging and restart;
- concurrent refund/quarantine workers;
- alert deduplication and durable issue visibility; and
- reviewed evidence-bound resolution of the blocked row.

Require each younger eligible frozen intent to submit exactly once. The blocked row must retain its source,
raw evidence, principal and diagnostics. No operator-action transition may release a pre-RPC/unknown
reservation, delete a source, invent a fee or authorize transport.

### Batch 4 — make the dashboard actually read-only and snapshot-consistent

**Priority: P2 hardening.**

`dashboard._ro_conn()` is read-only, but `api_summary()` calls state helpers that open ordinary writable
SQLite connections. Against a missing path, a summary read creates a database file. Route every dashboard
query through one read-only connection/transaction or dedicated read-only state API. Do not mix an
admission read from one snapshot with metrics and counts from later connections.

Acceptance:

- no database, WAL or SHM file is created or changed by any dashboard endpoint;
- missing/unreadable schema returns sanitized unknown values;
- a latch/admission transition concurrent with summary rendering cannot produce `not_held` plus healthy
  retained metrics; and
- repeated summary/issues/transaction reads leave a complete database dump byte-for-byte unchanged.

### Batch 5 — retain the existing separate release gates

After Batches 1–4, close the already documented fail-open heartbeat/chain identity gate and provide an
audited Solana hold-resolution protocol. Keep provider-v2 and optional receipts disabled until their own
wire-size, owner/schema, cost, create/readback and migration acceptance succeeds.

Only then run explicitly authorized target-infrastructure acceptance for provider pagination, authoritative
network/finality, Nexus completeness/reference/TLS, both bridge directions, accepted-but-unparsed outcomes,
durable-boundary crashes, backup/restore, total loss and operator rehearsal.

## Gate after every batch

1. Independently review final runtime functions and shared callers.
2. Run the new focused collected module, the complete suite and all CI isolation shards.
3. Run dependency consistency, byte compilation, local Markdown links, token-literal inventory and
   whitespace checks.
4. Record exact commit/tree, runtime/test SHA-256, commands and results.
5. Prove the real index and unrelated dirty/untracked work are unchanged.
6. Keep local, live, publication-CI and release decisions separate.
