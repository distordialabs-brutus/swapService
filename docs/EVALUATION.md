# swapService — Current Engineering Evaluation and Remediation Plan

## Independent re-evaluation — 2026-09-23

**Reviewed range:** `da79e0928c2dc7c39648734d9ad329637c87eae6..85030c890fa6f3bb7db97e068e5cf80827d21b28`.
**Verdict: release blocked.** The committed A/B/C repairs pass the complete offline gate and provide
meaningful safety while SQLite survives. They do not establish total-database-loss recovery of
unsent authorization: a wiped deployment can rediscover principal, return startup recovery as
complete, and authorize a different route or different refund terms. A fresh retry probe also
shows that one oldest malformed capacity hold safely prevents sends but indefinitely blocks a
later valid fitting hold, so the advertised eligible-FIFO retry has an operability exception.

This review changed documentation only. It did not change runtime/tests, stage the real index,
commit, push, access production credentials, call a live chain, or move funds. The September 22
review artifacts remain historical inputs; the complete September 23 evidence and commands are in
the [dated development review](DEVELOPMENT_REVIEW_2026-09-23.md).

The complete published `EVALUATION.md` snapshot replaced by this current issue register remains
available at the immutable
[reviewed source SHA](https://github.com/distordialabs-brutus/swapService/blob/85030c890fa6f3bb7db97e068e5cf80827d21b28/docs/EVALUATION.md).

## Architecture and verified progress

One process bridges one configured classic SPL token ↔ Nexus token pair. `config.SWAP_PAIR`
contains token/custody identity, independent decimals and fee terms. Gross conversion is 1:1 in
whole-token units before fees/rounding, not market pricing. Native SOL, Token-2022, arbitrary
chains and simultaneous pairs remain outside scope. Helius is a trusted primary provider; a
second attestor is not required. Exact amounts, success/finality and complete enumeration remain
application responsibilities.

| Area | Current implementation and acceptance boundary |
|---|---|
| A — disposition recovery, E-015/E-018 | Strict provenance parsing, conservative legacy-terminal migration, full-principal evidence holds, inferred-fee reversal and preserved proven cap spend. Atomic DDL/data rollback, in-place upgrade, online-backup and copied DB+WAL tests pass. This does not reconstruct an unsent B/C authorization that was lost with SQLite. |
| B — Solana input policy | Shared strict-integer minimum/maximum/decimal/fee classifier runs before destination routing. Below-minimum/nonpositive-output holds retain principal without fees. Frozen decisions survive restart **when the database survives**. |
| C — typed capacity holds | Durable typed outcomes, exact capacity diagnostics, liability/alert visibility, original-term retry and eligible FIFO are implemented for valid retained evidence. An individually impossible payout does not starve fitting work. A malformed oldest hold is fail-closed but can globally block a later valid fitting hold; see R-1b. Frozen retry requires retained intent evidence. |
| Ingestion/finality | Positive principal is durably retained; query/provider continuation is bound; unsupported/finality evidence is held; liability totals use one SQLite snapshot. Public waterlines pin behind unresolved sources. Source rediscovery alone does not reconstruct historical authorization. |
| Nexus identity/reconciliation, E-001–E-004/E-014 | Composite `(txid, contract_id)` identity, exact payout evidence, integer math and fail-closed backing controls remain. Automatic Nexus compensating transfers remain disabled; a narrow explicit operator protocol exists. |
| Optional receipts, E-016 | Durable outbox and independent positive-evidence/budget controls remain; production enablement is separately blocked pending cost/schema/target-chain acceptance. |
| Provider-v2 | Builder/validator and tests are committed, but registration, heartbeat, recovery and inspection still use v1. This is library-only implementation, not a default-v2 runtime migration. |

See [state machines](STATE_MACHINES.md) and the published
[historical A/B/C acceptance record](RECOVERY_INPUT_CAP_ACCEPTANCE.md). That tracked record documents
the original tested scope; the total-loss and scheduler qualifications in this evaluation are newer.

## Remaining findings, in repair order

### R-1 — High: lost unsent policy/cap intent can be reinterpreted after database loss

The real startup caller can return `recovery_complete=True` after total DB/WAL loss even though
no outgoing transaction exists from which to reconstruct an unsent hold. Incoming replay then
inserts a ready source with no policy evidence. Workers classify it using current configuration.

The parent independently reran both offline reviewer probes with dotenv loading and socket
connections disabled, temporary databases and mocked chain/send boundaries:

- A 1,100-unit deposit classified above max 1,000 froze a refund of 1,090 with fee 10 and was
  capacity-held. The public waterline correctly stayed behind the source. After database loss
  and a max increase to 2,000, startup returned complete and the deposit worker invoked the
  mocked Nexus debit for 1,100 instead of retaining the original refund obligation.
- With the oversized-refund route unchanged, losing the DB and changing fee/destination produced
  a mocked refund of 1,080 to a changed destination instead of the original 1,090/fee-10 intent.

The second probe isolates replay plus the refund worker; the first includes actual startup and
waterline callers. These are reproducible offline contract mutations, not claims of live loss or
of a demonstrated duplicate payment. Relevant paths: `startup_recovery.py:343-481,607-843`,
`state_db.py:1742-1777,2306-2375`, `solana_client.py:1049-1063,1329-1390` at the reviewed HEAD.

**Containment:** do not resume an existing deployment from an empty/recreated DB merely because
source history can be rediscovered. Restore verified frozen evidence from backup, or keep
processing paused pending reconciliation. This is a required operational restriction; current
runtime does not enforce the full restriction automatically.

**Exit:** either reconstruct exact historical authorization from durable evidence outside the
lost DB, or retain every affected rediscovered source as a quantified, visible, non-sendable
recovery hold. Test below-minimum/nonpositive policy holds and refund/quarantine cap holds through
DB/WAL loss, policy/fee/destination drift, multi-page replay and worker limits. Assert zero sends
without restored authorization, liability conservation and no inferred fee. Separately prove
verified backup restoration sends the original destination/output/memo/fee exactly once.

### R-1b — High operability: malformed oldest capacity evidence blocks later valid retries

The retry protocol correctly refuses malformed frozen evidence and retains all principal. However,
its global FIFO query still treats that unresolved row as the oldest eligible hold. A fresh real-worker
probe created two ordinary refund capacity holds, corrupted only the older hold's frozen JSON, released
the blocking budget, and ran the worker twice. Both runs returned zero; the valid younger 50-unit
refund remained `refund capacity held`, its attempt count increased from 1 to 3 with reason
`waiting behind older Solana payout capacity hold`, zero sends occurred, and the full 120-unit
liability remained. This is safe containment, but not progress or the claimed eligible-FIFO behavior.
The probe is session scratch only; its SHA-256 and exact output are recorded in the September 23 review.

Relevant code is `state_db.py:4158-4214,4770-4830` and
`solana_client.py:1289-1409`: loading the oldest hold returns `malformed_evidence`, while the later
valid prepare still selects that malformed source in the global oldest-hold query. The existing
suite covers malformed refusal, but not a younger fitting obligation behind it.

**Exit:** keep malformed/source-conflict/unknown-submission evidence non-sendable, but remove it from
automatic eligible FIFO after atomically promoting it to a distinct operator-action queue, or define
another durable scheduler disposition that cannot authorize transport. Add real refund and quarantine
worker tests with a malformed/conflicting oldest row, more rows than the worker limit, restart, alert
deduplication and later reviewed resolution. Require the younger valid original intent to submit
exactly once without deleting or reducing the blocked row's liability.

### R-2 — High deployment-safety gap: invalid registration is alert-only

`src/main.py:370-379` reports failed heartbeat validation or an exception but does not return;
execution can continue to pollers. The independent reviewer exercised that path offline. The
current validator checks readability/fields/parseable waterlines, not complete owner/address/
pair/terms identity. Authoritative network and freshness admission is also missing: known Solana
hostname/label checks exist, but custom endpoints are not checked against genesis/health/root
freshness, and Nexus network/sync/tip freshness is not an enforced startup gate.

**Exit:** add explicit fail-closed registration and authoritative chain-identity/freshness admission
before mutable startup/polling. Test mismatch, unavailable evidence, stale/unsynced nodes and
validator exceptions with zero poller/chain-write calls; validate semantics on intended nodes.
Do not equate a configured network label or a successful recovery mock with this gate.

### R-3 — High operability gate: non-capacity Solana holds lack audited resolution

Capacity-only holds can retry their retained original intent. Policy, recovery-evidence,
malformed-evidence, source/lifecycle-conflict and unknown-submission holds have no corresponding
audited Solana resolution command. Dashboard visibility is not a disposition protocol.
`nexus_transfer_operator.py` handles only an exact Nexus refund-hold family; actor strings do
not enforce distinct human approval roles.

**Do not follow** the direct-chain-transfer/manual-DB advice in `quarantine_viewer.py:409-418`.
It bypasses intent/cap/evidence protocols. The source text is flagged for repair, not changed in
this documentation-only review.

**Exit:** implement an evidence-bound operator protocol, or explicitly approve permanent retention
as policy. Require actor/rationale, competing-state checks, authoritative exact readback,
capacity accounting, atomic terminalization, replay/crash tests and no blind retries. If two-person
approval is required, enforce distinct identities rather than merely recording labels.

### R-4 — Publication gate: verify the new exact head independently of source-SHA history

[CI run 35755684698](https://github.com/distordialabs-brutus/swapService/actions/runs/35755684698)
for source SHA `85030c890fa6f3bb7db97e068e5cf80827d21b28` passed dependency, compile, Markdown,
full-suite and isolation steps, then
failed `git diff --check HEAD~1 HEAD`. Local reproduction reports 194 whitespace findings in
`docs/review_evidence/2026-09-15/committed-since-sept12.diff` and 2 in `dirty-config.diff`.
This is a historical result for that source SHA and a committed-artifact failure, not a failed
runtime test. It does not predict the result for a later documentation commit whose `HEAD~1..HEAD`
delta does not rewrite those raw forensic `.diff` bytes.

**Exit:** after the five review documents are staged, run the index-aware inventory and candidate
whitespace/link gates, then verify CI for the resulting exact publication SHA. Do not rewrite raw
forensic `.diff` bytes merely to repair the earlier source-SHA run; any future archival normalization
must be separately scoped and preserve provenance. The artifacts were not rewritten here.

### R-5 — Provider-v2 cutover remains a separate, blocked migration

`src/service_record.py` has no production importer. `ALLOW_LEGACY_PROVIDER_V1` is parsed but
inert; runtime v1 is not disabled by its false default. Immutable asset address, expected owner,
service ID and Nexus network settings do not currently protect registration/recovery callers.
The reviewer and parent measured the v2 fixture with `last_poll=0` at 1,448 bytes using the repository's
`service_record_size()` estimator, above its declared 1,024-byte budget. This is **not** proof of
the target node's exact encoded size limit; it blocks assuming the proposed record fits.

**Exit:** choose and verify a target-valid storage layout before any NXS-spending create, then
wire address-selected create/read/update, startup, heartbeat and recovery to one identity policy.
Enforce explicit legacy opt-in, exact owner/type/schema/service/pair/custody, monotonic terms,
secret-safe publication and agreement between published economics and executable policy. Test
multiple assets, name/address disagreement, readback delay, oversize rejection and migration on
the intended Nexus build. Provider-v2 is not a prerequisite to repairing R-1 in the existing
single-pair bridge; committing the library does not make it integrated.

## Fresh verification at the reviewed runtime — 2026-09-23

The reviewed runtime/test paths remained at the published HEAD hashes before and after execution.
The real index tree remained `a89d8904a200cafce86a5ecd002fa90978f2be13` and had no cached diff.

| Executed offline gate | Result |
|---|---|
| `.venv/bin/python -m pytest -q` | **565 passed, 77 subtests passed in 66.89s** |
| Recovery standalone | **35 passed, 52 subtests passed in 2.21s** |
| Recovery plus installed SDK boundary | **36 passed, 52 subtests passed in 2.62s** |
| Receipt/payout/Nexus-fee/SDK shard | **85 passed in 7.12s** |
| Provenance migration + terminal admission + deposit policy + capacity holds | **129 passed in 13.25s** |
| Legacy script/frozen-name gate | **5 passed in 1.41s** |
| Dependency consistency, byte compilation, Markdown links | Passed |
| Token-literal inventory | Passed; **274 active lines** |
| Working documentation whitespace | `git diff --check` passed |
| Two total-DB-loss probes | Both reproduced R-1; no live calls and not default-collected tests |
| Malformed-oldest capacity probe | Reproduced R-1b: **0 sends, 120 units retained, valid younger hold did not progress** |
| Source-SHA CI history | Run `35755684698` for `85030c8` **failed on committed historical-artifact whitespace**, not runtime tests; the future publication head is untested |

The green suite preserves evidence for local provenance migration, retained-database policy and valid
capacity retries; it does not close either fresh integration finding or any live-chain gate. Runtime
and test SHA-256 values, exact commands, probe hashes/output and the complete review-authored path list
are in the [September 23 review](DEVELOPMENT_REVIEW_2026-09-23.md). Earlier independent reviewer
artifacts remain only as excluded local worktree files under `docs/review_evidence/2026-09-22/`,
including `REEVALUATION.md`; they are not published links or dependencies of these five documents.

## Development and release sequence

1. **Contain/repair R-1 first**, adding collected end-to-end regression tests before runtime fixes.
   Keep A's safe migration and B/C's valid surviving-database controls; do not undo them.
2. Repair R-1b without releasing malformed/conflicting evidence to transport: separate operator-action
   holds from eligible automatic FIFO and prove later valid work progresses with liability conserved.
3. Close R-2 admission and R-3 audited resolution with independent caller-level review. For R-4,
   verify the exact five-document publication candidate and its resulting CI without changing the
   excluded raw forensic artifacts; neither whitespace nor a green suite closes R-1.
4. Keep provider-v2 and receipts disabled/unclaimed as runtime capabilities until their separate
   migration/cost gates pass. Preserve compatibility; no dependency upgrade is part of this review.
5. On explicitly approved Solana devnet/Nexus test infrastructure, run both directions, mixed
   decimals, provider pagination/concurrent arrivals, finality, exact readback, Nexus references,
   accepted-but-unparsed/timeout outcomes, durable-boundary crashes, backup/WAL and total-loss
   recovery. Rehearse alerts, holds, incident response, key rotation and TLS/session controls.
6. Re-review the final runtime identity, run the complete configured gate, then make a separate
   release decision. Production and real funds remain blocked; no live acceptance was performed.

The original [A/B/C implementation plan](plans/recovery-input-cap-repairs.md) remains the historical
implementation record. The executable follow-up is the
[September 23 recovery/retry plan](plans/2026-09-23-financial-recovery-follow-up.md).
