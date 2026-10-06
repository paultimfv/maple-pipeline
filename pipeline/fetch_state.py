"""
Pool state via eth_call (Alchemy) -> pool_state. Resumable.
  - every Maple pool in the registry: totalAssets / totalSupply at each month-end since 2023 (AUM history)
  - live pools: daily since syrupUSDG launched (2026-05-25)
  - SYRUP: totalSupply and the balances held by Maple-controlled wallets -> syrup_supply
pool key = pool_group from config/contracts.csv ('syrupUSDC', 'syrupUSDG', ...). Amounts in the pool asset
(6-dec pools = USD; 18-dec pools are WETH and are excluded from USD AUM).
"""
import datetime as dt
from web3 import Web3
from common import db, ETH_CALL_RPC, pools, SYRUP_TOKEN, SYRUP_NONCIRC

HISTORY_START = dt.date(2023, 1, 1)
DAILY_START = dt.date(2026, 5, 25)
LIVE = {"syrupUSDC", "syrupUSDT", "syrupUSDG", "Maple Institutional - Secured Lending"}
ABI = [{"name": n, "type": "function", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view"}
       for n in ("totalAssets", "totalSupply")] + \
      [{"name": "balanceOf", "type": "function", "inputs": [{"type": "address"}], "outputs": [{"type": "uint256"}], "stateMutability": "view"}]

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

def snapshot_days(today):
    """Month-ends since HISTORY_START, every day since DAILY_START, and today."""
    days, d = [], HISTORY_START
    while d < today:
        nxt = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        days.append(nxt - dt.timedelta(days=1)); d = nxt
    d = DAILY_START
    while d <= today:
        days.append(d); d += dt.timedelta(days=1)
    return sorted({x for x in days if x <= today})

def block_for(day, today):
    if day == today: return w3.eth.block_number
    nxt = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.timezone.utc)
    return block_before(int(nxt.timestamp()))

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    days = snapshot_days(today)
    month_ends = {d for d in days if (d + dt.timedelta(days=1)).day == 1}
    with db() as conn:
        done = {(r[0], r[1]) for r in conn.execute("SELECT day, pool FROM pool_state")}
        for addr, (name, group, dec) in pools().items():
            if group == "(derived only)": continue
            c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI)
            for day in days:
                if day not in month_ends and day != today and group not in LIVE: continue
                if (day, group) in done and day != today: continue
                blk = block_for(day, today)
                try:
                    ta = c.functions.totalAssets().call(block_identifier=blk)
                    ts = c.functions.totalSupply().call(block_identifier=blk)
                except Exception:
                    continue   # not deployed yet at this block
                conn.execute("""INSERT INTO pool_state VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (day,pool) DO UPDATE SET block_number=EXCLUDED.block_number,
                    total_assets=EXCLUDED.total_assets, total_supply=EXCLUDED.total_supply, exch_rate=EXCLUDED.exch_rate""",
                    (day, group, blk, ta / 10 ** dec, ts / 10 ** dec, (ta / ts) if ts else 1.0))
                conn.commit()
                print(f"{group[:28]:28s} {day} {ta / 10 ** dec:>16,.0f}", end="\r")
        print()

        # SYRUP supply: month-ends + daily window, as above
        syrup = w3.eth.contract(address=Web3.to_checksum_address(SYRUP_TOKEN), abi=ABI)
        done = {r[0] for r in conn.execute("SELECT day FROM syrup_supply")}
        for day in days:
            if day < dt.date(2024, 11, 1) or (day in done and day != today): continue   # SYRUP token from Nov 2024
            blk = block_for(day, today)
            try: total = syrup.functions.totalSupply().call(block_identifier=blk) / 1e18
            except Exception: continue
            held = sum(syrup.functions.balanceOf(Web3.to_checksum_address(a)).call(block_identifier=blk) / 1e18
                       for a in SYRUP_NONCIRC.values())
            conn.execute("""INSERT INTO syrup_supply VALUES (%s,%s,%s,%s) ON CONFLICT (day) DO UPDATE SET
                block_number=EXCLUDED.block_number, total_supply=EXCLUDED.total_supply, maple_held=EXCLUDED.maple_held""",
                (day, blk, total, held))
            conn.commit()
        print(conn.execute("SELECT count(DISTINCT pool), count(*), max(day) FROM pool_state").fetchone(),
              conn.execute("SELECT count(*), max(day) FROM syrup_supply").fetchone())

if __name__ == "__main__":
    main()
