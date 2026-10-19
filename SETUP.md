# swapService Operator and Setup Reference — Release Blocked

This guide preserves the installation, configuration and operational contract of the currently
implemented **one configured Solana token / Nexus token pair** bridge. It does not authorize operation.
The non-executable user-flow reference is in [README.md](README.md); every parsed operator-facing setting
is listed in [CONFIG.md](CONFIG.md).

> **No custody deployment is release-approved.** The direct Python and historical systemd routes below
> bypass the optional external-container admission primitive, and that primitive is not yet bound to the
> one-use witness. Coherent restore, semantic host policy, service/node freshness and target acceptance
> also remain open. Use this document for offline development and protocol review only. Do not create
> live custody accounts, publish a service/mapping asset, load real credentials, transfer tokens, run the
> mutating operator CLI or start the service until one immutable candidate passes the maintained plan and
> a named human release owner approves it.

## Implemented scope

A process bridges one configured pair in two directions:

- **Solana → Nexus:** a user transfers the configured Solana-side token to the configured vault token account and includes `<DEPOSIT_MEMO_PREFIX><Nexus destination>`.
- **Nexus → Solana:** a user credits the configured Nexus treasury and publishes the existing `txid_toService` + `receival_account` mapping described in [ASSET_STANDARD.md](ASSET_STANDARD.md).

Missing mapping -> hold for operator review (no automatic Nexus refund).

The gross conversion is **1:1 in whole token units before fees**. Base units are rescaled when the two tokens use different decimal precision. The immutable `config.SWAP_PAIR` object supplies both token identities, custody accounts, decimals, fee policy and memo prefix to current money paths.

The Solana implementation is limited to mints and accounts owned by the classic SPL Token Program (`Tokenkeg...`). Configurability does **not** imply native SOL, Token-2022 extensions, arbitrary token programs, arbitrary chains, or simultaneous pairs. Deploying another classic SPL/Nexus pair still requires target-token and target-node acceptance testing; a configurable identity is not a blanket asset-safety guarantee.

### Compatibility names are not product branding

