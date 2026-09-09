"""Regression coverage for the durable Solana payout-cap reservation ledger.

These tests use a temporary SQLite database only; no chain RPC is invoked.
"""
from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from src import state_db


@contextmanager
def isolated_state(tmp_path):
    with patch.object(state_db, "DB_PATH", str(tmp_path / "state.db")):
        state_db.init_db()
        yield


def test_reservation_is_unique_and_counts_pending_capacity(tmp_path):
    with isolated_state(tmp_path):
        assert state_db.reserve_solana_payout_budget(
            obligation_id="nexus:credit-a:0", kind="nexus_payout", amount_usdc_units=60,
            cap_units=100,
        )
        assert not state_db.reserve_solana_payout_budget(
            obligation_id="nexus:credit-a:0", kind="nexus_payout", amount_usdc_units=60,
            cap_units=100,
        )
        assert not state_db.reserve_solana_payout_budget(
            obligation_id="nexus:credit-b:0", kind="nexus_payout", amount_usdc_units=50,
            cap_units=100,
        )

        assert state_db.payout_budget_used(86400) == 60
        with sqlite3.connect(state_db.DB_PATH) as conn:
            events = conn.execute(
                "SELECT obligation_id, event, amount_usdc_units FROM solana_payout_budget_events"
            ).fetchall()

    assert events == [("nexus:credit-a:0", "reserved", 60)]


def test_concurrent_reservations_cannot_oversubscribe_a_cap(tmp_path):
    with isolated_state(tmp_path):
        def reserve(index):
            return state_db.reserve_solana_payout_budget(
                obligation_id=f"nexus:credit-{index}:0", kind="nexus_payout",
                amount_usdc_units=60, cap_units=100,
            )

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(reserve, range(2)))

        assert sorted(results) == [False, True]
        assert state_db.payout_budget_used(86400) == 60


def test_submitted_and_confirmed_events_preserve_exact_obligation_identity(tmp_path):
    with isolated_state(tmp_path):
        obligation_id = "nexus:credit-a:7"
        assert state_db.reserve_solana_payout_budget(
            obligation_id=obligation_id, kind="nexus_payout", amount_usdc_units=60,
            cap_units=100,
        )
        assert state_db.record_solana_payout_submission(obligation_id, "solana-signature")
        assert state_db.settle_solana_payout_budget(
            obligation_id, "solana-signature", 60
        )
        assert not state_db.settle_solana_payout_budget(
            obligation_id, "another-signature", 60
        )

        with sqlite3.connect(state_db.DB_PATH) as conn:
            events = conn.execute(
                """SELECT event, signature, amount_usdc_units
                   FROM solana_payout_budget_events
                   WHERE obligation_id = ? ORDER BY id""",
                (obligation_id,),
            ).fetchall()

    assert events == [
        ("reserved", None, 60),
        ("submitted", "solana-signature", 60),
        ("confirmed", "solana-signature", 60),
    ]


@pytest.mark.parametrize("amount, cap", [(True, 100), (0, 100), (1, -1), (1, "100")])
def test_reservation_rejects_non_exact_budget_terms(tmp_path, amount, cap):
    with isolated_state(tmp_path), pytest.raises(ValueError):
        state_db.reserve_solana_payout_budget(
            obligation_id="nexus:credit-a:0", kind="nexus_payout",
            amount_usdc_units=amount, cap_units=cap,
        )
