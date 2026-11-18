"""Offline recovery checks using LLL-TAO's detail-verbosity sigchain shape."""
import json
from dataclasses import replace
from unittest.mock import call, patch

import pytest

from src import balance_reconciler, config, main, nexus_client, startup_recovery, state_db, swap_nexus


TREASURY = "TREASURY"
GENESIS = "a1" * 32
ADDRESS = f"address={TREASURY}"
LOOKUP = "register/get/finance:account"
HISTORY = "ledger/list/transactions"


def txid(sequence):
    return f"{sequence + 1:0128x}"


def credit(contract_id=0, *, to: str | None = TREASURY, amount: int | str = 3):
    return {"id": contract_id, "OP": "CREDIT", "from": {"address": "sender"},
            "to": {"address": to}, "amount": amount}


def sigchain(count, *, root_contracts=None):
    return [
        {"txid": txid(sequence), "genesis": GENESIS, "sequence": sequence,
         "prevhash": txid(sequence - 1), "timestamp": 100, "confirmations": 10,
         "contracts": (
             root_contracts if root_contracts is not None else
             [{"id": 0, "OP": "CREATE", "address": TREASURY}]
         ) if sequence == 0 else [{"id": 0, "OP": "WRITE", "address": "heartbeat"}]}
        for sequence in range(count - 1, -1, -1)
    ]


def reply(value, wrapped=False):
    return 0, json.dumps({"result": value, "info": {}} if wrapped else value), ""


TOKEN = "token-register"


def test_first_start_proves_no_mints_and_clears_exposure_pause(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(state_db, "DB_PATH", str(path))
    state_db.init_db()
    history = sigchain(135, root_contracts=[{"id": 0, "OP": "CREATE", "address": TOKEN}])
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, register_address=TOKEN))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TOKEN, "owner": GENESIS}, wrapped=True), reply(history, wrapped=True),
    ]) as run:
        result = balance_reconciler.run_balance_reconciliation()
    assert result["healthy"] is True, result
    assert result["checked_addresses"] == 0
    assert result["empty_mint_history_verified"] is True
    assert main.update_reconciliation_exposure_pause(True, result) is False
    assert [c.args[0][1] for c in run.call_args_list] == ["register/get/finance:token", HISTORY]
    assert not any(a.startswith("offset=") for a in run.call_args.args[0])


@pytest.mark.parametrize("fault", ["unmatched", "unconfirmed", "wrong_owner", "broken_link", "truncated"])
def test_empty_local_database_never_hides_remote_mints_or_incomplete_history(tmp_path, monkeypatch, fault):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "fresh.db"))
    state_db.init_db()
    history = sigchain(5001 if fault == "truncated" else 135,
                       root_contracts=[{"id": 0, "OP": "CREATE", "address": TOKEN}])
    index = 0 if fault == "unconfirmed" else 110
    history[index]["contracts"] = [{"id": 0, "OP": "DEBIT", "from": {"address": TOKEN},
                                    "to": {"address": "recipient"}, "amount": "3.25", "reference": 99}]
    if fault == "unconfirmed":
        history[index].pop("confirmations")
    if fault == "broken_link":
        history[99]["prevhash"] = "ff" * 64
    owner = "b2" * 32 if fault == "wrong_owner" else GENESIS
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, register_address=TOKEN))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TOKEN, "owner": owner}, wrapped=True), reply(history, wrapped=True),
    ]) as run:
        result = balance_reconciler.run_balance_reconciliation()
    assert result["healthy"] is False, result
    assert result["empty_mint_history_verified"] is False
    assert run.call_count == 2
    if fault in {"unmatched", "unconfirmed"}:
        assert result["discrepancies"][0]["account"] == "recipient"
    else:
        assert any("history incomplete" in reason for reason in result["incomplete_reasons"])


