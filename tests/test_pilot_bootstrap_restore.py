import shutil
from pathlib import Path

import pytest

from src import custody_admission, custody_bootstrap, custody_witness, nexus_client, startup_recovery, state_db


def test_bootstrap_image_supported_through_idle_restart(tmp_path, monkeypatch):
    path = tmp_path / 'new.sqlite'
    monkeypatch.setattr(state_db, 'DB_PATH', str(path))
    custody_bootstrap.prepare(path, 'test-pilot', nexus_waterline=100, solana_waterline=200)
    with pytest.raises(FileExistsError):
        custody_bootstrap.prepare(path, 'test-pilot', nexus_waterline=100, solana_waterline=200)
    assert custody_admission.inspect_image(path)['image_size'] > 0
    assert not state_db.latch_empty_custody_recovery(
        deployment_id='test-pilot', nexus_waterline=100, solana_waterline=200)
    assert not state_db.latch_empty_custody_recovery(
        deployment_id='test-pilot', nexus_waterline=101, solana_waterline=201)
    assert state_db.latch_empty_custody_recovery(
        deployment_id='wrong-pilot', nexus_waterline=101, solana_waterline=201)
    assert state_db.latch_empty_custody_recovery(
        deployment_id='test-pilot', nexus_waterline=101, solana_waterline=201)


def test_first_start_uses_reviewed_reference_floor_when_token_has_no_debits(tmp_path, monkeypatch):
    path = tmp_path / 'new.sqlite'
    monkeypatch.setattr(state_db, 'DB_PATH', str(path))
    custody_bootstrap.prepare(path, 'test-pilot', nexus_waterline=100, solana_waterline=200,
                              reference_floor=60)
    nxs_field, sol_field = nexus_client.heartbeat_waterline_field_names()
    monkeypatch.setattr(nexus_client, 'get_heartbeat_asset',
                        lambda: {nxs_field: 100, sol_field: 200})
    monkeypatch.setattr(nexus_client, 'get_last_reference', lambda: None)
    monkeypatch.setattr(startup_recovery, '_rebuild_solana_from_waterline',
                        lambda ts: {'recovery_complete': True})
    monkeypatch.setattr(nexus_client, 'fetch_deposits_since',
                        lambda address, ts: nexus_client.DepositScan([], True))
    result = startup_recovery.perform_startup_recovery(deployment_id='test-pilot')
    assert result['recovery_complete'] is True, result
    assert state_db.next_reference() == 61


def test_waterline_acknowledgement_keeps_newer_or_unpublished_work(tmp_path, monkeypatch):
    monkeypatch.setattr(state_db, 'DB_PATH', str(tmp_path / 'waterlines.sqlite'))
    state_db.init_db()
    state_db.propose_solana_waterline(110)
    state_db.propose_nexus_waterline(200)
    state_db.acknowledge_waterline_proposals(solana=100, nexus=None)
    assert state_db.get_proposed_solana_waterline() == 110
    assert state_db.get_proposed_nexus_waterline() == 200
    state_db.acknowledge_waterline_proposals(solana=110, nexus=200)
    assert state_db.get_proposed_solana_waterline() is None
    assert state_db.get_proposed_nexus_waterline() is None


def test_restore_replaces_permit_with_admin_approved_exact_image(tmp_path, monkeypatch):
    original = tmp_path / 'pilot.sqlite'
    monkeypatch.setattr(state_db, 'DB_PATH', str(original))
    custody_bootstrap.prepare(original, 'test-pilot', nexus_waterline=100, solana_waterline=200)
    runtime, admin = 'r' * 32, 'a' * 32
    store = custody_witness.Store(tmp_path / 'witness.sqlite', runtime_token=runtime, admin_token=admin)
    client = custody_witness.StoreClient(store, runtime)
    initial = custody_bootstrap.certificate(original, 'test-pilot', 0, '1' * 64, '2' * 64, 'new pilot evidence')
    store.issue_initial(initial, actor='reviewer', rationale='new pilot evidence', admin_token=admin)
    def claim(path: Path):
        return custody_admission.claim(db_path=path, client=client, deployment_id='test-pilot',
                                       config_sha256='1' * 64, build_sha256='2' * 64)
    old = claim(original)
    old.complete()
    with pytest.raises(custody_admission.AdmissionError):
        claim(original)
    backup = tmp_path / 'reconciled.sqlite'
    shutil.copyfile(original, backup)  # Offline fixture: no SQLite writers or sidecars.
    replacement = custody_bootstrap.certificate(backup, 'test-pilot', 1, '1' * 64, '2' * 64, 'reconciled image')
    def restore(token, fencing):
        return store.approve_restore(replacement, prior_permit_nonce=initial.permit_nonce,
                                     actor='reviewer', fencing_evidence=fencing,
                                     reconciliation_evidence='reviewed liability and transaction report',
                                     admin_token=token)
    with pytest.raises(custody_witness.WitnessError):
        restore(runtime, 'old signer removed')
    with pytest.raises(custody_witness.WitnessError):
        restore(admin, '')
    restore(admin, 'old signer removed and process stopped')
    with pytest.raises(custody_admission.AdmissionError):
        old.assert_running()
    with pytest.raises(custody_witness.WitnessError):
        restore(admin, 'old signer removed and process stopped')
    old._close_image()
    restored = claim(backup)
    assert restored.generation == 1
    restored.complete()
    restored.seal()
    assert client.get_head('test-pilot')['status'] == 'ready'
