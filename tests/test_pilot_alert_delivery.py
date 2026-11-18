from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src import alerts, config, state_db


@pytest.mark.parametrize('status', [200, 204, 302, 401, 503])
def test_webhook_requires_positive_http_acknowledgement(monkeypatch, status):
    monkeypatch.setattr(config, 'ALERT_WEBHOOK_URL', 'https://example.invalid/alerts')
    monkeypatch.setattr(config, 'ALERT_COMMAND', None)
    post = Mock(return_value=SimpleNamespace(status_code=status))
    monkeypatch.setattr(requests, 'post', post)
    accepted, _ = alerts._deliver({'event': 'test'})
    assert accepted is (200 <= status < 300)
    assert post.call_args.kwargs['allow_redirects'] is False


@pytest.mark.parametrize('returncode', [0, 1])
def test_notification_command_requires_zero_exit_status(monkeypatch, returncode):
    monkeypatch.setattr(config, 'ALERT_WEBHOOK_URL', None)
    monkeypatch.setattr(config, 'ALERT_COMMAND', 'test-notifier')
    monkeypatch.setattr(alerts.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=returncode)))
    assert alerts._deliver({'event': 'test'})[0] is (returncode == 0)


def test_startup_diagnostic_leaves_custody_file_untouched(monkeypatch, tmp_path):
    monkeypatch.setattr(state_db, 'DB_PATH', str(tmp_path / 'custody.sqlite'))
    monkeypatch.setattr(config, 'ALERT_WEBHOOK_URL', 'https://example.invalid/alerts')
    delivery = Mock()
    monkeypatch.setattr(alerts, '_deliver', delivery)
    alerts.critical('startup_diagnostic_test', 'test', persist=False)
    assert not (tmp_path / 'custody.sqlite').exists()
    delivery.assert_not_called()