def test_production_reconciliation_matches_completed_mint_past_row_100(tmp_path, monkeypatch):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "complete.db"))
    state_db.init_db()
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, register_address=TOKEN))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_TRANSFER_MIN_CONFIRMATIONS", 10)
    history = sigchain(135, root_contracts=[{"id": 0, "OP": "CREATE", "address": TOKEN}])
    mint = history[110]
    mint["contracts"] = [{"id": 0, "OP": "DEBIT", "from": {"address": TOKEN},
                          "to": {"address": "recipient"}, "amount": "1", "reference": 99}]
    units = 10**pair.nexus.decimals
    state_db.mark_processed_sig(
        "source-sig", 100, 2_000_000, mint["txid"], 0.0, "debit_confirmed", 99,
        amount_usdd_units=units, nexus_destination="recipient", memo="nexus:recipient", contract_id=0,
    )
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TOKEN, "owner": GENESIS}, wrapped=True), reply(history, wrapped=True),
    ]):
        result = balance_reconciler.run_balance_reconciliation()
    assert result["healthy"] is True, result
    assert result["checked_addresses"] == 1
    assert not result["empty_mint_history_verified"]


def test_production_backing_reads_wrapped_supply(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    with patch.object(nexus_client, "_run", return_value=reply({"currentsupply": "1.25"}, wrapped=True)):
        assert nexus_client.get_circulating_nexus_units() == 125 * 10**(config.NEXUS_TOKEN_DECIMALS - 2)


def test_production_mint_preserves_wrapped_txid_and_uses_pinned_register(monkeypatch):
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, register_address=TOKEN))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_PIN", "offline-test")
    with patch.object(nexus_client, "_run", return_value=reply({"txid": txid(2)}, wrapped=True)) as run:
        assert nexus_client.debit_nexus_token_with_txid("recipient", 1_000_000, 99) == (True, txid(2))
    assert f"from={TOKEN}" in run.call_args.args[0]


@pytest.mark.parametrize("case", ["confirmed", "shallow", "duplicate"])
def test_interrupted_mint_uses_linked_evidence_then_exact_txid(tmp_path, monkeypatch, case):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "interrupted.db"))
    state_db.init_db()
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, register_address=TOKEN))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_TRANSFER_MIN_CONFIRMATIONS", 10)
    units = 10**pair.nexus.decimals
    state_db.add_unprocessed_sig("source-sig", 100, "nexus:recipient", "sender", 2_000_000,
                                 "debit in flight", None)
    state_db.set_unprocessed_sig_debit_intent("source-sig", 99, units)
    history = sigchain(135, root_contracts=[{"id": 0, "OP": "CREATE", "address": TOKEN}])
    mint = history[110]
    term = {"id": 0, "OP": "DEBIT", "from": {"address": TOKEN},
            "to": {"address": "recipient"}, "amount": 1.0, "reference": 99}
    mint["contracts"] = [term]
    if case == "shallow":
        mint["confirmations"] = 9
    if case == "duplicate":
        history[0]["contracts"] = [term]
        history[0].pop("confirmations")

    replies = [reply({"address": TOKEN, "owner": GENESIS}, wrapped=True), reply(history, wrapped=True)]
    if case == "confirmed":
        replies.append(reply(mint, wrapped=True))
    with patch.object(nexus_client, "_run", side_effect=replies) as run:
        resolved = nexus_client.resolve_unverified_debits()
        if case == "confirmed":
            assert resolved == 1
            assert nexus_client.check_unconfirmed_debits(10, 8) == 1
            assert run.call_args.args[0][1:] == ["ledger/get/transaction", f"txid={mint['txid']}"]
        else:
            assert resolved == 0
            assert state_db.get_sigs_pending_debit_verification(nexus_client.DEBIT_UNVERIFIED_STATUSES)
    assert run.call_count == (3 if case == "confirmed" else 2)


def test_restart_accepts_a_pending_pinned_heartbeat_but_not_a_pending_credit(tmp_path, monkeypatch):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "idle.db"))
    state_db.init_db()
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, treasury_account=TREASURY))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_HEARTBEAT_ASSET_ADDRESS", "heartbeat")
    history = sigchain(3)
    history[0].pop("confirmations")
    history[0]["contracts"].append({"id": 1, "OP": "FEE"})
    owner = reply({"address": TREASURY, "owner": GENESIS})
    with patch.object(nexus_client, "_run", side_effect=[owner, reply(history)]):
        result = startup_recovery._rebuild_nexus_from_waterline(1)
    assert result["recovery_complete"] is True, result
    history[0]["contracts"] = [credit()]
    with patch.object(nexus_client, "_run", side_effect=[owner, reply(history)]):
        result = startup_recovery._rebuild_nexus_from_waterline(1)
    assert result["recovery_complete"] is False


