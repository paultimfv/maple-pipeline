"""
Backfill raw event logs for every tracked Maple event into DuckDB.
Resumable: progress is checkpointed per event after every chunk.

usage: python pipeline/fetch_logs.py            # all events
       python pipeline/fetch_logs.py Deposit    # one event by name
"""
import sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import duckdb
from web3 import Web3
from common import RPC_URL, DB_PATH, load_contracts, tracked_events

CHUNK = 100_000          # blocks per eth_getLogs call; halves on provider error
MIN_CHUNK = 2_000

assert RPC_URL, "set RPC_URL in .env"
w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 60}))
db = duckdb.connect(str(DB_PATH))

db.execute("""
CREATE TABLE IF NOT EXISTS raw_logs (
  address VARCHAR, topic0 VARCHAR, topics VARCHAR[], data VARCHAR,
  block_number BIGINT, tx_hash VARCHAR, log_index INTEGER,
  PRIMARY KEY (tx_hash, log_index))""")
db.execute("CREATE TABLE IF NOT EXISTS checkpoint (event_key VARCHAR PRIMARY KEY, last_block BIGINT)")
db.execute("CREATE TABLE IF NOT EXISTS blocks (block_number BIGINT PRIMARY KEY, block_time TIMESTAMP)")

_bcache = {}
def block_at(ts):
    """Binary-search the first block at or after a unix timestamp."""
    if ts in _bcache: return _bcache[ts]
    lo, hi = 1, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi) // 2
        if w3.eth.get_block(mid).timestamp < ts: lo = mid + 1
        else: hi = mid
    _bcache[ts] = lo
    return lo

def start_block_for(emitters, contracts):
    dates = [contracts[a]["first_seen"] for a in emitters if a in contracts and contracts[a].get("first_seen")]
    first = min(dates) if dates else "2022-01-01"
    ts = int(dt.datetime.fromisoformat(first).replace(tzinfo=dt.timezone.utc).timestamp()) - 86400
    return block_at(ts)

def fetch(event, contracts, head):
    key = f'{event["contract_type"]}.{event["event"]}'
    emitters = [Web3.to_checksum_address(a) for a in event["emitter_addresses"]]
    if not emitters:
        print(f"{key}: no emitters, skip"); return
    row = db.execute("SELECT last_block FROM checkpoint WHERE event_key=?", [key]).fetchone()
    frm = row[0] + 1 if row else start_block_for(event["emitter_addresses"], contracts)
    chunk, total = CHUNK, 0
    print(f"{key}: {len(emitters)} emitters, blocks {frm:,} -> {head:,}")
    while frm <= head:
        to = min(frm + chunk - 1, head)
        try:
            logs = w3.eth.get_logs({"address": emitters, "topics": [event["topic0"]], "fromBlock": frm, "toBlock": to})
        except Exception as e:
            if chunk > MIN_CHUNK:
                chunk //= 2; continue
            print(f"  error at {frm}: {e}"); time.sleep(5); continue
        if logs:
            db.executemany("INSERT OR IGNORE INTO raw_logs VALUES (?,?,?,?,?,?,?)", [
                (l["address"].lower(), l["topics"][0].hex() if hasattr(l["topics"][0], "hex") else l["topics"][0],
                 [t.hex() if hasattr(t, "hex") else t for t in l["topics"]],
                 l["data"].hex() if hasattr(l["data"], "hex") else l["data"],
                 l["blockNumber"], l["transactionHash"].hex(), l["logIndex"]) for l in logs])
            total += len(logs)
        db.execute("INSERT OR REPLACE INTO checkpoint VALUES (?,?)", [key, to])
        print(f"  {to:,}  +{len(logs)}  (chunk {chunk:,})", end="\r")
        frm = to + 1
        if len(logs) < 2000 and chunk < CHUNK: chunk *= 2
    print(f"\n{key}: done, {total} new logs")

def backfill_block_times():
    missing = [r[0] for r in db.execute(
        "SELECT DISTINCT block_number FROM raw_logs WHERE block_number NOT IN (SELECT block_number FROM blocks)").fetchall()]
    if not missing: return
    print(f"block timestamps: {len(missing):,} to fetch")
    def one(n): return (n, dt.datetime.fromtimestamp(w3.eth.get_block(n).timestamp, dt.timezone.utc))
    with ThreadPoolExecutor(8) as ex:
        buf = []
        for i, rec in enumerate(ex.map(one, missing), 1):
            buf.append(rec)
            if len(buf) >= 500 or i == len(missing):
                db.executemany("INSERT OR IGNORE INTO blocks VALUES (?,?)", buf); buf = []
                print(f"  {i:,}/{len(missing):,}", end="\r")
    print()

if __name__ == "__main__":
    contracts = load_contracts()
    head = w3.eth.block_number
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for ev in tracked_events():
        if only and only.lower() not in ev["event"].lower(): continue
        fetch(ev, contracts, head)
    backfill_block_times()
    n = db.execute("SELECT count(*) FROM raw_logs").fetchone()[0]
    print(f"raw_logs total: {n:,}")
