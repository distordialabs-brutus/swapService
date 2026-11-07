"""Durable operator alert delivery regressions.

Every alert is persisted to the state DB outbox before delivery, retried from
there within a budget and cooldown, dead-lettered when exhausted, and surfaced
to the operator dashboard.  None of this may silently lose an alert.
"""

import json
import sqlite3
import threading
import time
from typing import Optional

import pytest

from src import alerts, config, dashboard, state_db


class Clock:
    """Controllable wall clock so cooldowns can be exercised without sleeping."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _outbox_rows() -> list:
    conn = sqlite3.connect(state_db.DB_PATH)
    try:
        return conn.execute("SELECT * FROM alert_outbox").fetchall()
    finally:
        conn.close()


def _alert_row(alert_id: int) -> Optional[dict]:
    row = state_db.load_alert(alert_id)
    assert row is not None, f"alert row {alert_id} missing"
    return row


def _is_sent(alert_id: int) -> bool:
    row = state_db.load_alert(alert_id)
    return bool(row and row["status"] == state_db.ALERT_OUTBOX_SENT)


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(time, "time", clock)
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(config, "ALERT_WEBHOOK_URL", None)
    monkeypatch.setattr(config, "ALERT_COMMAND", "/bin/true")  # any channel enables delivery
    monkeypatch.setattr(config, "MAX_ALERT_ATTEMPTS", 2)
    monkeypatch.setattr(config, "ALERT_RETRY_COOLDOWN_SEC", 60)
    monkeypatch.setattr(alerts, "_last_sent", {})
    state_db.init_db()
    return clock


def test_alert_is_persisted_before_delivery(outbox, monkeypatch):
    """The outbox row must exist before any delivery thread is even started."""
    release = threading.Event()
    received = []

    def fake_deliver(payload, _release=release):
        received.append(payload)
        _release.wait(timeout=5)
        return True, None

    monkeypatch.setattr(alerts, "_deliver", fake_deliver)
    alerts.critical("vault_deficit", "deficit note", amount=7)

    assert wait_until(lambda: len(received) == 1)
    row = _alert_row(1)
    assert row["status"] == "pending"              # persisted, delivery still in flight
    assert row["event"] == "vault_deficit"
    assert row["level"] == "critical"
    assert json.loads(row["payload_json"])["fields"]["amount"] == 7

    release.set()
    assert wait_until(lambda: _is_sent(1))


def test_outbox_retries_failure_then_dead_letters(outbox, monkeypatch):
    """A failed channel must be retried inside its budget, then dead-lettered, once."""
    monkeypatch.setattr(alerts, "_deliver", lambda payload: (False, "webhook: ConnectionError"))
    alert_id = state_db.enqueue_alert("critical", "nexus_debit_held", "boom", "{}")

    delivered, abandoned = alerts.deliver_pending(limit=5)
    assert (delivered, abandoned) == (0, 0)          # first failure: still pending
    row = _alert_row(alert_id)
    assert row["attempts"] == 1 and row["status"] == "pending"
    assert "ConnectionError" in (row["last_error"] or "")

    delivered, abandoned = alerts.deliver_pending(limit=5)
    assert (delivered, abandoned) == (0, 0)          # inside the retry cooldown

    outbox.now += 61                                   # cooldown elapsed
    delivered, abandoned = alerts.deliver_pending(limit=5)
    assert (delivered, abandoned) == (0, 1)          # budget spent: dead letter
    row = _alert_row(alert_id)
    assert row["attempts"] == 2 and row["status"] == "abandoned"

    assert alerts.deliver_pending(limit=5) == (0, 0)  # dead letters are never retried


def test_outbox_marks_delivered_on_success(outbox, monkeypatch):
    """A successful attempt must stop retries and record what reached the channel."""
    seen = {}

    def fake_deliver(payload):
        seen.update(payload)
        return True, None

    monkeypatch.setattr(alerts, "_deliver", fake_deliver)
    alert_id = state_db.enqueue_alert(
        "critical", "x", "boom", '{"message": "boom", "level": "critical"}')

    assert alerts.deliver_pending(limit=5) == (1, 0)
    row = _alert_row(alert_id)
    assert row["status"] == "sent" and row["attempts"] == 1
    assert seen["message"] == "boom"
    assert alerts.deliver_pending(limit=5) == (0, 0)  # nothing left to drain


def test_alert_rate_limit_covers_the_outbox(outbox, monkeypatch):
    """Duplicate events must not multiply outbox rows while one delivery is in flight."""
    release = threading.Event()
    received = []

    def fake_deliver(payload, _release=release):
        received.append(payload)
        _release.wait(timeout=5)
        return True, None

    monkeypatch.setattr(alerts, "_deliver", fake_deliver)
    monkeypatch.setattr(config, "NEXUS_PIN", "PIN-VALUE")
    alerts.critical("vault_deficit", "transfer pin PIN-VALUE", amount=7)
    alerts.critical("vault_deficit", "duplicate should be dropped", amount=7)

    assert wait_until(lambda: len(received) == 1)
    row = _alert_row(1)
    assert "PIN-VALUE" not in (row["message"] or "")
    assert "***" in (row["message"] or "")           # PIN never reaches the channel
    assert "PIN-VALUE" not in received[0]["message"]
    assert "***" in received[0]["message"]
    # exactly one row even though alert() was called twice
    assert len(_outbox_rows()) == 1
    release.set()
    assert wait_until(lambda: _is_sent(1))


def test_dashboard_reports_undelivered_alerts(outbox, monkeypatch):
    """Pending retries and dead letters must be visible to the operator, sent ones excluded."""
    def fake_deliver(payload):
        ok = payload.get("event") != "nexus_debit_held"
        return (ok, None if ok else "down")

    monkeypatch.setattr(alerts, "_deliver", fake_deliver)
    monkeypatch.setattr(config, "MAX_ALERT_ATTEMPTS", 2)
    monkeypatch.setattr(config, "ALERT_RETRY_COOLDOWN_SEC", 60)

    abandoned_id = state_db.enqueue_alert("critical", "nexus_debit_held", "dead note",
                          json.dumps({"event": "nexus_debit_held", "level": "critical"}))
    sent_id = state_db.enqueue_alert("warning", "refund_exhausted", "sent note", "{}")

    assert alerts.deliver_pending(limit=5) == (1, 0)      # warning delivered, critical pending
    assert _alert_row(abandoned_id)["status"] == "pending"

    outbox.now += 61                                       # cooldown elapsed
    assert alerts.deliver_pending(limit=5) == (0, 1)      # budget spent: dead letter
    assert _alert_row(abandoned_id)["status"] == "abandoned"

    pending_id = state_db.enqueue_alert("critical", "stuck_event", "pending note", "{}")

    summary = dashboard.api_summary()
    assert summary["undelivered_alerts"]["counts"] == {"critical": 2}

    issues = dashboard.api_issues()
    assert issues["counts"]["undelivered"] == 2
    by_id = {r["id"]: r for r in issues["undelivered_alerts"]}
    assert by_id[pending_id]["status"] == "pending"
    assert by_id[abandoned_id]["status"] == "abandoned"
    assert by_id[abandoned_id]["age_sec"] >= 0
    assert sent_id not in by_id
