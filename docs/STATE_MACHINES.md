# Swap Service State Machines

**Scope:** one configured classic SPL token ↔ Nexus token pair. This describes the current
tracked runtime plus explicitly identified local proposal boundaries. The offline execution gate
passes, but the financial-safety exits below remain open.
See [EVALUATION.md](EVALUATION.md) for current approval status. Historical dated notes and the full
previous diagrams are preserved in the [pre-repair snapshot](POST_CHANGE_REVIEW_2026-09-13_PRE_REPAIR_DOCUMENTATION.md).

## Safety boundaries

- Immutable token/custody identities and integer base units control financial decisions; symbols
  are display metadata. Existing database columns and status strings remain compatibility contracts.
- Each irreversible action persists its intent and budget before one submission. An uncertain result
  retains its liability and can resolve only through authoritative positive evidence or explicit
  operator disposition; it does not authorize automatic retry/refund.
- A returned signature or finalized status is not sufficient settlement proof. Match transaction
  success, source identity, vault/mint, exact recipient and output against frozen intent.
- Payout completion, fee booking and exact source removal commit atomically. Nexus source identity
  is `(txid, contract_id)` so settling one sibling cannot delete another.
- Incomplete recovery prevents the exposure-producing service loop from starting. Paused operation
  continues evidence-only resolution and existing refund/quarantine work, not new bridge exposure.

## Solana deposit enumeration and holds

```mermaid
flowchart TD
    Query[Bound network/vault/mint/commitment/range] --> Provider{Provider}
    Provider --> Helius[Trusted Helius full transaction page]
    Provider --> Core[Core signatures + exact transactions]
    Helius --> Validate[Validate full page and ordering]
    Core --> Validate
    Validate -->|incomplete or malformed enumeration| Stop[Hold cursor and public waterline]
    Validate -->|exact positive deposit| Policy{Admission policy}
    Policy -->|supported and finality satisfied| Queue[ready for processing]
    Policy -->|unsupported shape or finality pending| Hold[Durable per-signature hold]
    Queue --> Commit[Atomic rows + page evidence + continuation]
    Hold --> Commit
    Commit -->|continuation remains| Query
    Commit -->|range complete| Checkpoint[Evaluate conservative public waterline]
    Hold --> Replay[Fair bounded replay using frozen provenance]
    Replay -->|exact evidence and required finality| Queue
    Replay -->|still unresolved| Hold
```

Helius is trusted; core RPC is not a mandatory second attestor. Bind provider continuations to
network, vault, mint, commitment and fixed range/query parameters. Never reinterpret a Helius token
as a core `before` signature or resume it under changed query terms.

**Hold requirements:** retain the positive integer principal, exact evidence and immutable provenance.
Include held principal in unresolved backing liabilities; unknown amounts make authorization unhealthy.
Read hold and pending totals in one SQLite snapshot so concurrent promotion cannot omit principal.
Finalized configuration cannot retroactively bless evidence observed at confirmed commitment.
Validate the actual provider endpoint/network before every replay promotion, even when stored
evidence is already finalized and needs no new status request; missing/conflicting endpoints retain the hold.
Status queries obey provider batch limits, and replay cannot repeatedly select only a permanently
unsupported oldest window.

Ordinary classic SPL `transfer` and `transferChecked` share exact vault-balance validation. An outer
ATA creation and its matching inner initialization form one logical creation. Multiple incoming
sources or memos remain held when one payable source/destination cannot be established. Every positive
deposit enters the liability/fee/refund lifecycle; processing minimums must not silently filter history.

## Public waterlines and database loss

| Evidence | Permitted public waterline behavior |
|---|---|
| RPC error, malformed page, incomplete range or paused/no enumeration | Do not advance |
| In-progress provider continuation | Persist local page progress, not a completed range |
| Unprocessed or held Solana deposits | Pin behind the oldest unresolved source |
| Complete range, all obligations reconstructible | Advance only to the proven bound with safety margin |
| Proposed value does not exceed current value | Leave unchanged |
| Nexus processing-only pass | Never propose a checkpoint |
| Nexus mutable multi-page offset scan | Hold; positive rows do not establish complete enumeration |
| Empty live Nexus enumeration | Hold as unproven absence |

A durable **local** hold is not enough to pass an **external** recovery checkpoint: the local
record can disappear with the database. Either keep the public checkpoint behind it or demonstrate
complete reconstruction before startup succeeds. Do not initialize or move checkpoints to “now” to
bypass custody history. A policy/configuration mismatch must not silently reinterpret a saved cursor.

