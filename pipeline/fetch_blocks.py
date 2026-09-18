"""
Block timestamps. Ethereum: exact, per block (few hundred). Robinhood: exact anchors on a grid,
then linear interpolation for the ~270k blocks referenced by Morpho logs (daily buckets only need
minute-level accuracy). Anchor grid is finer for the sparse early chain (< 1M blocks).
"""
import time, datetime as dt, requests
from concurrent.futures import ThreadPoolExecutor
from common import db, BATCH_RPC, RPC

def get_block_times(url, nums, batch=10, threads=2):
    """Batched eth_getBlockByNumber with backoff. Returns {block: datetime}."""
    out = {}
    def one(chunk):
        body = [{"jsonrpc": "2.0", "id": i, "method": "eth_getBlockByNumber", "params": [hex(n), False]} for i, n in enumerate(chunk)]
        delay = 1
        for _ in range(8):
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 429:
                time.sleep(delay); delay = min(delay * 2, 30); continue
            r.raise_for_status()
            items = r.json()
            if not isinstance(items, list) or any(not x.get("result") for x in items):
                # per-item rate-limit errors come back as HTTP 200 -> retry the whole batch
                time.sleep(delay); delay = min(delay * 2, 30); continue
            return {int(x["result"]["number"], 16): dt.datetime.fromtimestamp(int(x["result"]["timestamp"], 16), dt.timezone.utc)
                    for x in items}
        raise RuntimeError(f"rate limited at {chunk[0]}")
    chunks = [nums[i:i+batch] for i in range(0, len(nums), batch)]
    with ThreadPoolExecutor(threads) as ex:
        for i, res in enumerate(ex.map(one, chunks), 1):
            out.update(res); print(f"  anchors {len(out):,}/{len(nums):,}", end="\r")
    print()
    return out

def missing_blocks(conn, chain):
    return [r[0] for r in conn.execute("""
        SELECT DISTINCT r.block_number FROM raw_logs r
        LEFT JOIN blocks b ON b.chain=r.chain AND b.block_number=r.block_number
        WHERE r.chain=%s AND b.block_number IS NULL ORDER BY 1""", (chain,)).fetchall()]

def insert(_conn, chain, mapping):
    """Fresh connection + COPY into a temp table (psycopg executemany/pipeline misbehaves on Neon)."""
    with db() as c:
        with c.cursor() as cur:
            cur.execute("CREATE TEMP TABLE tb (chain text, block_number bigint, block_time timestamptz) ON COMMIT DROP")
            with cur.copy("COPY tb (chain, block_number, block_time) FROM STDIN") as cp:
                for n, t in mapping.items():
                    cp.write_row((chain, n, t))
            cur.execute("INSERT INTO blocks SELECT * FROM tb ON CONFLICT DO NOTHING")
        c.commit()

def main():
    with db() as conn:
        # ethereum: exact
        miss = missing_blocks(conn, "ethereum")
        if miss:
            print(f"ethereum: {len(miss):,} blocks exact")
            insert(conn, "ethereum", get_block_times(BATCH_RPC["ethereum"], miss, batch=10, threads=2))

        # robinhood: anchors + interpolation
        miss = missing_blocks(conn, "robinhood")
        if not miss: return
        lo, hi = miss[0], miss[-1]
        grid = set()
        n = lo
        while n <= hi:
            grid.add(n); n += 1_000 if n < 1_000_000 else 10_000
        grid.update([lo, hi])
        # exact for the small sets (syrup/USDG mints+burns, markets); Morpho + Earn vault rows are interpolated
        exact = [r[0] for r in conn.execute("""
            SELECT DISTINCT r.block_number FROM raw_logs r
            LEFT JOIN blocks b ON b.chain=r.chain AND b.block_number=r.block_number
            WHERE r.chain='robinhood' AND b.block_number IS NULL AND r.address NOT IN (%s, %s)""",
            ("0x9d53d5e3bd5e8d4cbfa6db1ca238aea02e651010", "0xbeeff033f34c046626b8d0a041844c5d1a5409dd")).fetchall()]
        grid.update(exact)
        print(f"robinhood: {len(miss):,} blocks, {len(grid):,} anchors")
        anchors = get_block_times(BATCH_RPC["robinhood"], sorted(grid), batch=10, threads=2)
        insert(conn, "robinhood", anchors)
        ak = sorted(anchors)
        import bisect
        interp = {}
        for b in miss:
            if b in anchors: continue
            i = bisect.bisect_left(ak, b)
            a0, a1 = ak[max(i-1, 0)], ak[min(i, len(ak)-1)]
            if a1 == a0: interp[b] = anchors[a0]; continue
            t0, t1 = anchors[a0], anchors[a1]
            interp[b] = t0 + (t1 - t0) * ((b - a0) / (a1 - a0))
        insert(conn, "robinhood", interp)
        print(f"robinhood: {len(anchors):,} exact + {len(interp):,} interpolated")

if __name__ == "__main__":
    main()