def test_known_mint_txid_does_not_require_reference_history(tmp_path, monkeypatch):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "known.db"))
    state_db.init_db()
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, register_address=TOKEN))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_TRANSFER_MIN_CONFIRMATIONS", 10)
    mint = {"txid": txid(2), "confirmations": 10, "contracts": [
        {"id": 0, "OP": "DEBIT", "from": {"address": TOKEN}, "to": {"address": "recipient"},
         "amount": "1", "reference": 99},
    ]}
    state_db.add_unprocessed_sig("source-sig", 100, "nexus:recipient", "sender", 2_000_000,
                                 "debit in flight", mint["txid"])
    state_db.set_unprocessed_sig_debit_intent("source-sig", 99, 10**pair.nexus.decimals)
    with patch.object(nexus_client, "_run", return_value=reply(mint, wrapped=True)) as run:
        assert nexus_client.resolve_unverified_debits() == 0
        assert nexus_client.check_unconfirmed_debits(10, 8) == 1
    assert run.call_args.args[0][1:] == ["ledger/get/transaction", f"txid={mint['txid']}"]
    assert run.call_count == 1
    assert state_db.is_processed_sig("source-sig")


def test_slow_mint_confirmation_does_not_starve_a_later_row(tmp_path, monkeypatch):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "slow.db"))
    state_db.init_db()
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(nexus_client, "_mint_confirmation_cursor", None)
    for i in range(2):
        state_db.add_unprocessed_sig(str(i), 100, "nexus:recipient", "sender", 2_000_000,
                                     "debited, awaiting confirmation", txid(i))
        state_db.set_unprocessed_sig_debit_intent(str(i), i + 1, 1_000_000)
    now = [0.0]
    def lookup(cmd, *, timeout):
        assert 0 < timeout <= 3
        now[0] += 3
        return 1, "", "fixture timeout"
    monkeypatch.setattr(nexus_client.time, "monotonic", lambda: now[0])
    with patch.object(nexus_client, "_run", side_effect=lookup) as run:
        assert nexus_client.check_unconfirmed_debits(10, 3) == 0
        assert nexus_client.check_unconfirmed_debits(10, 3) == 0
    assert [c.args[0][-1] for c in run.call_args_list] == [f"txid={txid(0)}", f"txid={txid(1)}"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_recovery_reads_200_linked_rows_in_one_history_request(wrapped):
    history = sigchain(200)
    # Equal timestamps straddle the former 100-row boundary and the inclusive waterline.
    history[99]["contracts"] = [credit()]
    history[100]["contracts"] = [credit(), credit(1), credit(2, to="someone-else")]
    history[-1]["timestamp"] = 98
    history[-2]["timestamp"] = 99
    history[-2]["contracts"] = [credit()]
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}, wrapped), reply(history, wrapped),
    ]) as run:
        scan = nexus_client.fetch_deposits_since(TREASURY, 100, max_pages=2)

    assert scan.complete
    assert scan.deposits == history[99:101]
    assert run.call_args_list == [
        call([config.NEXUS_CLI, LOOKUP, ADDRESS], timeout=config.NEXUS_CLI_TIMEOUT_SEC),
        call([config.NEXUS_CLI, HISTORY, f"genesis={GENESIS}", "verbose=detail", "order=desc",
              "limit=201"], timeout=config.NEXUS_CLI_TIMEOUT_SEC),
    ]


@pytest.mark.parametrize("broken", [False, True])
def test_production_poll_applies_only_complete_linked_history(tmp_path, monkeypatch, broken):
    history = sigchain(205)
    for index, tx in enumerate(history):
        tx["timestamp"] = 1_000 - index
    history[101]["contracts"] = [credit(), credit(1)]
    if broken:
        history.pop(102)
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, treasury_account=TREASURY))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "HEARTBEAT_WATERLINE_ENABLED", True)
    monkeypatch.setattr(config, "HEARTBEAT_WATERLINE_SAFETY_SEC", 3)
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "live.db"))
    state_db.init_db()
    nexus_field, solana_field = nexus_client.heartbeat_waterline_field_names()
    monkeypatch.setattr(nexus_client, "get_heartbeat_asset", lambda: {nexus_field: 800, solana_field: 800})
    monkeypatch.setattr(nexus_client, "get_account_info", lambda address: {"owner": "b2" * 32})
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}, wrapped=True), reply(history, wrapped=True),
    ]) as run:
        swap_nexus.poll_nexus_deposits()
    assert [c.args[0][1] for c in run.call_args_list] == [LOOKUP, HISTORY]
    assert not any(arg.startswith("offset=") for arg in run.call_args.args[0])
    rows = state_db.get_unprocessed_txids_as_dicts()
    if broken:
        assert rows == []
        assert state_db.get_proposed_nexus_waterline() is None
    else:
        assert {(row["txid"], row["contract_id"]) for row in rows} == {(txid(103), 0), (txid(103), 1)}
        assert state_db.get_proposed_nexus_waterline() == 896


