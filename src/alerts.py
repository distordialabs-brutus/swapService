"""Operator alerting.

Before this existed, every safety signal the service produced - backing deficit pause,
unbacked-mint discrepancy, halted poller, exhausted refund, breached cap - was a bare
`print()` to stdout. Nothing reached a human unless somebody happened to be watching a
terminal, which for a custodial bridge means the detection logic was effectively
decorative.

Delivery is durable and never raises: an alerting failure must not take down the
swap loop. Configure at least one channel:

    ALERT_WEBHOOK_URL   POST a JSON body
    ALERT_COMMAND       executable; receives the same JSON on stdin

Every alert is written to the state DB outbox before delivery, so a crash or process
exit cannot lose it: the main loop drains the outbox, retries failed deliveries
(rate-limited by ALERT_RETRY_COOLDOWN_SEC up to MAX_ALERT_ATTEMPTS), and dead-letters
anything that exhausts its budget so the dashboard can report what never reached the
operator. Delivery is at-least-once by design; duplicate notifications are harmless,
silent loss is not.

Identical events are rate-limited to one per ALERT_MIN_INTERVAL_SEC so a stuck condition
cannot flood the channel.
"""
import json
import logging
import subprocess
import threading
import time
from typing import Any, Dict

from . import config, state_db, structured_logging

_LOG = structured_logging.get_logger("swapService.alerts")

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"

# Alerts attempted per main-loop drain, so a stuck channel cannot stall the swap loop.
DRAIN_LIMIT = 3

_lock = threading.Lock()
_last_sent: Dict[str, float] = {}


def _redact(value: Any) -> Any:
    """Never let the Nexus PIN reach an external channel."""
    pin = getattr(config, "NEXUS_PIN", "") or ""
    if pin and isinstance(value, str) and pin in value:
        return value.replace(pin, "***")
    return value


def _deliver(payload: dict) -> tuple[bool, str | None]:
    """Best-effort delivery to every configured channel.

    Returns (delivered, error): delivered means at least one channel accepted the
    alert, and error lists every channel that failed, for the outbox record. Never
    raises - an alerting failure must not take down the swap loop.
    """
    body = json.dumps(payload, default=str)
    outcomes = []

    url = getattr(config, "ALERT_WEBHOOK_URL", None)
    if url:
        try:
            import requests
            requests.post(url, data=body,
                          headers={"Content-Type": "application/json"},
                          timeout=10)
            outcomes.append((True, None))
        except Exception as e:
            structured_logging.emit(
                _LOG, logging.WARNING, "alert_webhook_delivery_failed",
                "operator alert webhook delivery failed",
                error_type=type(e).__name__, error=str(e),
            )
            outcomes.append((False, f"webhook: {type(e).__name__}: {e}"))

    cmd = getattr(config, "ALERT_COMMAND", None)
    if cmd:
        try:
            subprocess.run([cmd], input=body, text=True, timeout=15,
                           capture_output=True)
            outcomes.append((True, None))
        except Exception as e:
            structured_logging.emit(
                _LOG, logging.WARNING, "alert_command_delivery_failed",
                "operator alert command delivery failed",
                error_type=type(e).__name__, error=str(e),
            )
            outcomes.append((False, f"command: {type(e).__name__}: {e}"))

    if not outcomes:
        return False, "no alert channel configured"
    errors = [err for ok, err in outcomes if not ok]
    return any(ok for ok, _ in outcomes), ("; ".join(errors) if errors else None)


def _record(alert_id: int, delivered: bool, error: str | None) -> dict | None:
    """Record an attempt outcome; the outbox update itself is best-effort."""
    try:
        return state_db.record_alert_delivery(alert_id, delivered, error)
    except Exception as e:
        structured_logging.emit(
            _LOG, logging.ERROR, "alert_outbox_record_failed",
            "operator alert delivery outcome could not be recorded",
            error_type=type(e).__name__, error=str(e),
        )
        return None


