"""
Backfill raw event logs (dashboard scope) into Postgres. Resumable per event key.

usage: python pipeline/fetch_logs.py              # all
       python pipeline/fetch_logs.py rh.          # keys containing 'rh.'
"""
import sys, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor
from web3 import Web3
from common import db, w3, tracked_events, BATCH_RPC

CHUNK = {"ethereum": 100_000, "robinhood": 2_000_000}
MIN_CHUNK = 2_000

def h(x): return x.hex() if hasattr(x, "hex") else x
def hx(x):
    s = h(x); return s if s.startswith("0x") else "0x" + s

def fetch(ev, conn):
    chain, key = ev["chain"], ev["key"]
    node = w3(chain); head = node.eth.block_number
    row = conn.execute("SELECT last_block FROM checkpoint WHERE event_key=%s", (key,)).fetchone()
    frm = row[0] + 1 if row else ev["from_block"]
    chunk, total = CHUNK[chain], 0
    topics = [hx(ev["topic0"])] + ev.get("extra_topics", [])
    flt = {"topics": topics}
    addrs = ev["addresses"]
    if addrs == "STOCK_TOKENS":
        from common import stock_tokens; addrs = stock_tokens()
    if addrs:
        flt["address"] = [Web3.to_checksum_address(a) for a in addrs]
    print(f"{key}: blocks {frm:,} -> {head:,}")
    while frm <= head:
        to = min(frm + chunk - 1, head)
        try:
            logs = node.eth.get_logs({**flt, "fromBlock": frm, "toBlock": to})
        except Exception as e:
            if chunk > MIN_CHUNK:
                chunk //= 2; continue
            print(f"  error at {frm}: {str(e)[:120]}"); time.sleep(5); continue
        if logs:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO raw_logs VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    [(chain, l["address"].lower(), hx(l["topics"][0]), [hx(t) for t in l["topics"]],
                      hx(l["data"]), l["blockNumber"], hx(l["transactionHash"]), l["logIndex"]) for l in logs])
            total += len(logs)
        conn.execute("INSERT INTO checkpoint VALUES (%s,%s) ON CONFLICT (event_key) DO UPDATE SET last_block=EXCLUDED.last_block", (key, to))
        conn.commit()
        print(f"  {to:,}  +{len(logs)}  (chunk {chunk:,})", end="\r")
        frm = to + 1
        if len(logs) < 2000 and chunk < CHUNK[chain]: chunk *= 2
    print(f"\n{key}: done, {total} new logs")

def backfill_block_times(conn):
    """Batched eth_getBlockByNumber via Alchemy (50 per request)."""
    import requests
    for chain in ("ethereum", "robinhood"):
        missing = [r[0] for r in conn.execute("""
            SELECT DISTINCT r.block_number FROM raw_logs r
            LEFT JOIN blocks b ON b.chain=r.chain AND b.block_number=r.block_number
            WHERE r.chain=%s AND b.block_number IS NULL""", (chain,)).fetchall()]
        if not missing: continue
        print(f"{chain} block timestamps: {len(missing):,} to fetch")
        url = BATCH_RPC[chain]
        def one_batch(nums):
            body = [{"jsonrpc": "2.0", "id": i, "method": "eth_getBlockByNumber", "params": [hex(n), False]} for i, n in enumerate(nums)]
            for _ in range(6):
                try:
                    r = requests.post(url, json=body, timeout=60); r.raise_for_status()
                    out = {}
                    for item in r.json():
                        res = item.get("result")
                        if res: out[int(res["number"], 16)] = dt.datetime.fromtimestamp(int(res["timestamp"], 16), dt.timezone.utc)
                    return [(chain, n, t) for n, t in out.items()]
                except Exception as e:
                    time.sleep(2)
            raise RuntimeError(f"batch failed at {nums[0]}")
        batches = [missing[i:i+50] for i in range(0, len(missing), 50)]
        done = 0
        with ThreadPoolExecutor(6) as ex:
            for recs in ex.map(one_batch, batches):
                with conn.cursor() as cur:
                    cur.executemany("INSERT INTO blocks VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", recs)
                conn.commit(); done += len(recs)
                print(f"  {done:,}/{len(missing):,}", end="\r")
        print()

if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    with db() as conn:
        for ev in tracked_events():
            if only and only not in ev["key"]: continue
            fetch(ev, conn)
        backfill_block_times(conn)
        for chain, n in conn.execute("SELECT chain, count(*) FROM raw_logs GROUP BY 1"):
            print(f"raw_logs {chain}: {n:,}")