@pytest.mark.parametrize("pending_credit", [False, True])
def test_production_poll_can_ingest_behind_unconfirmed_head(tmp_path, monkeypatch, pending_credit):
    history = sigchain(3)
    history[0].pop("confirmations")  # LLL-TAO omits this and blockhash for mempool rows.
    if pending_credit:
        history[0]["contracts"] = [credit()]
    history[1]["contracts"] = [credit()]
    history[1]["timestamp"] = history[0]["timestamp"] = 900
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, treasury_account=TREASURY))
    monkeypatch.setattr(config, "SWAP_PAIR", pair)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_TRANSFER_MIN_CONFIRMATIONS", 10)
    monkeypatch.setattr(config, "HEARTBEAT_WATERLINE_ENABLED", True)
    monkeypatch.setattr(config, "HEARTBEAT_WATERLINE_SAFETY_SEC", 3)
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "live.db"))
    state_db.init_db()
    nexus_field, solana_field = nexus_client.heartbeat_waterline_field_names()
    monkeypatch.setattr(nexus_client, "get_heartbeat_asset", lambda: {nexus_field: 800, solana_field: 800})
    monkeypatch.setattr(nexus_client, "get_account_info", lambda address: {"owner": "b2" * 32})
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}), reply(history),
    ]):
        swap_nexus.poll_nexus_deposits()
    assert {row["txid"] for row in state_db.get_unprocessed_txids_as_dicts()} == {txid(1)}
    assert state_db.get_proposed_nexus_waterline() == (None if pending_credit else 897)


def test_recovery_can_prove_no_deposits_from_a_linked_history():
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}), reply(sigchain(1)),
    ]):
        scan = nexus_client.fetch_deposits_since(TREASURY, 100)
    assert scan == nexus_client.DepositScan([], True)


@pytest.mark.parametrize(("count", "reason"), [(201, "pagination_truncated"), (202, "pagination_truncated")])
def test_recovery_discards_every_row_at_the_query_cap(count, reason):
    history = sigchain(count)
    history[0]["contracts"] = [credit()]
    # An old timestamp in a capped response is not proof of completeness.
    history[-1]["timestamp"] = 99
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}), reply(history),
    ]) as run:
        scan = nexus_client.fetch_deposits_since(TREASURY, 100, max_pages=2)
    assert scan == nexus_client.DepositScan([], False, reason)
    assert run.call_count == 2


@pytest.mark.parametrize(("alter", "reason"), [
    (lambda rows: rows.clear(), "invalid_sigchain_range"),
    (lambda rows: rows.pop(), "invalid_sigchain_range"),
    (lambda rows: rows.pop(1), "invalid_sigchain_range"),
    (lambda rows: rows[1].update(txid=rows[0]["txid"]), "invalid_sigchain_range"),
    (lambda rows: rows[1].update(genesis="b" * 64), "invalid_sigchain_range"),
    (lambda rows: rows[-1].update(timestamp=101), "invalid_sigchain_timestamp_order"),
    (lambda rows: rows[0].pop("confirmations"), "invalid_confirmations"),
    (lambda rows: rows[0].update(confirmations=0), "invalid_confirmations"),
    (lambda rows: rows[-1]["contracts"][0].update(address="different-treasury"), "treasury_creation_unproven"),
    (lambda rows: rows[1].update(contracts=[]), "invalid_contracts"),
    (lambda rows: rows[1]["contracts"][0].update(OP="credit"), "invalid_contract"),
    (lambda rows: rows[1]["contracts"].append({"id": 1, "OP": "TRANSFER", "address": TREASURY}),
     "treasury_ownership_changed"),
    (lambda rows: rows[1]["contracts"].append({"id": 1, "OP": "CLAIM", "address": TREASURY}),
     "treasury_ownership_changed"),
    (lambda rows: rows[1]["contracts"].append(credit(0)), "invalid_contract_id"),
    (lambda rows: rows[1]["contracts"].append(credit(1, amount="3.0000001")), "invalid_credit_amount"),
    (lambda rows: rows[1]["contracts"].append(credit(1, to=None)), "invalid_credit_destination"),
])
def test_recovery_fails_closed_on_unproved_sigchain_or_credit(alter, reason):
    history = sigchain(3)
    history[1]["contracts"] = [credit()]
    alter(history)
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}), reply(history),
    ]):
        scan = nexus_client.fetch_deposits_since(TREASURY, 100)
    assert scan == nexus_client.DepositScan([], False, reason)


