"""Offline recovery checks using LLL-TAO's detail-verbosity sigchain shape."""
import json
from dataclasses import replace
from unittest.mock import call, patch

import pytest

from src import config, nexus_client, startup_recovery, state_db


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
