"""Growth drivers for Maple: yield-bearing stablecoins and stablecoin lending.

Onchain, Ethereum (macro_onchain): read from the contracts at the last block of each Sunday (weekly) since 2024, plus today.
  - yield_bearing: ERC-4626 vaults at totalSupply x convertToAssets (sUSDS, sUSDe, sDAI, scrvUSD, sfrxUSD) and BUIDL
    ($1 NAV, totalSupply). syrupUSDC/USDT come from pool_state.
  - supplied / borrowed: Aave v3 and SparkLend (aToken totalSupply; borrowed = aToken supply - underlying cash held by
    the aToken) and Compound v3 (totalSupply / totalBorrow), for USDC, USDT and DAI markets. Maple loans from loan_state.
All chains (llama_lending, DefiLlama): supplied (TVL + borrowed) and borrowed for the 25 largest lending protocols, weekly.
"""
import datetime as dt, requests
from web3 import Web3
from common import db, w3
from fetch_state import block_before

YB = {  # name -> (address, kind)
    "sUSDS": ("0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD", "4626"), "sUSDe": ("0x9D39A5DE30e57443BfF2A8307A4256c8797A3497", "4626"),
    "sDAI": ("0x83F20F44975D03b1b09e64809B757c47f942BEeA", "4626"), "scrvUSD": ("0x0655977FEb2f289A4aB78af67BAB0d17aAb84367", "4626"),
    "sfrxUSD": ("0xcf62F905562626CfcDD2261162a51fd02Fc9c5b6", "4626"), "BUIDL": ("0x7712c34205737192402172409a8F7ccef8aA2AEc", "nav1"),
}
ATOKENS = {  # protocol -> aTokens (USDC, USDT, DAI markets)
    "Aave": ["0x98C23E9d8f34FEFb1B7BD6a91B7FF122F4e16F5c", "0x23878914EFE38d27C4D67Ab83ed1b93A74D4086a", "0x018008bfb33d285247A21d44E50697654f754e63"],
    "Spark": ["0x377C3bd93f2a2984E1E7bE6A5C22c525eD4A4815", "0xe7dF13b8e3d6740fe17CBE928C7334243d86c92f", "0x4DEDf26112B3Ec8eC46e7E31EA5e123490B05B8B"],
}
COMET = {"Compound": ["0xc3d688B66703497DAA19211EEdff47f25384cdc3", "0x3Afdc9BCA9213A35503b077a6072F3D0d5AB0840"]}
SEL = {k: Web3.keccak(text=k)[:4].hex().removeprefix("0x") for k in
       ("totalSupply()", "decimals()", "convertToAssets(uint256)", "UNDERLYING_ASSET_ADDRESS()", "balanceOf(address)", "totalBorrow()")}

def call(to, sig, arg=None, block="latest"):
    data = "0x" + SEL[sig] + ((arg.lower().removeprefix("0x").rjust(64, "0") if isinstance(arg, str) else format(arg, "064x")) if arg is not None else "")
    return int(w3("ethereum").eth.call({"to": Web3.to_checksum_address(to), "data": data}, block).hex() or "0x0", 16)

def onchain_rows(day, blk):
    out, dec = [], {}
    d = lambda a: dec.setdefault(a, call(a, "decimals()"))
    for name, (a, kind) in YB.items():
        try:
            n = call(a, "totalSupply()", block=blk) / 10 ** d(a)
            rate = call(a, "convertToAssets(uint256)", 10 ** d(a), blk) / 10 ** d(a) if kind == "4626" else 1.0
            if n: out.append((day, "yield_bearing", name, n * rate))
        except Exception:
            pass   # not deployed yet
    for proto, toks in ATOKENS.items():
        sup = bor = 0.0
        for a in toks:
            try:
                u = "0x" + format(call(a, "UNDERLYING_ASSET_ADDRESS()"), "040x")
                s = call(a, "totalSupply()", block=blk) / 10 ** d(a); cash = call(u, "balanceOf(address)", a, blk) / 10 ** d(a)
                sup += s; bor += max(s - cash, 0)
            except Exception:
                pass
        if sup: out += [(day, "supplied", proto, sup), (day, "borrowed", proto, bor)]
    for proto, toks in COMET.items():
        sup = bor = 0.0
        for a in toks:
            try:
                sup += call(a, "totalSupply()", block=blk) / 1e6; bor += call(a, "totalBorrow()", block=blk) / 1e6
            except Exception:
                pass
        if sup: out += [(day, "supplied", proto, sup), (day, "borrowed", proto, bor)]
    return out