Nexus startup currently accepts an empty first bounded page while rejecting a later mutable-offset
page. The stricter live-poller rule differs; target-node completeness semantics remain an acceptance
gate, not something local fixtures prove.

## Solana token → Nexus token lifecycle

```mermaid
flowchart LR
    Ready[ready for processing] -->|persist reference and terms| Flight[debit in flight]
    Flight -->|returned txid recorded| Await[debited, awaiting confirmation]
    Flight -->|uncertain response| Unknown[debit unverified]
    Unknown -->|positive exact chain evidence| Await
    Await -->|exact confirmed Nexus contract| Done[debit_confirmed]
    Ready -->|invalid destination/memo or over cap| Refund[to be refunded]
    Ready -->|net output is not positive| Fees[processed, amount after fees <= 0]
    Refund -->|intent + cap reservation + one send| RefundWait[refund sent, awaiting confirmation]
    RefundWait -->|exact finalized transfer| Refunded[refund_confirmed]
    Refund -->|eligible source cannot be refunded| Quarantine[to be quarantined]
    Quarantine -->|intent + cap reservation + one send| QuarantineWait[quarantine sent, awaiting confirmation]
    QuarantineWait -->|exact finalized transfer| Quarantined[quarantine_confirmed]
```

The diagram omits nonterminal retry/hold loops, not their controls. Unknown Nexus mint outcomes
cannot be converted into a Solana refund merely because a bounded lookup is empty. Refund/quarantine
workers freeze the source, resolved token-account recipient, exact output and versioned memo before
submission; legacy rows without frozen terms remain held. Receipt publication never reopens this
bridge payout lifecycle.

## Nexus token → Solana token lifecycle

| Persisted state | Transition rule |
|---|---|
| `pending_receival` | Require complete mapping evidence and authoritative owner/token-account match |
| `ready for processing` | Successful liquidity/admission checks, then atomically freeze payout/fee terms and reserve cap |
| `payout cap held` | Retry admission when capacity is available; no submission occurred |
| `sending` | Single submission claim; ambiguous outcome remains held |
| `sig created, awaiting confirmations` | Require full finalized payout proof matching frozen terms |
| `processed` | Fee, exact terminal evidence and sibling-scoped source removal committed |
| `processed as fees` | Exact per-contract fee classification for the supported dust/minimum policy |
| `refund held for operator review` | No automatic Nexus debit; use the separate audited intent workflow |
| Legacy `collecting refund`, `refund pending`, `trade balance to be checked` | Retain compatibility, resolve/hold conservatively; no blind automatic refund |

Current outgoing payout memos carry `nexus_txid:<txid>:<contract_id>`. Automatic Nexus refund and
quarantine transfers remain disabled. The operator protocol is prepare → named authorization →
execute once → positive chain resolution → exact-source finalize. A submitted txid is immutable;
an unresolved reference-only scan cannot authorize a second debit.

## Recovery and rolling-cap accounting

Current Solana disposition memos are `swapService:v1:refund:<source_signature>` and
`swapService:v1:quarantine:<source_signature>`. Recovery requires exact finalized successful outbound
transfer evidence and the corresponding finalized incoming deposit: source token account, vault,
mint, amount, memo and authoritative chronology. A conflicting active Nexus mint lifecycle holds
reconstruction instead of erasing a possible mint-and-refund conflict. Missing source memos use the
same representation as normal persisted deposits.

**Current `814c0ae` containment:** when no disposition row survives, current-v1 chain-only evidence
restores actual cap spend and a full-principal `refund evidence held` / `quarantine evidence held`
source. It creates no terminal row or fee, remains in unresolved-liability accounting, appears on the
dashboard and is selected by neither send worker. Current-v1 still binds only kind and source signature;
without surviving pre-submission terms, operator review is required.

**Open migration bypass:** the pre-`814c0ae` recovery could manufacture a terminal disposition row and
fee from the same chain-only evidence. The current branch treats any matching existing terminal row as
surviving frozen intent, but the schema has no provenance field proving that the row existed before the
send. Consequently in-place upgrades and backups containing those legacy manufactured terminal rows
retain the inferred fee and no unresolved source liability. Unknown provenance must be migrated to the
same evidence-held state before this transition is safe. Genuine automatic terminal reconstruction
requires durable pre-submission provenance plus exact source, kind, recipient, output, fee/terms and
chain proof.