@pytest.mark.parametrize(("response", "reason"), [
    (TimeoutError("timeout"), "exception"),
    ((1, "[]", "node failed"), "cli_error"),
    ((0, "[]\ntrailing data", ""), "invalid_response"),
    (reply({"error": {"code": -108}, "result": []}), "invalid_response"),
])
def test_recovery_does_not_fall_back_on_history_transport_failure(response, reason):
    with patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}), response,
    ]) as run:
        scan = nexus_client.fetch_deposits_since(TREASURY, 100)
    assert scan == nexus_client.DepositScan([], False, reason)
    assert run.call_count == 2


def test_recovery_requires_lookup_to_resolve_the_exact_treasury():
    with patch.object(nexus_client, "_run", return_value=reply({
        "address": "some-other-address", "owner": GENESIS,
    })) as run:
        scan = nexus_client.fetch_deposits_since(TREASURY, 100)
    assert scan == nexus_client.DepositScan([], False, "treasury_owner_unproven")
    run.assert_called_once()


@pytest.mark.parametrize("max_pages", [True, 0, 51, "50"])
def test_recovery_never_executes_an_invalid_history_budget(max_pages):
    with patch.object(nexus_client, "_run") as run:
        scan = nexus_client.fetch_deposits_since(TREASURY, 100, max_pages=max_pages)
    assert scan == nexus_client.DepositScan([], False, "invalid_history_budget")
    run.assert_not_called()


def test_truncated_real_producer_does_not_touch_recovery_database(tmp_path):
    history = sigchain(5001)
    history[0]["contracts"] = [credit()]
    path = tmp_path / "must-not-create.db"
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, treasury_account=TREASURY))
    with patch.object(config, "SWAP_PAIR", pair), patch.object(state_db, "DB_PATH", str(path)), patch.object(
        nexus_client, "_run", side_effect=[reply({"address": TREASURY, "owner": GENESIS}), reply(history)],
    ):
        summary = startup_recovery._rebuild_nexus_from_waterline(100)
    assert summary["error"] == "nexus_deposit_scan_incomplete:pagination_truncated"
    assert not summary["recovery_complete"]
    assert not path.exists()


def test_native_http_results_restore_sibling_deposits_past_100_rows(tmp_path):
    history = sigchain(102)
    history[100]["contracts"] = [credit(), credit(1)]
    pair = replace(config.SWAP_PAIR, nexus=replace(config.SWAP_PAIR.nexus, treasury_account=TREASURY))
    sender = {"address": "sender", "owner": "b2" * 32}
    with patch.object(config, "SWAP_PAIR", pair), patch.object(
        state_db, "DB_PATH", str(tmp_path / "recovery.db")
    ), patch.object(nexus_client, "_run", side_effect=[
        reply({"address": TREASURY, "owner": GENESIS}, wrapped=True),
        reply(history, wrapped=True), reply(sender, wrapped=True), reply(sender, wrapped=True),
    ]):
        state_db.init_db()
        summary = startup_recovery._rebuild_nexus_from_waterline(100)
        rows = state_db.get_unprocessed_txids_as_dicts()

    assert summary["recovery_complete"], summary
    assert {(row["txid"], row["contract_id"]) for row in rows} == {
        (txid(1), 0), (txid(1), 1),
    }