def llama_lending(conn):
    ps = requests.get("https://api.llama.fi/protocols", timeout=120).json()
    top = sorted([p for p in ps if p.get("category") == "Lending"], key=lambda p: -(p.get("tvl") or 0))[:25]
    rows = []
    for p in top:
        try:
            j = requests.get(f"https://api.llama.fi/protocol/{p['slug']}", timeout=120).json()
        except Exception:
            continue
        tvl = {r["date"]: r["totalLiquidityUSD"] for r in j.get("tvl", [])}
        bor = {r["date"]: r["totalLiquidityUSD"] for r in (j.get("chainTvls", {}).get("borrowed", {}) or {}).get("tvl", [])}
        for ts, v in tvl.items():
            day = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()
            if day.weekday() != 6 or day < dt.date(2022, 1, 1): continue   # Sundays
            b = bor.get(ts, 0) or 0
            rows.append((day, p["name"], v + b, b))
    conn.cursor().executemany("""INSERT INTO llama_lending VALUES (%s,%s,%s,%s) ON CONFLICT (day, protocol) DO UPDATE
        SET supplied_usd=EXCLUDED.supplied_usd, borrowed_usd=EXCLUDED.borrowed_usd""", rows)
    conn.commit(); print(f"llama_lending: {len(rows)} rows, {len(top)} protocols")

def cg_yield_bearing(conn):
    """CoinGecko 'yield-bearing-stablecoins' category: today's top 15 by market cap (all chains), with a year of daily
    market caps for each, so the total matches the figure the SYRUP model uses."""
    import time
    top = requests.get("https://api.coingecko.com/api/v3/coins/markets", params={"vs_currency": "usd", "category": "yield-bearing-stablecoins",
                       "order": "market_cap_desc", "per_page": 15}, timeout=60).json()
    today = dt.datetime.now(dt.timezone.utc).date()
    have = {r[0] for r in conn.execute("SELECT DISTINCT coin FROM cg_yield_bearing WHERE day < %s", (today - dt.timedelta(days=3),)).fetchall()}
    rows = [(today, c["id"], c["symbol"].upper(), c["market_cap"] or 0) for c in top]
    for c in top:
        if c["id"] in have: continue
        for _ in range(4):
            r = requests.get(f"https://api.coingecko.com/api/v3/coins/{c['id']}/market_chart", params={"vs_currency": "usd", "days": 365, "interval": "daily"}, timeout=60)
            if r.status_code == 200: break
            time.sleep(20)
        for ts, mc in r.json().get("market_caps", []):
            if mc: rows.append((dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date(), c["id"], c["symbol"].upper(), mc))
        time.sleep(3)
    conn.cursor().executemany("""INSERT INTO cg_yield_bearing VALUES (%s,%s,%s,%s) ON CONFLICT (day, coin) DO UPDATE SET mcap_usd=EXCLUDED.mcap_usd""", rows)
    conn.commit(); print(f"cg_yield_bearing: {len(rows)} rows, top 15 = ${sum(c['market_cap'] or 0 for c in top)/1e9:.2f}B")

def main():
    conn = db(); today = dt.datetime.now(dt.timezone.utc).date()
    have = {r[0] for r in conn.execute("SELECT DISTINCT day FROM macro_onchain").fetchall()}
    days = [dt.date(2024, 1, 7) + dt.timedelta(weeks=i) for i in range(0, 200)]
    days = [x for x in days if x < today and x not in have] + [today]
    for day in days:
        nxt = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(), dt.timezone.utc)
        blk = w3("ethereum").eth.block_number if day == today else block_before(int(nxt.timestamp()))
        rows = onchain_rows(day, blk)
        conn.execute("DELETE FROM macro_onchain WHERE day=%s", (day,))
        conn.cursor().executemany("INSERT INTO macro_onchain VALUES (%s,%s,%s,%s)", rows); conn.commit()
    print(f"macro_onchain: {len(days)} days")
    cg_yield_bearing(conn)
    # DefiLlama is weekly (Sundays) and heavy: fetch only when the latest Sunday isn't in yet
    sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
    if (conn.execute("SELECT max(day) FROM llama_lending").fetchone()[0] or dt.date(2000, 1, 1)) < sunday:
        llama_lending(conn)

if __name__ == "__main__":
    main()
