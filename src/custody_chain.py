"""Fail-closed admission against independently pinned immutable chain identities."""
from __future__ import annotations

import os
import time

import requests
from solders.hash import Hash

from . import config, nexus_client
from .custody_admission import AdmissionError


_HEX = frozenset("0123456789abcdef")


def _expected_solana_identity() -> str:
    solana = os.getenv("CUSTODY_SOLANA_GENESIS_HASH")
    if not solana:
        raise AdmissionError("custody chain identity configuration missing")
    try:
        valid_solana = solana == solana.strip() and str(Hash.from_string(solana)) == solana
    except Exception:
        valid_solana = False
    if not valid_solana:
        raise AdmissionError("custody chain identity configuration invalid")
    return solana


def _expected_nexus_identity() -> str:
    nexus = os.getenv("CUSTODY_NEXUS_GENESIS_HASH")
    if not nexus:
        raise AdmissionError("custody chain identity configuration missing")
    if (nexus != nexus.strip()
            or len(nexus) != 256
            or any(character not in _HEX for character in nexus)):
        raise AdmissionError("custody chain identity configuration invalid")
    return nexus


def _solana_rpc(method: str, params: list):
    url = config.RPC_URL
    if not url:
        raise AdmissionError("Solana RPC URL is missing")
    response = requests.post(
        url,
        json={"jsonrpc": "2.0", "id": "custody-tip", "method": method, "params": params},
        timeout=config.SOLANA_RPC_TIMEOUT_SEC,
        allow_redirects=False,
    )
    if response.status_code != 200:
        raise AdmissionError("Solana readiness HTTP request failed")
    body = response.json()
    if not isinstance(body, dict) or body.get("id") != "custody-tip" or "error" in body:
        raise AdmissionError("Solana readiness response invalid")
    return body["result"]


def _nexus_status(endpoint: str, *args: str) -> dict:
    code, output, _ = nexus_client._run(
        [config.NEXUS_CLI, endpoint, *args], timeout=config.NEXUS_CLI_TIMEOUT_SEC,
    )
    body = nexus_client._parse_json_lenient(output)
    if code != 0 or not isinstance(body, dict) or "error" in body:
        raise AdmissionError("Nexus readiness response invalid")
    result = body.get("result", body)
    if not isinstance(result, dict):
        raise AdmissionError("Nexus readiness response invalid")
    return result


def require_fresh_tips(*, now: int | None = None) -> None:
    """Require healthy primary RPCs and a recent finalized Solana and Nexus tip."""
    def fresh(timestamp):
        return type(timestamp) is int and -30 <= current - timestamp <= 900

    current = int(time.time()) if now is None else now
    try:
        if _solana_rpc("getHealth", []) != "ok":
            raise AdmissionError("Solana RPC is not healthy")
        slot = _solana_rpc("getSlot", [{"commitment": "finalized"}])
        if type(slot) is not int or slot <= 0 or not fresh(_solana_rpc("getBlockTime", [slot])):
            raise AdmissionError("Solana finalized tip is not fresh")
        info = _nexus_status("system/get/info")
        height = info.get("blocks")
        if (info.get("synchronized") is not True or info.get("syncing") is not False
                or type(height) is not int or height <= 0):
            raise AdmissionError("Nexus node is not synchronized")
        tip = _nexus_status("ledger/get/block", f"height={height}")
        if tip.get("height") != height or not fresh(tip.get("timestamp")):
            raise AdmissionError("Nexus tip is not fresh")
    except AdmissionError:
        raise
    except Exception as exc:
        raise AdmissionError("chain readiness query failed") from exc


def _solana_genesis_hash() -> str:
    try:
        response = requests.post(
            config.RPC_URL,
            json={
                "jsonrpc": "2.0",
                "id": "custody-chain-admission",
                "method": "getGenesisHash",
            },
            timeout=config.SOLANA_RPC_TIMEOUT_SEC,
        )
        response.raise_for_status()
        body = response.json()
        observed = body.get("result") if isinstance(body, dict) and "error" not in body else None
        if type(observed) is not str or str(Hash.from_string(observed)) != observed:
            raise ValueError
        return observed
    except Exception as exc:
        raise AdmissionError("Solana custody chain identity query failed") from exc


def _nexus_height_zero_hash() -> str:
    try:
        code, output, _error = nexus_client._run(
            [config.NEXUS_CLI, "ledger/get/blockhash", "height=0"],
            timeout=config.NEXUS_CLI_TIMEOUT_SEC,
        )
        if code != 0:
            raise ValueError
        body = nexus_client._parse_json_lenient(output)
        if isinstance(body, dict) and "error" not in body:
            body = body.get("result", body)
        if not isinstance(body, dict) or set(body) != {"hash"}:
            raise ValueError
        observed = body["hash"]
        if (type(observed) is not str or len(observed) != 256
                or any(character not in _HEX for character in observed)):
            raise ValueError
        return observed
    except Exception as exc:
        raise AdmissionError("Nexus custody chain identity query failed") from exc


def verify() -> None:
    """Require the configured endpoints to report the independently pinned chains.

    The Nexus height-zero identity check is part of admission unless disabled with
    CUSTODY_NEXUS_IDENTITY_CHECK=false; a disabled check skips the height-zero query
    entirely and the operator accepts responsibility for their LLL-TAO node version.
    """
    expected_solana = _expected_solana_identity()
    observed_solana = _solana_genesis_hash()
    if observed_solana != expected_solana:
        raise AdmissionError("Solana custody chain identity does not match approved deployment")
    if not config.CUSTODY_NEXUS_IDENTITY_CHECK:
        return
    expected_nexus = _expected_nexus_identity()
    observed_nexus = _nexus_height_zero_hash()
    if observed_nexus != expected_nexus:
        raise AdmissionError("Nexus custody chain identity does not match approved deployment")
