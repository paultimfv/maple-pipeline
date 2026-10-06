"""
Maple's transparency page (maple.finance/transparency) -> Maple-reported series. The page server-renders its chart data
into Astro island props, so one GET returns full history. Maple is the only source for anything offchain
(OTC desk revenue, collateral at custodians, the Syrup Strategic Fund wallet), so these are labelled Maple-reported.

  maple_reported_revenue  monthly protocol revenue (onchain + offchain). Reconciles to our onchain fees + published OTC
  maple_reported_aum      daily AUM (deposits + collateral) and deposits, per product, since 2023-01-25
  ssf_daily               Syrup Strategic Fund: SYRUP held (tokens) and liquid assets (USD), since 2025-08-13
  syrup_buybacks          monthly buybacks (replaces the hand-typed CSV)
  maple_balance_sheet     latest SYRUP + liquid assets held by Maple
"""
import datetime as dt, html, json, re, requests
from common import db

URL = "https://maple.finance/transparency"
PRODUCTS = ("syrupUSDC", "syrupUSDT", "syrupUSDG", "mapleInstitutional")

def unwrap(v):
    """Astro serialises props as [0, scalar] / [1, array]; [0] alone = undefined."""
    if isinstance(v, list) and len(v) == 1 and isinstance(v[0], int):
        return None
    if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int):
        k, x = v
        return [unwrap(i) for i in x] if k == 1 else unwrap(x)
    if isinstance(v, dict):
        return {a: unwrap(b) for a, b in v.items()}
    return v

def islands(page):
    out = {}
    for url, props in re.findall(r'<astro-island[^>]*component-url="([^"]+)"[^>]*props="([^"]*)"', page):
        out[url.split("/")[-1].split(".")[0]] = unwrap(json.loads(html.unescape(props)))
    return out

D = lambda ts: dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
money = lambda s: float(str(s).replace("$", "").replace(",", "") or 0)

def main():
    page = requests.get(URL, timeout=90, headers={"User-Agent": "Mozilla/5.0 (maple-pipeline)"}).text
    isl = islands(page)
    rev = [(D(r["ts"]), r["revenueUsd"]) for r in isl["RevChartInner"]["datasets"]["ALL"]]
    aum = {D(r["ts"]): r for r in isl["AUMChartInner"]["datasets"]["ALL"]}
    dep = {D(r["ts"]): r for r in isl["DepositsChartInner"]["datasets"]["ALL"]}
    pools = [(d, p, aum[d].get(p) or 0, dep.get(d, {}).get(p) or 0) for d in aum for p in PRODUCTS]
    ssf = [(D(r["ts"]), r["syrupHoldings"], r["liquidAssetsUsd"]) for r in isl["SsfChartInner"]["datasets"]["ALL"]]
    bb = [(dt.datetime.strptime(r["date"], "%b %Y").date(), money(r["amountUsd"]), money(r["syrupAcquired"]), money(r["avgPrice"]) or None)
          for r in isl["BuybacksTableInner"]["rows"]]
    bs = isl["FinancialsModals"]["balanceSheetData"]
    today = dt.datetime.now(dt.timezone.utc).date()
    with db() as conn:
        cur = conn.cursor()
        cur.executemany("INSERT INTO maple_reported_revenue VALUES (%s,%s) ON CONFLICT (month) DO UPDATE SET revenue_usd=EXCLUDED.revenue_usd", rev)
        cur.executemany("""INSERT INTO maple_reported_aum VALUES (%s,%s,%s,%s) ON CONFLICT (day, product) DO UPDATE
                           SET aum_usd=EXCLUDED.aum_usd, deposits_usd=EXCLUDED.deposits_usd""", pools)
        cur.executemany("""INSERT INTO ssf_daily VALUES (%s,%s,%s) ON CONFLICT (day) DO UPDATE
                           SET syrup_held=EXCLUDED.syrup_held, liquid_assets_usd=EXCLUDED.liquid_assets_usd""", ssf)
        cur.executemany("""INSERT INTO syrup_buybacks VALUES (%s,%s,%s,%s) ON CONFLICT (month) DO UPDATE
                           SET amount_usd=EXCLUDED.amount_usd, syrup_bought=EXCLUDED.syrup_bought, avg_price=EXCLUDED.avg_price""", bb)
        cur.execute("""INSERT INTO maple_balance_sheet VALUES (%s,%s,%s,%s) ON CONFLICT (day) DO UPDATE SET
                       syrup_amount=EXCLUDED.syrup_amount, syrup_usd=EXCLUDED.syrup_usd, liquid_assets_usd=EXCLUDED.liquid_assets_usd""",
                    (today, money(bs["totalSyrupAmount"].replace("M", "")) * 1e6, money(bs["totalSyrupUsd"].replace("M", "")) * 1e6,
                     money(bs["totalLiquidAssetsUsd"].replace("M", "")) * 1e6))
        conn.commit()
    print(f"maple site: revenue {len(rev)} months · aum {len(aum)} days · ssf {len(ssf)} days · buybacks {len(bb)} months")

if __name__ == "__main__":
    main()
