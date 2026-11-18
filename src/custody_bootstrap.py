"""Offline preparation of a new pilot image and candidate witness certificates."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from . import custody_admission, state_db
from .custody_witness import Certificate


def prepare(path: Path, deployment_id: str, *, nexus_waterline: int, solana_waterline: int,
            reference_floor: int = 0) -> None:
    """Create a new image only; never modify an existing custody DB."""
    if (not deployment_id or deployment_id != deployment_id.strip() or len(deployment_id) > 128
            or any(type(n) is not int or not 0 < n < 2**63 for n in (nexus_waterline, solana_waterline))
            or type(reference_floor) is not int or not 0 <= reference_floor < 2**63 - 1):
        raise ValueError("invalid initial deployment or checkpoints")
    if any(os.path.lexists(str(path) + suffix) for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError("unexpected SQLite sidecar; use a new image path")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        state_db._init_db_with_connection(conn)
        conn.execute("INSERT INTO custody_bootstrap VALUES (1, ?, ?, ?)",
                     (deployment_id, nexus_waterline, solana_waterline))
        conn.execute("INSERT INTO counters (name, value) VALUES ('reference', ?)", (reference_floor,))
    custody_admission.inspect_image(path)


def certificate(path: Path, deployment_id: str, generation: int, config_sha256: str,
                build_sha256: str, rationale: str) -> Certificate:
    """Describe exact sealed bytes for independent review; does not grant authority."""
    return Certificate.from_dict({
        'deployment_id': deployment_id, 'generation': generation,
        'permit_nonce': secrets.token_hex(32), **custody_admission.inspect_image(path),
        'config_sha256': config_sha256, 'build_sha256': build_sha256,
        'issued_at': int(time.time()), 'approval_rationale': rationale,
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    new = sub.add_parser('prepare', help='create an offline candidate first-start image')
    new.add_argument('--image', type=Path, required=True)
    new.add_argument('--deployment', required=True)
    new.add_argument('--nexus-waterline', type=int, required=True)
    new.add_argument('--solana-waterline', type=int, required=True)
    new.add_argument('--reference-floor', type=int, required=True)
    cert = sub.add_parser('describe', help='print an unapproved candidate certificate as JSON')
    cert.add_argument('--image', type=Path, required=True)
    cert.add_argument('--deployment', required=True)
    cert.add_argument('--generation', type=int, required=True)
    cert.add_argument('--rationale', required=True)
    cert.add_argument('--config-sha256')
    cert.add_argument('--build-sha256')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.image, args.deployment, nexus_waterline=args.nexus_waterline,
                solana_waterline=args.solana_waterline, reference_floor=args.reference_floor)
    else:
        print(json.dumps(certificate(
            args.image, args.deployment, args.generation,
            args.config_sha256 or custody_admission.configuration_fingerprint(),
            args.build_sha256 or custody_admission.build_fingerprint(),
            args.rationale,
        ).to_dict(), indent=2))


if __name__ == '__main__':
    main()
