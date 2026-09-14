"""Shared config loading for the maple pipeline."""
import csv, json, os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

RPC_URL = os.environ.get("RPC_URL", "")
DB_PATH = ROOT / "db" / "maple.duckdb"
CSV_DIR = Path(os.environ.get("DUNE_CSV_DIR", ""))

def load_abis():
    return json.load(open(ROOT / "config" / "abis.json"))

def load_contracts():
    rows = list(csv.DictReader(open(ROOT / "config" / "contracts.csv")))
    rows += [{"address": r["address"], "contract_type": "MapleLoan", "pool_group": "(fixed-term loan)",
              "decimals": r["decimals"], "first_seen": r["first_seen"]}
             for r in csv.DictReader(open(ROOT / "config" / "fixed_term_loans.csv"))]
    return {r["address"].lower(): r for r in rows}

def tracked_events():
    """The events that back a Dune table, with their emitter sets."""
    abis = load_abis()
    return [e for e in abis["events"] if e.get("dune_table")]
