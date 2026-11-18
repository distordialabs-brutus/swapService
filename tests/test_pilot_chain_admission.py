import json
from unittest.mock import Mock

import pytest

from src import config, custody_chain, nexus_client
from src.custody_admission import AdmissionError


@pytest.mark.parametrize('age, allowed', [(5, True), (901, False), (-31, False)])
def test_requires_healthy_fresh_nodes(monkeypatch, age, allowed):
    now = 1_800_000_000
    solana = Mock(side_effect=['ok', 100, now - 5])
    monkeypatch.setattr(custody_chain, '_solana_rpc', solana, raising=False)
    replies = iter([{'synchronized': True, 'syncing': False, 'blocks': 100}, {'height': 100, 'timestamp': now - age}])
    monkeypatch.setattr(nexus_client, '_run', lambda *a, **kw: (0, json.dumps({'result': next(replies)}), ''))
    if allowed:
        custody_chain.require_fresh_tips(now=now)
    else:
        with pytest.raises(AdmissionError):
            custody_chain.require_fresh_tips(now=now)


@pytest.mark.parametrize('owner, allowed', [('approved-owner', True), ('other-owner', False)])
def test_production_heartbeat_is_bound_to_address_owner_and_pair(monkeypatch, owner, allowed):
    monkeypatch.setattr(config, 'PRODUCTION_MODE', True)
    monkeypatch.setattr(config, 'NEXUS_HEARTBEAT_ASSET_ADDRESS', 'approved-record')
    monkeypatch.setattr(config, 'NEXUS_HEARTBEAT_ASSET_OWNER', 'approved-owner', raising=False)
    pair = config.SWAP_PAIR
    nx, sol = nexus_client.heartbeat_waterline_field_names()
    record = {'address': 'approved-record', 'owner': owner, 'distordiaType': 'nexusBridgeHeartbeat',
              'nexus_treasury_address': str(pair.nexus.treasury_account or ''),
              'nexus_token_register_address': str(pair.nexus.register_address or ''),
              'solana_vault_address': str(pair.solana.vault_account),
              'solana_vault_mint': str(pair.solana.mint),
              'last_poll_timestamp': 20, nx: 10, sol: 10}
    run = Mock(return_value=(0, json.dumps({'result': record}), ''))
    monkeypatch.setattr(nexus_client, '_run', run)
    assert (nexus_client.get_heartbeat_asset() == record) is allowed
    assert 'address=approved-record' in run.call_args.args[0]


@pytest.mark.parametrize('confirmations, allowed', [(2, False), (10, True)])
def test_exact_nexus_credit_requires_configured_depth(monkeypatch, confirmations, allowed):
    txid = 'ab' * 64
    monkeypatch.setattr(config, 'NEXUS_TRANSFER_MIN_CONFIRMATIONS', 10)
    monkeypatch.setattr(nexus_client, '_run', Mock(return_value=(0, json.dumps({
        'result': {'txid': txid, 'confirmations': confirmations, 'blockhash': 'cd' * 128,
                   'contracts': [{'id': 1, 'OP': 'CREDIT', 'from': 'source', 'to': 'treasury',
                                  'token': 'register', 'amount': '1.25'}]}}), '')))
    assert nexus_client.has_confirmed_treasury_credit(
        txid=txid, contract_id=1, source='source', treasury='treasury',
        register='register', amount_units=125 * 10 ** (config.NEXUS_TOKEN_DECIMALS - 2),
    ) is allowed
