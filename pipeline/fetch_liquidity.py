"""
Maple's pool liquidity profile (public GraphQL, PoolV2.liquidity; docs.maple.finance "Tracking Liquidity").
How much of each syrup pool can come back, and how fast: sources by time window (idle cash, DeFi, DEX LP, loans by
days to call/maturity, US Treasuries, trading), interest due per window, and the withdrawal queue + 12-month
processing stats. Maple computes it offchain (loan call/maturity dates, strategy positions); one snapshot per hour.

  pool_liquidity           rows behind the transparency page's Liquidity table
  pool_liquidity_interest  interest due on top, per window
  pool_withdrawal_queue    pending withdrawals and how fast they were processed
"""
import datetime as dt, requests
from common import db

URL = "https://api.maple.finance/v2/graphql"
POOLS = {"0x80ac24aa929eaf5013f6436cda2a7ba190f5cc0b": "syrupUSDC",
         "0x356b8d89c1e1239cbbb9de4815c39a1474d5ba7d": "syrupUSDT",
         "0x87b65c4aaffa76881f9e96f3e7ed945ddfc3cd7a": "syrupUSDG"}
Q = """{ poolV2S(where: {id_in: [%s]}) { id totalAssets liquidity {
  sources { category name detail timing window windowOrder loanCount amount cumulativeAmount pctOfTotalAssets cumulativePct order }
  interestDue { window windowOrder loanCount amount cumulativeAmount }
  withdrawalQueue { pendingAmount asOf total medianMinutes within24h within3d within7d within14d within24hPct within3dPct within7dPct within14dPct } } } }""" % ",".join(f'"{a}"' for a in POOLS)
U = lambda v: int(v or 0) / 1e6          # USDC, USDT, USDG: 6 decimals

def main():
    r = requests.post(URL, json={"query": Q}, timeout=180, headers={"User-Agent": "maple-pipeline"})
    pools = r.json()["data"]["poolV2S"]          # can take ~1 min: Maple builds it on request
    ts = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    src, intr, wq = [], [], []
    for p in pools:
        name, L = POOLS[p["id"].lower()], p["liquidity"]
        for s in L["sources"]:
            src.append((ts, name, s["order"], s["category"], s["name"], s["detail"], s["timing"], s["window"], s["windowOrder"],
                        s["loanCount"], U(s["amount"]), U(s["cumulativeAmount"]), s["pctOfTotalAssets"], s["cumulativePct"]))
        for i in L["interestDue"]:
            intr.append((ts, name, i["window"], i["windowOrder"], i["loanCount"], U(i["amount"]), U(i["cumulativeAmount"])))
        w = L["withdrawalQueue"] or {}
        wq.append((ts, name, U(p["totalAssets"]), U(w.get("pendingAmount")),
                   dt.datetime.fromtimestamp(w["asOf"], dt.timezone.utc) if w.get("asOf") else None,
                   w.get("total"), w.get("medianMinutes"), w.get("within24h"), w.get("within3d"), w.get("within7d"), w.get("within14d"),
                   w.get("within24hPct"), w.get("within3dPct"), w.get("within7dPct"), w.get("within14dPct")))
    with db() as conn:
        c = conn.cursor()
        for t in ("pool_liquidity", "pool_liquidity_interest", "pool_withdrawal_queue"):
            c.execute(f"DELETE FROM {t} WHERE ts = %s", (ts,))
        c.executemany("INSERT INTO pool_liquidity VALUES (" + ",".join(["%s"] * 14) + ")", src)
        c.executemany("INSERT INTO pool_liquidity_interest VALUES (%s,%s,%s,%s,%s,%s,%s)", intr)
        c.executemany("INSERT INTO pool_withdrawal_queue VALUES (" + ",".join(["%s"] * 15) + ")", wq)
        conn.commit()
        for row in conn.execute("""SELECT pool, window_name, round(max(cumulative_usd)/1e6, 1) FROM pool_liquidity WHERE ts=%s
                                   GROUP BY 1, 2, window_order ORDER BY 1, window_order""", (ts,)):
            print("pool_liquidity", *row)

if __name__ == "__main__":
    main()
