# Recovery, input policy and cap-hold implementation plan

**Status — 2026-09-22:** A, B and C are complete and independently accepted offline.
The final runtime review approved all repairs, including frozen cap retries, conflict liability
preservation and eligible-FIFO scheduling around impossible holds. Parent final verification:
**565 passed, 77 subtests passed**, with all configured shards and static/repository checks green.
No production, live-chain or real-funds approval is implied; changes remain unstaged/uncommitted.

The original requirements below remain the acceptance contract. See the
[acceptance report](../RECOVERY_INPUT_CAP_ACCEPTANCE.md) and linked independent review for evidence.

**Goal:** Complete offline recovery acceptance, enforce Solana deposit admission, and make disposition cap holds durable and observable.

**Architecture:** Preserve intent-first side effects and exact integer accounting. Recovery must never infer historical authorization from observed spend. A shared pure input policy must govern live/recovered deposits; typed cap outcomes must be persisted atomically with source state and surfaced through existing operator interfaces.

**Tech Stack:** Python, SQLite, pytest, existing Solana/Nexus adapters; offline temporary databases and transport stubs only.

## Boundaries

Starting HEAD: `a1f19b109681da693331583e30fa192ccee17d2d`. Preserve pre-existing `src/config.py`, `src/service_record.py`, `tests/test_service_record_v2.py` and September 15 raw diff artifacts. Do not stage, commit, push, enable receipts, upgrade dependencies, access credentials or send live transactions. Baseline/index hashes are in `/tmp/swap-repair-baseline-lqg08hyt/manifest.json` for this session. Use a disposable index for candidate-aware inventory verification.

## Batch A — recovery acceptance (offline accepted)

Files: `src/state_db.py`, `src/startup_recovery.py` if needed, `tests/test_recovery_safety.py`, focused new collected acceptance test module.

1. Reproduce actual legacy predecessor state, including its terminal/fee and cap rows; test in-place upgrade, SQLite online backup, DB+WAL restoration and idempotent restart.
2. Exercise genuine prepared/awaiting/confirmed provenance, absent/malformed/recovery-only provenance, conflicting source/recipient/output/signature/terms, and configuration change after submission.
3. Inject failure inside cap/fee/source/migration writes and verify atomic rollback/retry. Exercise the actual startup and confirmation entry points, not just a helper. Unknown historical evidence must be quantified, visible and non-sendable, and cannot authorize surplus.
4. For each discovered defect write and run a minimal red regression, fix production code, rerun green; preserve tests of already-correct behavior.
5. Run `.venv/bin/python -m pytest -q tests/test_recovery_safety.py tests/test_payout_budget.py tests/test_payout_review_regressions.py` plus new module. Independent spec and quality review must pass before Batch B.

**Implemented outcome:** strict exact-type/duplicate-key provenance validation; conservative
full-principal migration for absent, malformed, recovery-only and unknown provenance; preserved proven
cap spend; inferred-fee reversal; migration audit; atomic schema/data migration beginning under
`BEGIN IMMEDIATE`; in-place, online-backup and copied DB+WAL restore coverage. Final independent
whole-candidate acceptance is approved offline.

## Batch B — shared minimum-deposit classifier (implemented; independently approved in batch scope)

Files: `src/solana_client.py`, new pure policy module if appropriate, `src/state_db.py`, relevant recovery/public-terms caller, new default-collected policy integration tests.

1. Red test: real worker receives a positive-net source below configured minimum; require zero Nexus debit calls and a durable explicit disposition.
2. Implement pure strict-integer classification with exact frozen terms; use existing published economics rather than inventing new fees. Do not drop positive inputs from ingestion or silently consume the entire deposit as fees.
3. Test below/exact/above boundaries, unequal decimals, fees/rounding, invalid destination/memo, oversized deposits and non-positive output. Freeze/persist any policy decision needed to prevent restart or configuration change reclassifying an already-disposed source.
4. Live and recovered input must use the same decision boundary; previously submitted intents remain governed by frozen historical output, not new policy.
5. Prove public minimum/fee terms match the executable policy, and unsupported settings are not advertised as supported. No provider-v2 integration.
6. Focused and full test gate, independent spec then quality review, before Batch C.

**Implemented outcome:** one pure strict-integer min/max/decimal/flat-plus-basis-point policy is frozen
before destination routing for live and recovered inputs. Below-minimum and non-positive-output inputs
retain full principal in a non-sendable policy hold; exact boundaries are payable and above-maximum
keeps the established refund route. `MICRO_DEPOSIT_FEE_PCT` remains unused because no supported
percentage policy exists. Batch-scoped independent quality review approved; final candidate gate also passed.

## Batch C — typed disposition cap holds (offline accepted; review blockers repaired)

Files: `src/state_db.py`, `src/solana_client.py`, `src/dashboard.py`, existing alerts interface and default-collected tests.

1. Red real-worker test for both refund/quarantine: exhausted cap causes no send and a durable typed capacity hold with source/kind/needed/used/cap evidence.
2. Replace ambiguous reservation outcomes with typed results while preserving fail-closed callers. Distinguish source conflict, opposing lifecycle, malformed evidence, capacity refusal and DB failure.
3. Make state/budget/hold writes atomic. Add safe fair retry of capacity holds after capacity ages out; never retry unknown submitted outcomes.
4. Dashboard/API and alerts expose non-secret actionable diagnostics. Alert failure cannot remove a hold or trigger a send; avoid repeated alert storms.
5. Test restart, cap release/aging, concurrency, conflicting lifecycle, rollback, exact single send and liability conservation.
6. Independent spec then quality review.

**Implemented outcome:** closed typed preparation outcomes; atomic source/hold/reservation writes;
full-principal holds with needed/used/cap evidence; dashboard/API and alert visibility; eligible FIFO
retry under current capacity using the original frozen terms. The `current_cap_too_low` outcome
retains impossible payouts without starving fitting work, including beyond worker limits; conflict/malformed/database/submitted
states remain distinct and non-sendable. The initial spec review's frozen-term retry and orphaned-source
blockers now have real-worker regressions and passing implementer/parent focused runs. Final
independent closure review approved the integrated runtime.

## Final verification/documentation

Update `docs/EVALUATION.md`, `docs/STATE_MACHINES.md` and a repair acceptance report with actual commands/results and remaining external gates. Regenerate `docs/TOKEN_PAIR_LITERAL_INVENTORY.md` against the explicitly scoped candidate using disposable `GIT_INDEX_FILE`, never the real index. Execute complete pytest, recovery standalone/SDK and receipt/payout/Nexus-fee/SDK shards, `pip check`, compilation, Markdown links, inventory and whitespace. Independently review the final candidate and rerun affected/full tests after repairs. Confirm baseline unrelated-file hashes and real index are unchanged. Local acceptance does not approve real funds or replace devnet/testnet/operations acceptance.

**Final-gate status:** independent runtime review APPROVED; parent full suite 565 + 77 subtests;
configured shards, dependencies, compilation, links, inventory and whitespace passed. Reviewed runtime
hashes, real index and unrelated baseline files were verified unchanged. Historical counts remain
source-attributed in the acceptance report. Do not stage, commit, push, enable receipts/provider-v2, upgrade
dependencies or perform a live transaction as part of closing this plan.