Confirmed cap consumption uses chain time, including refunds/quarantine before a newer heartbeat.
The whole rolling window must be covered even when the recovery checkpoint is newer. Known primary
payout identities preserve paid Nexus siblings; unpaid siblings remain independently recoverable.
Unknown, malformed, encoded, legacy or unattributed vault spending keeps recovery incomplete.

## Optional receipt publication state machine

```mermaid
flowchart LR
    Payout[Exact payout confirmed] -->|atomic obligation| Owner[awaiting_owner]
    Payout -->|payload construction failed; frozen evidence retained| Manual[manual_review]
    Owner -->|authenticated registration; first owner frozen| Pending[pending]
    Pending -->|matching owner + atomic NXS budget claim| Creating[creating]
    Creating -->|create identity recorded| Verifying[verifying]
    Creating -->|uncertain result| Creating
    Creating -->|later exact readback| Published[published]
    Verifying -->|exact unique owner/payload readback| Published
    Verifying -->|incomplete or ambiguous readback| Verifying
    Owner -->|malformed durable payload| Manual
    Pending -->|malformed durable payload| Manual
```

`receipt_contract.py` owns the immutable payload schema and deterministic name. The database still
independently binds receipt fields to the exact completed payout. Owner lookup is not part of payout
finalization. A bound owner cannot be overwritten; mismatches hold publication. Malformed evidence
is retained for manual review, never silently discarded or published.

`creating` is a one-shot boundary: restart reads back and never blindly recreates. Its NXS budget
reservation remains charged across unknown outcomes. Production still rejects receipt enablement
pending live cost, indexing/readback and registration-migration acceptance. Existing fixed-field v1
records cannot gain a receipt schema through a heartbeat update.

## Durable stores and monitoring

| Store | Authority |
|---|---|
| Four `*_sigs` lifecycle tables | Solana source obligations and terminal evidence; evidence-held current-v1 rows remain in `unprocessed_sigs` |
| Four `*_txids` lifecycle tables | Composite Nexus source obligations and terminal evidence |
| Provider cursor/event tables | Bound page continuation and completion evidence |
| `solana_deposit_holds` | Unresolved principal, evidence, provenance and replay state |
| `solana_payout_budget_events` | Per-obligation reserved/submitted/confirmed/released cap accounting |
| `nexus_transfer_intents` / audit events | Immutable operator disposition and attribution |
| `swap_receipts` / `receipt_nxs_budget_events` | Publication obligation and NXS reservation |
| `fee_entries` | Authoritative integer fee journal |

SQLite uses WAL. Use `state_db.payout_budget_used(86400)` for rolling usage rather than summing one
ledger by hand. Inspect unresolved lifecycle rows, holds, manual-review receipts and unresolved cap
reservations together. Primary cap refusal has a durable dashboard-visible state; disposition cap
refusal currently retains generic source states and structured diagnostics.

Frozen compatibility examples include `reservations.kind=usdc_to_usdd_debit`, the
`usdc_send:<txid>:<contract_id>` attempt key, legacy fee/table columns and existing status strings.
Do not rename or delete them as cosmetic cleanup while old databases may contain active obligations.

For settings/timeouts see [CONFIG.md](../CONFIG.md); for operator procedures see
[SETUP.md](../SETUP.md) and [SECURITY.md](SECURITY.md). The runtime entrypoints are
`poll_solana_deposits`, `poll_nexus_deposits`, `process_unprocessed_txids`,
`check_unconfirmed_debits`, and `perform_startup_recovery` in their respective `src/` modules.

## 2026-09-15 safety-architecture addendum

The state diagrams above remain the committed intended architecture, with these reviewed
qualifications:

1. **Disposition recovery is not yet intent-complete.** Current-v1 refund/quarantine memos bind kind
   and source signature but not frozen output, fee or terms revision. After database loss, exact
   finalized transfer evidence may restore actual rolling-cap spend, but must not by itself authorize
   terminal source removal or classify `source - payout` as fee. Retain a manual-review liability
   until frozen intent survives or a new versioned on-chain identity proves it.
2. **Solana minimum classification is missing after ingestion.** Durable ingestion must continue to
   admit every positive custody delta. Before the `debit in flight` transition, a shared
   live/recovery classifier must apply `MIN_DEPOSIT_SOLANA_UNITS` and the published micro policy.
   Current positive-net below-minimum deposits can reach the Nexus debit boundary.