Some active environment variables, database columns, retry keys, reservation kinds and persisted statuses retain `USDC`/`USDD` in their literal names. They are compatibility interfaces from the original deployment, not assertions that every deployment bridges those assets. New environment configuration should use the generic canonical spellings where they exist. [CONFIG.md](CONFIG.md#canonical-keys-and-legacy-aliases) lists both spellings and the conflict rules.

### Planned, not implemented

The following remain planned work:

- provider asset v2 and address-based provider identity;
- general-chain or multi-pair routing;
- automatic pair discovery or per-request asset selection;
- automatic Nexus refunds/quarantine transfers from the service loop;
- automatic DEX conversion or backing-surplus mint/rebalance.

See [the planned provider-v2 standard](ASSET_STANDARD.md#provider-swapservice-asset-standard-v2-planned) and [Batch 7 in the evaluation](docs/EVALUATION.md#batch-7--complete-configurability-and-provider-asset-v2-in-progress-provider-v2-remains-documentation-only). The current runtime still uses one **name-addressed v1 heartbeat/service record**.

## Prerequisite inventory for a future release candidate

- Python 3.10+
- a Solana RPC endpoint
- Solana CLI and SPL Token CLI for deployment setup only
- a synced Nexus node and profile
- SQLite storage writable by one service instance

For production, use a dedicated Solana RPC provider. The runtime can use Helius enriched transaction retrieval when `HELIUS_RPC_URL` or `HELIUS_API_KEY` is set; otherwise it falls back to core Solana RPC.

Install the Solana tools from the maintained Anza documentation:

- [Install the Solana CLI](https://solana.com/docs/intro/installation)
- [SPL Token CLI documentation](https://spl.solana.com/token)

## Local dependency setup for offline development

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
# Optional synthetic configuration only; never place live custody credentials in this review checkout.
cp .env.example .env.synthetic
chmod 600 .env.synthetic
```

Do not commit `.env`, the vault keypair, Nexus PIN/session, API credentials, or private RPC URLs.

## Configuration reference — do not activate custody

Use canonical generic keys for new deployments:

```env
# Solana custody and token identity
SOLANA_RPC_URL=<HTTPS_SOLANA_RPC_URL>
VAULT_KEYPAIR=<PATH_TO_VAULT_KEYPAIR_JSON>
SOL_MAIN_ACCOUNT=<SOLANA_VAULT_OWNER_PUBKEY>
SOLANA_VAULT_ACCOUNT=<CLASSIC_SPL_TOKEN_ACCOUNT_FOR_CONFIGURED_MINT>
SOLANA_TOKEN_MINT=<CLASSIC_SPL_MINT_PUBKEY>
SOLANA_TOKEN_SYMBOL=<DISPLAY_SYMBOL>
SOLANA_TOKEN_DECIMALS=<DECIMALS>

# Nexus custody and immutable token identity
NEXUS_PIN=<PROFILE_PIN>
NEXUS_TREASURY_ACCOUNT=<NEXUS_TOKEN_TREASURY_ACCOUNT>
NEXUS_TOKEN_NAME=<NEXUS_TOKEN_NAME>
NEXUS_TOKEN_REGISTER_ADDRESS=<IMMUTABLE_NEXUS_TOKEN_REGISTER_ADDRESS>
NEXUS_TOKEN_DECIMALS=<DECIMALS>

# Direction-named fee terms
FEE_FLAT_TO_NEXUS=<NEXUS_OUTPUT_TOKEN_UNITS>
FEE_FLAT_TO_SOLANA=<SOLANA_OUTPUT_TOKEN_UNITS>
FEE_REFUND_SOLANA=<SOLANA_TOKEN_UNITS>
FEE_BPS=<0_TO_4999>
DEPOSIT_MEMO_PREFIX=nexus:
```

All decimal fee and threshold values must be exactly representable at the relevant configured precision. Canonical and legacy aliases may both be present only when their strings are identical; conflicting identity, custody, precision or fee aliases fail startup.

If minimums and the Nexus dust threshold are omitted, the code derives them from the flat fee. An explicit minimum below the safety floor is raised to twice the corresponding flat fee and reported at startup. See [CONFIG.md § Fees, minimums and limits](CONFIG.md#fees-minimums-and-limits).

## Solana custody setup reference — do not execute

A future approved deployment would require a dedicated protected vault signer. The historical command
shape below is reference only and must not be run under the current gate:

```bash
solana-keygen new -o <VAULT_KEYPAIR_PATH>
chmod 600 <VAULT_KEYPAIR_PATH>
solana config set -k <VAULT_KEYPAIR_PATH> -u <SOLANA_RPC_URL>
solana address
```

A future operator would separately fund fees and create classic SPL Token Program accounts for the
approved mint; these command shapes remain non-executable reference:

```bash
spl-token create-account <SOLANA_TOKEN_MINT>
spl-token accounts --owner <SOL_MAIN_ACCOUNT>
spl-token balance <SOLANA_VAULT_ACCOUNT>
```

The resulting token-account address, not the wallet owner address, would be `SOLANA_VAULT_ACCOUNT`.
An approved production design would also require a self-owned same-mint quarantine account and an
explicit decision about `SOLANA_FEE_ACCOUNT`; absent that setting, Solana-side fees remain in the vault.

Before deployment, independently verify that the configured mint, vault, quarantine and fee accounts all belong to the intended classic SPL mint and operator. Do not substitute a native SOL account or Token-2022 account.

## Nexus custody setup reference — do not execute

The operator needs:

1. a synced Nexus node and active profile/session;
2. the configured Nexus token name and immutable register address;
3. a treasury account for that exact token;
4. a dedicated quarantine account in production;
5. authority required by the service's `finance/debit/token from=<NEXUS_TOKEN_NAME>` path.

The future approved configuration would contain these canonical custody keys:

```env
NEXUS_TREASURY_ACCOUNT=<TREASURY_ACCOUNT>
NEXUS_QUARANTINE_ACCOUNT=<QUARANTINE_ACCOUNT>
NEXUS_FEE_ACCOUNT=<OPTIONAL_FEE_ACCOUNT>
```

`NEXUS_USDD_LOCAL_ACCOUNT` remains a literal legacy-named compatibility setting for micro-credit handling; no generic alias exists yet. It does not enable automatic Nexus refunds.

### Nexus transport

Source-level local fixtures can model `NEXUS_CLI_PATH`. A future production candidate requires the
authenticated HTTPS transport represented by these placeholders:

```env
NEXUS_API_URL=https://127.0.0.1:<TLS_PORT>
NEXUS_API_USER=<API_USER>
NEXUS_API_PASSWORD=<API_PASSWORD>
```

The future production URL must be HTTPS and contain no embedded credentials, query or fragment. Its
approved Nexus node would require `apiauth=1`, `apissl=1` and `apisslrequired=1`, restricted non-loopback
access and certificate validation. These requirements do not authorize configuring a live node now.

The expected multiuser configuration shape is:

```env
NEXUS_MULTIUSER=true
NEXUS_SESSION=<SESSION_ID>
```

`NEXUS_SESSION` is required when `NEXUS_MULTIUSER=true`. In a single-user configuration,
`NEXUS_MULTIUSER=false` makes the service omit a session because single-user Nexus calls reject it.
The session and PIN are spending credentials and must not be loaded for this review.

## Required heartbeat and recovery evidence — no bypass

`HEARTBEAT_ENABLED` is consulted by v1 service-record publication and heartbeat validation, but it does not disable the main recovery and polling dependencies. Startup recovery always reads the configured name-addressed heartbeat record. A live process therefore needs `NEXUS_HEARTBEAT_ASSET_NAME` resolving to a readable v1 asset containing:

- `last_poll_timestamp`;
- the configured Solana waterline field (default `last_safe_timestamp_solana`);
- the configured Nexus waterline field (default `last_safe_timestamp_nexus`).

The field names must be non-empty, distinct and match the top-level fields already present on the Nexus `format=basic` asset. `NEXUS_HEARTBEAT_ASSET_ADDRESS` is currently not used as the live lookup identity; provider-v2 address-based selection is planned.

Preview the current v1 service record without writing anything:

```bash
python3 register_service.py --show
python3 register_service.py --show --json
python3 register_service.py --create --name <HEARTBEAT_ASSET_NAME> --dry-run
python3 register_service.py --inspect <HEARTBEAT_ASSET_NAME>
```

`register_service.py --create` becomes a live, permanent Nexus operation when `--dry-run` is removed;
that live form is prohibited while release is blocked. It creates a complete current v1 field set, but
its initial waterlines are zero. **Zero or missing waterlines cannot pass startup recovery.** A future
first start would require independently reviewed positive checkpoints covering all relevant custody
history. Current time is never a safe substitute for history. No automated helper can choose a safe
bootstrap checkpoint; the future ceremony must retain the evidence and human decision for each value.

`create_heartbeat_asset.py` is a legacy v1 helper whose defaults include zero waterlines and pair-specific
example labels. Its mutating mode is prohibited. A future compatibility decision would require explicit
generic pair fields, reviewed positive `--solana-waterline-initial` / `--nexus-waterline-initial` values,
dry-run preview and exact readback before use.

Startup recovery is an admission gate, not a best-effort diagnostic. Polling begins only if both checkpoints are positive and both chain scans return complete, authoritative evidence. Missing/incompatible heartbeat data, incomplete pagination, malformed or legacy payout evidence, sparse refund/quarantine markers, reference lookup failure, or any recovery exception produces a nonzero service exit. A bounded recent scan is not accepted as recovery.

Source: [`src/startup_recovery.py`](src/startup_recovery.py) and [`src/main.py`](src/main.py).

## Unmet production admission controls

> **Payout-budget control:** all automated Solana token sends reserve rolling-cap capacity in
> SQLite before RPC, retain it across submitted or unknown outcomes, and settle it only from the
> exact confirmed signature. The positive-cap startup requirement is therefore enforced locally;
> target-chain timeout/crash/finality acceptance remains required. See [SECURITY.md](docs/SECURITY.md).

The current documentation does not authorize setting `SWAP_PRODUCTION_MODE=true`. A future production
candidate would require all of the following in addition to the open release gates:

- positive `MAX_SWAP_USDC`, `MAX_SWAP_USDD` and `DAILY_PAYOUT_CAP_USDC` values (literal legacy-named active keys; no generic env aliases exist yet);
- `SOLANA_QUARANTINE_ACCOUNT` and `NEXUS_QUARANTINE_ACCOUNT`;
- `NEXUS_TOKEN_REGISTER_ADDRESS`;
- `ALERT_WEBHOOK_URL` or `ALERT_COMMAND`;
- valid Nexus HTTPS API URL, user and password;
- `NEXUS_SESSION` when multiuser mode is enabled.
- `NEXUS_SWAP_RECEIPTS_ENABLED=false`; named receipt assets spend NXS. A local pre-create budget ledger exists, but registration migration and target-node acceptance are still unproven.

The production switch accepts only `1/true/yes/on` and `0/false/no/off`, case-insensitively. A typo fails closed. A configured alert route is not proof of delivery; test it separately before live operation.

## Offline verification; custody startup remains blocked

Run local, non-chain tests first:

```bash
python -m pytest -q
python3 scripts/check_markdown_links.py
```

Do **not** run `python3 swapService.py` or install the historical systemd unit. Both are direct repository
entrypoints and therefore bypass protected external admission. A future supported service unit must invoke
an independently installed launcher/interpreter, bind the approved image/configuration authority to the
same one-use witness generation and refuse restart/retry outside that protocol. The exact unit is a Batch 0
deliverable, not a placeholder operators should invent.

The entrypoint's nonzero refusal and `SWAP_LOCK_PATH` singleton lock remain useful internal controls, but
they do not make direct startup safe. Authorized target-infrastructure verification of both directions,
invalid inputs, unknown outcomes, alert delivery, restart, coherent restore and paused-mode behavior belongs
to Batch 7 after Batches 0–6 pass; process output alone is never settlement evidence.

## Held Nexus credits: no automatic refund

A missing/invalid Nexus mapping, an oversized Nexus credit, or another refund condition is held for operator review. The service loop does **not** automatically debit the Nexus treasury for a refund or quarantine movement.

The following historical CLI shape is retained for source review only. **Do not execute these mutating
commands while release is blocked.** A future authorized disposition requires the Batch 6 evidence-bound
protocol, exact source/target readback, attributable human authority and a candidate accepted under Batch 7:

```bash
python3 nexus_transfer_operator.py prepare --kind refund \
  --txid <NEXUS_CREDIT_TXID> --contract-id <CREDIT_CONTRACT_ID> \
  --operator <OPERATOR> --reason "<REVIEWED_RATIONALE>"

python3 nexus_transfer_operator.py show --intent <INTENT_ID>

python3 nexus_transfer_operator.py authorize --intent <INTENT_ID> \
  --confirm-reference <DISPLAYED_REFERENCE> \
  --operator <OPERATOR> --reason "<REVIEWED_RATIONALE>"

python3 nexus_transfer_operator.py execute --intent <INTENT_ID> \
  --operator <OPERATOR> --reason "<ONE_TIME_EXECUTION_RATIONALE>"

python3 nexus_transfer_operator.py resolve

python3 nexus_transfer_operator.py finalize --intent <INTENT_ID> \
  --confirm-remote-txid <CONFIRMED_REMOTE_TXID> \
  --operator <OPERATOR> --reason "<CONFIRMED_EVIDENCE>"
```

Under the designed protocol, `execute` must never be rerun after a timeout, nonzero result or unparsable
response. Those outcomes may follow an accepted debit and remain `outcome_unknown` until positive reference
resolution. `prepare --kind quarantine` targets `NEXUS_QUARANTINE_ACCOUNT` through its legacy internal
attribute. `list`, `show` and `resolve` are intended to be non-debiting; this description does not authorize
their use against a live custody database before the operational gate is accepted.

Source: [`nexus_transfer_operator.py`](nexus_transfer_operator.py) and the durable intent implementation in [`src/nexus_client.py`](src/nexus_client.py).

## State, monitoring and troubleshooting

- `STATE_DB_PATH` is the authoritative SQLite state store. Some schema and status names remain legacy-frozen for upgrade safety.
- `FEES_STATE_FILE` is a legacy JSON fee journal reconciled against the database; the database wins on drift.
- The read-only dashboard is a separate process: `python3 dashboard.py`. It opens SQLite in read-only mode and has no retry/refund/release endpoint. Non-loopback binding requires `DASHBOARD_TOKEN`; use a TLS reverse proxy or SSH tunnel.
- A backing deficit or incomplete mint reconciliation pauses new exposure but keeps existing Solana refund/quarantine and confirmation work running.
- Backing surplus is alert-only. No automatic DEX trade or Nexus surplus mint runs.
- A heartbeat update failure can freeze liveness and waterlines because Nexus `format=basic` updates are atomic and cannot add missing fields.
- An unreadable heartbeat during live Solana polling uses the last locally persisted waterline only if one exists; otherwise Solana ingestion halts. This fallback does not weaken the mandatory complete startup-recovery gate.

Useful read-only tools:

```bash
python3 quarantine_viewer.py --solana
python3 quarantine_viewer.py --nexus
python3 nexus_transfer_operator.py list
python3 register_service.py --inspect <HEARTBEAT_ASSET_NAME>
```

The hidden `quarantine_viewer.py --usdc` / `--usdd` options are legacy CLI aliases; prefer `--solana` / `--nexus`.

## References

- [Configuration reference](CONFIG.md)
- [Asset mapping and current/planned provider records](ASSET_STANDARD.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/STATE_MACHINES.md](docs/STATE_MACHINES.md)
- [docs/SWAP_INITIATOR_STATE_MACHINES.md](docs/SWAP_INITIATOR_STATE_MACHINES.md)
- [docs/AUDIT_FINDINGS.md](docs/AUDIT_FINDINGS.md)
- [Current evaluation and live acceptance gaps](docs/EVALUATION.md)

LICENSE: Provided as-is; no warranty.
