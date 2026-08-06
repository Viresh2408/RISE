#!/usr/bin/env python3
"""Audit Log Hash Chain Verification Script.

Usage:
    python scripts/verify_chain.py --tenant-id <tenant_uuid> [--db-url <postgres_url>]

Exits with:
    0 if the audit event hash chain is valid (or empty)
    1 if hash chain tampering or corruption is detected
"""

import sys
import os
import argparse
from pathlib import Path

# Add project root and packages/rise-core to Python path
root_dir = Path(__file__).resolve().parents[1]
rise_core_dir = root_dir / "packages" / "rise-core"
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(rise_core_dir) not in sys.path:
    sys.path.insert(0, str(rise_core_dir))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import verify_hash_chain


def main():
    parser = argparse.ArgumentParser(description="Verify audit_events hash chain integrity for a tenant.")
    parser.add_argument("--tenant-id", required=True, help="Tenant UUID to verify")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/rise_dev"),
        help="PostgreSQL connection URL",
    )
    args = parser.parse_args()

    engine = create_engine(args.db_url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        valid, bad_event, msg = verify_hash_chain(session, args.tenant_id)
        if valid:
            print(f"SUCCESS: Audit log hash chain for tenant {args.tenant_id} is VALID. ({msg})")
            sys.exit(0)
        else:
            print(f"VERIFICATION FAILURE: Audit log hash chain for tenant {args.tenant_id} is TAMPERED / INVALID!")
            print(f"Details: {msg}")
            if bad_event:
                print(f"Corrupted event ID: {bad_event.id}, seq: {bad_event.seq}, action: {bad_event.action}")
            sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