def _deliver_queued(alert_id: int) -> None:
    """Attempt one queued alert and record the outcome. Never raises."""
    try:
        row = state_db.load_alert(alert_id)
        if row is None:
            return
        payload = json.loads(row["payload_json"])
    except Exception as e:
        structured_logging.emit(
            _LOG, logging.ERROR, "alert_outbox_deliver_failed",
            "operator alert could not be read back from the outbox",
            error_type=type(e).__name__, error=str(e),
        )
        _record(alert_id, False, f"outbox read: {type(e).__name__}: {e}")
        return
    delivered, error = _deliver(payload)
    _record(alert_id, delivered, error)


def deliver_pending(limit: int = DRAIN_LIMIT) -> tuple[int, int]:
    """Drain due outbox alerts: retry what is pending, dead-letter what is exhausted.

    Returns (delivered, abandoned) counts for the drained batch.
    """
    delivered = 0
    abandoned = 0
    for row in state_db.due_alert_rows(limit=limit):
        try:
            payload = json.loads(row["payload_json"])
        except Exception as e:
            structured_logging.emit(
                _LOG, logging.ERROR, "alert_outbox_deliver_failed",
                "operator alert payload in the outbox is unreadable",
                error_type=type(e).__name__, error=str(e),
            )
            _record(row["id"], False, f"payload: {type(e).__name__}: {e}")
            continue
        delivered_row, error = _deliver(payload)
        outcome = _record(row["id"], delivered_row, error)
        status = outcome["status"] if outcome else None
        if status == state_db.ALERT_OUTBOX_SENT:
            delivered += 1
        elif status == state_db.ALERT_OUTBOX_ABANDONED:
            abandoned += 1
    return delivered, abandoned


def alert(level: str, event: str, message: str = "", **fields) -> None:
    """Emit an operator alert. Always logs; delivers if a channel is configured."""
    try:
        safe_fields = {k: _redact(v) for k, v in fields.items()}
        structured_logging.emit(
            _LOG,
            {CRITICAL: logging.CRITICAL, WARNING: logging.WARNING, INFO: logging.INFO}.get(
                level, logging.INFO
            ),
            event,
            _redact(message),
            **safe_fields,
        )

        # Rate-limit identical events so a persistent condition cannot flood the channel.
        now = time.monotonic()
        interval = int(getattr(config, "ALERT_MIN_INTERVAL_SEC", 300))
        with _lock:
            last = _last_sent.get(event)
            if last is not None and (now - last) < interval:
                return
            _last_sent[event] = now

        if not (getattr(config, "ALERT_WEBHOOK_URL", None) or getattr(config, "ALERT_COMMAND", None)):
            return

        payload = {
            "service": "swapService",
            "level": level,
            "event": event,
            "message": _redact(message),
            "timestamp": int(time.time()),
            "fields": safe_fields,
        }
        # Persist first: the outbox survives a crash or process exit, and the main loop
        # retries from it, so an alert is never lost for lack of transport.
        try:
            alert_id = state_db.enqueue_alert(
                level, event, _redact(message), json.dumps(payload, default=str))
        except Exception as e:
            structured_logging.emit(
                _LOG, logging.ERROR, "alert_outbox_enqueue_failed",
                "operator alert could not be safely queued for delivery",
                error_type=type(e).__name__, error=str(e),
            )
            # Degraded fallback: still deliver off the hot path, best-effort only.
            threading.Thread(target=_deliver, args=(payload,), daemon=True).start()
            return
        # Deliver off the hot path; a slow webhook must not stall the swap loop.
        threading.Thread(target=_deliver_queued, args=(alert_id,), daemon=True).start()
    except Exception as e:
        structured_logging.emit(
            _LOG, logging.ERROR, "alert_emit_failed", "operator alert emission failed",
            error_type=type(e).__name__, error=str(e),
        )


def critical(event: str, message: str = "", **fields) -> None:
    alert(CRITICAL, event, message, **fields)


def warning(event: str, message: str = "", **fields) -> None:
    alert(WARNING, event, message, **fields)


def info(event: str, message: str = "", **fields) -> None:
    alert(INFO, event, message, **fields)