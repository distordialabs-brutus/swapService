"""Fail-closed admission against independently pinned immutable chain identities."""
from __future__ import annotations

import os

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
