"""
Robinhood Chain activity by sampling: SAMPLES blocks per UTC day (evenly spaced), full txs + receipts.
Daily totals are scaled by n_blocks / sampled. Resumable per day. Loads config/rh_labels.csv into rh_labels.
"""
import csv, time, datetime as dt, requests
from concurrent.futures import ThreadPoolExecutor
from web3 import Web3
from common import db, BATCH_RPC, RPC, ROOT

SAMPLES = 200
START = dt.date(2026, 5, 1)
URL = BATCH_RPC["robinhood"]
rh = Web3(Web3.HTTPProvider(RPC["robinhood"], request_kwargs={"timeout": 60}))

def rpc_batch(calls):
    delay = 1
    for _ in range(8):
        r = requests.post(URL, json=calls, timeout=90)
        if r.status_code == 429: time.sleep(delay); delay = min(delay * 2, 30); continue
        r.raise_for_status(); out = r.json()
        if any("result" not in x for x in out): time.sleep(delay); delay = min(delay * 2, 30); continue
        return {x["id"]: x["result"] for x in out}
    raise RuntimeError("rpc batch failed")

_bc = {}
def block_before(ts):
    if ts in _bc: return _bc[ts]
    lo, hi = 1, rh.eth.block_number
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if rh.eth.get_block(mid).timestamp < ts: lo = mid
        else: hi = mid - 1
    _bc[ts] = lo; return lo

def day_ranges(conn):
    today = dt.datetime.now(dt.timezone.utc).date()
    have = {r[0]: r for r in conn.execute("SELECT day, first_block, last_block FROM rh_day_blocks")}
    day = START
    while day < today:
        if day not in have:
            t0 = int(dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp())
            t1 = int(dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.timezone.utc).timestamp())
            f, l = block_before(t0) + 1, block_before(t1)
            conn.execute("INSERT INTO rh_day_blocks VALUES (%s,%s,%s,%s,0) ON CONFLICT DO NOTHING", (day, f, l, l - f + 1)); conn.commit()
            print(f"{day}: blocks {f:,}-{l:,} ({l-f+1:,})")
        day += dt.timedelta(days=1)

def sample_day(conn, day, f, l):
    n = l - f + 1
    blocks = sorted(set(f + (i * n) // SAMPLES for i in range(SAMPLES))) if n > SAMPLES else list(range(f, l + 1))
    done = {r[0] for r in conn.execute("SELECT block_number FROM rh_block_samples WHERE day=%s", (day,))}
    blocks = [b for b in blocks if b not in done]
    if not blocks: return 0
    def one(chunk):
        calls = [{"jsonrpc": "2.0", "id": f"b{b}", "method": "eth_getBlockByNumber", "params": [hex(b), True]} for b in chunk] + \
                [{"jsonrpc": "2.0", "id": f"r{b}", "method": "eth_getBlockReceipts", "params": [hex(b)]} for b in chunk]
        res = rpc_batch(calls)
        rows, tos = [], []
        for b in chunk:
            blk, rcs = res[f"b{b}"], res[f"r{b}"] or []
            txs = blk["transactions"]; base = int(blk.get("baseFeePerGas", "0x0"), 16)
            fees = sum(int(x["gasUsed"], 16) * int(x["effectiveGasPrice"], 16) for x in rcs) / 1e18
            l1 = sum(int(x.get("gasUsedForL1", "0x0"), 16) for x in rcs)
            rows.append((b, day, dt.datetime.fromtimestamp(int(blk["timestamp"], 16), dt.timezone.utc), len(txs),
                         len({t["from"] for t in txs}), int(blk["gasUsed"], 16), base, fees, l1))
            agg = {}
            for t, x in zip(txs, rcs):
                to = (t.get("to") or "create").lower()
                a = agg.setdefault(to, [0, 0, 0.0]); a[0] += 1; a[1] += int(x["gasUsed"], 16); a[2] += int(x["gasUsed"], 16) * int(x["effectiveGasPrice"], 16) / 1e18
            tos += [(b, to, v[0], v[1], v[2]) for to, v in agg.items()]
        return rows, tos
    chunks = [blocks[i:i+5] for i in range(0, len(blocks), 5)]
    got = 0
    with ThreadPoolExecutor(2) as ex:
        for rows, tos in ex.map(one, chunks):
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO rh_block_samples VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", rows)
                cur.executemany("INSERT INTO rh_block_to VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", tos)
            conn.commit(); got += len(rows)
    conn.execute("UPDATE rh_day_blocks SET sampled=(SELECT count(*) FROM rh_block_samples WHERE day=%s) WHERE day=%s", (day, day)); conn.commit()
    return got

def main():
    with db() as conn:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO rh_labels VALUES (%s,%s,%s) ON CONFLICT (address) DO UPDATE SET label=EXCLUDED.label, kind=EXCLUDED.kind",
                            [(r["address"].lower(), r["label"], r["kind"]) for r in csv.DictReader(open(ROOT / "config" / "rh_labels.csv"))])
        conn.commit()
        day_ranges(conn)
        for day, f, l, n, s in conn.execute("SELECT * FROM rh_day_blocks WHERE sampled < LEAST(%s, n_blocks) ORDER BY day", (SAMPLES,)).fetchall():
            with db() as c2:
                got = sample_day(c2, day, f, l)
            print(f"{day}: +{got} blocks sampled")

if __name__ == "__main__":
    main()
