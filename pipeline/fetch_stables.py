"""Stablecoin supply on Robinhood Chain: totalSupply() eth_call per token at the last indexed block of each UTC day -> rh_stable_supply.
Canonical contracts only (Blockscout search is full of fakes named USDG/USDC). spUSDG wraps USDG — shown, not summed."""
import datetime as dt
from web3 import Web3
from common import db, BATCH_RPC, RH_USDG

TOKENS = {  # symbol: (address, decimals, kind)
    "USDG":      (RH_USDG, 6, "stablecoin"),
    "USDe":      ("0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34", 18, "stablecoin"),
    "syrupUSDG": ("0x40858070814a57fdf33a613ae84fe0a8b4a874f7", 6, "yield-bearing"),
    "mGLO":      ("0xfed493f38c1aacb4ea4e6a11f8b9287849ee0096", 18, "yield-bearing"),
    "spUSDG":    ("0xde770c84fe66e063336b31737cfe9790f18c4087", 6, "wrapper"),
}
ABI = [{"name": "totalSupply", "type": "function", "inputs": [], "outputs": [{"type": "uint256"}], "stateMutability": "view"}]
START = dt.date(2026, 5, 11)

w3 = Web3(Web3.HTTPProvider(BATCH_RPC["robinhood"], request_kwargs={"timeout": 60}))

def main():
    today = dt.datetime.now(dt.timezone.utc).date()
    with db() as conn:   # read what we need, then close: Neon drops connections idle during long RPC loops
        done = {(r[0], r[1]) for r in conn.execute("SELECT day, token FROM rh_stable_supply")}
        # last indexed Robinhood block per day (blocks table is sampled; good to within minutes)
        day_blk = dict(conn.execute("SELECT block_time::date, MAX(block_number) FROM blocks WHERE chain='robinhood' GROUP BY 1").fetchall())
    head = w3.eth.block_number
    for sym, (addr, dec, kind) in TOKENS.items():
        c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=ABI)
        rows, day = [], START
        while day <= today:
            if (day, sym) not in done or day == today:
                blk = head if day == today else day_blk.get(day)
                if blk:
                    try: sup = c.functions.totalSupply().call(block_identifier=blk) / 10 ** dec
                    except Exception: sup = 0.0   # contract not deployed yet at that block
                    rows.append((day, sym, kind, blk, sup)); print(f"{sym} {day} {sup:,.0f}", end="\r")
            day += dt.timedelta(days=1)
        with db() as conn:
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO rh_stable_supply VALUES (%s,%s,%s,%s,%s) ON CONFLICT (day, token) DO UPDATE SET
                    block_number=EXCLUDED.block_number, supply=EXCLUDED.supply""", rows)
            conn.commit()
    print()
    with db() as conn: print(conn.execute("SELECT token, MAX(day), MAX(supply) FROM rh_stable_supply GROUP BY 1 ORDER BY 3 DESC").fetchall())

if __name__ == "__main__":
    main()
