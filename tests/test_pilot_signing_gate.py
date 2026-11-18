from unittest.mock import Mock

import pytest

from src import config, custody_chain, nexus_client, solana_client, state_db
from src.custody_admission import AdmissionError


@pytest.mark.parametrize('endpoint', ['finance/debit/account', 'finance/credit/account',
                                      'assets/update/asset', 'assets/create/asset'])
def test_nexus_mutations_without_running_gate_never_reach_transport(monkeypatch, endpoint):
    monkeypatch.setattr(config, 'PRODUCTION_MODE', True)
    monkeypatch.setattr(config, 'NEXUS_API_URL', '')
    execute = Mock(return_value=Mock(returncode=0, stdout='{}', stderr=''))
    monkeypatch.setattr(nexus_client.subprocess, 'run', execute)
    with pytest.raises(AdmissionError):
        nexus_client._run(['nexus', endpoint])
    execute.assert_not_called()
    assert nexus_client._run(['nexus', 'ledger/get/transaction']) == (0, '{}', '')


def test_mint_refused_before_transport_can_be_queued_again(tmp_path, monkeypatch):
    monkeypatch.setattr(state_db, "DB_PATH", str(tmp_path / "refusal.db"))
    state_db.init_db()
    state_db.add_unprocessed_sig("source-sig", 100, "nexus:recipient", "sender", 100_000_000,
                                 "ready for processing", None)
    monkeypatch.setattr(config, "PRODUCTION_MODE", True)
    monkeypatch.setattr(config, "NEXUS_PIN", "fixture")
    monkeypatch.setattr(nexus_client, "is_valid_nexus_token_account", Mock(return_value=True))
    transport = Mock()
    monkeypatch.setattr(config, "NEXUS_API_URL", "https://offline.invalid")
    monkeypatch.setattr(nexus_client, "_run_via_nexus_api", transport)
    assert solana_client.process_unprocessed_solana_deposits() == [0, 0, 0, 0]
    transport.assert_not_called()
    assert state_db.get_unprocessed_sig_status("source-sig") == "ready for processing"
    assert state_db.get_unprocessed_sig_reference("source-sig") is None
    assert not state_db.is_reserved(state_db.DEBIT_RESERVATION_KIND, "source-sig")


def test_refund_signing_without_running_gate_is_refused(monkeypatch):
    monkeypatch.setattr(config, 'PRODUCTION_MODE', True)
    monkeypatch.setattr(solana_client, '_get_client', Mock())
    monkeypatch.setattr(solana_client, '_get_latest_blockhash_str',
                        Mock(return_value='11111111111111111111111111111111'))
    signer = Mock()
    signer.new_signed_with_payer.return_value = b'test-transaction'
    monkeypatch.setattr(solana_client, 'Transaction', signer)
    monkeypatch.setattr(solana_client, '_rpc_call', Mock())
    with pytest.raises(AdmissionError):
        solana_client._build_and_send_legacy_tx([], Mock())
    signer.new_signed_with_payer.assert_not_called()


def test_started_worker_cannot_submit_after_health_is_revoked(monkeypatch):
    monkeypatch.setattr(config, 'PRODUCTION_MODE', True)
    monkeypatch.setattr(custody_chain, 'verify', Mock())
    fresh = Mock()
    monkeypatch.setattr(custody_chain, 'require_fresh_tips', fresh)
    lease = Mock(assert_running=Mock())
    stop = Mock(return_value=False)
    with custody_chain.signing_session(lease, stop) as gate:
        assert gate.refresh()
        custody_chain.require_signing()
        gate.set_healthy(False)
        with pytest.raises(AdmissionError):
            custody_chain.require_signing()
        gate.set_healthy(True)
        fresh.side_effect = AdmissionError('stale')
        with pytest.raises(AdmissionError):
            custody_chain.require_signing()
        fresh.side_effect = None
        with pytest.raises(AdmissionError):
            custody_chain.require_signing()
    with pytest.raises(AdmissionError):
        custody_chain.require_signing()


def test_solana_rpc_worker_rechecks_before_sending_signed_bytes(monkeypatch):
    monkeypatch.setattr(config, 'PRODUCTION_MODE', True)
    monkeypatch.setattr(custody_chain, 'verify', Mock())
    monkeypatch.setattr(custody_chain, 'require_fresh_tips', Mock())
    rpc = Mock()
    monkeypatch.setattr(solana_client, '_get_client', lambda: rpc)
    monkeypatch.setattr(solana_client, '_get_latest_blockhash_str',
                        lambda client: '11111111111111111111111111111111')
    signer = Mock()
    signer.new_signed_with_payer.return_value = b'test-transaction'
    monkeypatch.setattr(solana_client, 'Transaction', signer)
    lease = Mock(assert_running=Mock())
    with custody_chain.signing_session(lease, lambda: False) as gate:
        assert gate.refresh()
        def delayed_rpc(method, raw, **kwargs):
            gate.set_healthy(False)
            return method(raw)
        monkeypatch.setattr(solana_client, '_rpc_call', delayed_rpc)
        with pytest.raises(AdmissionError):
            solana_client._build_and_send_legacy_tx([], Mock())
        signer.new_signed_with_payer.assert_called_once()
        rpc.send_raw_transaction.assert_not_called()
