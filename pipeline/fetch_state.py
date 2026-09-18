"""
Daily pool state via eth_call at the last block of each UTC day (Alchemy).
totalAssets / totalSupply on the syrupUSDG pool -> pool_state. Resumable.
"""
import datetime as dt
from web3 import Web3
from common import db, ETH_CALL_RPC, SYRUPUSDG_POOL

POOLS = {"syrupUSDG": SYRUPUSDG_POOL}
START = dt.date(2026, 5, 25)
ABI = [{"name": n, "type": "function", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view"}
       for n in ("totalAssets", "totalSupply")]

w3 = Web3(Web3.HTTPProvider(ETH_CALL_RPC, request_kwargs={"timeout": 60}))
_cache = {}
def block_before(ts):
    """Last block with timestamp < ts (binary search, cached)."""
    if ts in _cache: return _cache[ts]
    lo, hi = 1, w3.eth.block_number
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if w3.eth.get_block(mid).timestamp < ts: lo = mid
        else: hi = mid - 1
    _cache[ts] = lo
    return lo

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    with db() as conn:
        done = {(r[0], r[1]) for r in conn.execute("SELECT day, pool FROM pool_state")}
        for pool, addr in POOLS.items():
            c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI)
            day = START
            while day <= today:
                if (day, pool) not in done or day == today:   # always refresh today
                    if day == today:
                        blk = w3.eth.block_number
                    else:
                        nxt = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.timezone.utc)
                        blk = block_before(int(nxt.timestamp()))
                    ta = c.functions.totalAssets().call(block_identifier=blk)
                    ts = c.functions.totalSupply().call(block_identifier=blk)
                    conn.execute("""INSERT INTO pool_state VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (day,pool) DO UPDATE SET block_number=EXCLUDED.block_number,
                        total_assets=EXCLUDED.total_assets, total_supply=EXCLUDED.total_supply, exch_rate=EXCLUDED.exch_rate""",
                        (day, pool, blk, ta / 1e6, ts / 1e6, (ta / ts) if ts else 1.0))
                    conn.commit()
                    print(f"{pool} {day} blk {blk} tvl {ta/1e6:,.0f} rate {ta/ts if ts else 1:.5f}", end="\r")
                day += dt.timedelta(days=1)
        print()
        print(conn.execute("SELECT pool, count(*), max(day), max(exch_rate) FROM pool_state GROUP BY 1").fetchall())

if __name__ == "__main__":
    main()