3. **Disposition cap refusal needs a state.** Capacity exhaustion must persist a distinct retryable
   cap-held state and exact needed/used/cap evidence. Evidence conflicts require a different manual
   hold. A generic ready state plus a log is not an operational safety control.
4. **Provider-v2 remains outside this runtime state machine.** The dirty builder has no registration,
   heartbeat, startup-recovery or waterline caller. Until address-based read/update, exact owner and
   immutable-record validation, monotonic terms updates, secret-safe publication and explicit v1
   fallback are integrated and target-tested, v1 remains the actual runtime contract and v2 remains
   a non-deployable candidate.

See [the full 2026-09-15 review](DEVELOPMENT_REVIEW_2026-09-15.md) for probes, hashes and executable
repair exits. Production and real-fund admission remain hard-blocked.

## 2026-09-16 verification note

Tracked runtime did not change after the September 15 source baseline. The real index still excludes
the dirty provider-v2 proposal, and all paths in the September 15 runtime manifest match. Fresh focused
execution continues to reproduce each qualification above: arbitrary-shortfall v1 recovery can
terminalize a fee, a below-minimum Solana source can reach the Nexus debit boundary, and disposition
cap refusal retains only its generic source state. The isolated v2 library still publishes unenforced
micro percentages and permits a configured secret as a public URL substring.

The full shared-tree suite and configured focused shards remain green; that verifies execution and
isolation, not these architectural exits. See the
[full 2026-09-16 review](DEVELOPMENT_REVIEW_2026-09-16.md). No live-chain acceptance ran.

## 2026-09-17 unresolved-transition clarification

No tracked runtime changed after the preceding note. The following are required transition contracts,
not descriptions of current behavior:

1. **Chain-only current-v1 disposition recovery must not enter a terminal state.** Positive transfer
   evidence may append actual rolling-cap spend, but without frozen intent the source transitions to a
   quantified `manual_review`/unresolved-liability state. It must not enter `refund_confirmed` or
   `quarantine_confirmed`, delete the source obligation or derive a fee from an unexplained shortfall.
   Exact surviving frozen intent or a new pre-submission evidence version is the only automatic path
   from recovered chain evidence to a terminal disposition.
2. **Durable ingestion and economic admission are separate transitions.** Every positive custody delta
   still enters durable state. Before `debit in flight`, one shared classifier must produce an explicit
   below-minimum, boundary or payable outcome using exact integer terms. Live processing and recovery
   consume the same result; ingestion never filters history to enforce economic policy.
3. **Capacity refusal is a state, not a failed claim.** Refund and quarantine preparation must
   atomically persist a typed retryable cap hold containing obligation identity and exact
   needed/used/cap units. Capacity release may return that same obligation to preparation after
   restart. Evidence conflict and lifecycle conflict remain separate manual-review states, and every
   hold transition occurs before any transport send.

The currently collected recovery and cap tests accept the old terminal-fee and generic-state
behaviors, while no collected real-worker test enforces the input threshold matrix. Those tests must
be replaced or extended with the transition contracts above. See the
[full 2026-09-17 review](DEVELOPMENT_REVIEW_2026-09-17.md). Production and real-fund admission remain
hard-blocked.

## 2026-09-21 transition update

`814c0ae` implements the evidence-held transition for a fresh database reconstruction, so the first
September 17 contract is now partly current behavior. Its safe branch is:

```text
current-v1 chain evidence + no surviving disposition row
  → exact observed cap spend
  → full-principal evidence hold
  → no fee, no terminal row, no automatic send
```

The transition is not upgrade-complete. A matching existing terminal disposition row follows the
frozen-intent path regardless of whether it was written before submission or manufactured by the
pre-repair recovery. Add immutable intent provenance and an in-place/backup migration:

```text
existing terminal row + proven pre-submission provenance + exact chain match
  → terminal confirmation
existing terminal row + missing/legacy/recovery-only provenance
  → exact observed cap spend + evidence hold + no inferred fee
```

After that P0 migration, retain the other two September 17 contracts unchanged: shared exact input
classification before Nexus transport, then typed durable cap holds before any refund/quarantine
transport. The [full 2026-09-21 review](DEVELOPMENT_REVIEW_2026-09-21.md) specifies executable exits.
