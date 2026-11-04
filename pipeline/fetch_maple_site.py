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

def islands(page):  # unused since the Nov 2026 redesign; kept for reference
    out = {}
    for url, props in re.findall(r'<astro-island[^>]*component-url="([^"]+)"[^>]*props="([^"]*)"', page):
        out[url.split("/")[-1].split(".")[0]] = unwrap(json.loads(html.unescape(props)))
    return out

D = lambda ts: dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date()
money = lambda s: float(str(s).replace("$", "").replace(",", "") or 0)

def get(path):
    return requests.get(URL + path, timeout=90, headers={"User-Agent": "Mozilla/5.0 (maple-pipeline)"}).text

def all_islands(page, name):
    """Every island whose component name contains `name`, in page order (names carry a hash and change between builds)."""
    out = []
    for url, props in re.findall(r'<astro-island[^>]*component-url="([^"]+)"[^>]*props="([^"]*)"', page):
        if name in url.split("/")[-1]:
            out.append(unwrap(json.loads(html.unescape(props))))
    if not out:
        raise KeyError(f"no '{name}' island on maple.finance{URL[len('https://maple.finance'):]} (page layout changed?)")
    return out

def balance_sheet(page):
    """Rendered as plain HTML since the Nov 2026 redesign: '125.54M SYRUP held …' then '$20.09M', and 'Liquid assets' … '$12.27M'."""
    i = page.find("Balance sheet")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page[i:i + 20000]))
    syrup = re.search(r"([\d.,]+)M SYRUP held.*?\$([\d.,]+)M", text)
    liquid = re.search(r"Liquid assets.*?\$([\d.,]+)M", text)
    return float(syrup[1].replace(",", "")) * 1e6, float(syrup[2].replace(",", "")) * 1e6, float(liquid[1].replace(",", "")) * 1e6

def main():
    # Since the Nov 2026 redesign the data is split: AUM/deposits on /transparency, revenue + SSF + balance sheet
    # on /transparency/financials, buybacks on /transparency/syrup.
    home, fin, syr = get(""), get("/financials"), get("/syrup")
    aum_isl, dep_isl = all_islands(home, "ProductsAreaChart")[:2]   # first chart = AUM (deposits + collateral), second = deposits
    rev = [(D(r["ts"]), r["revenueUsd"]) for r in all_islands(fin, "RevenueChart")[0]["datasets"]["ALL"]]
    aum = {D(r["ts"]): r for r in aum_isl["datasets"]["ALL"]}
    dep = {D(r["ts"]): r for r in dep_isl["datasets"]["ALL"]}
    pools = [(d, p, aum[d].get(p) or 0, dep.get(d, {}).get(p) or 0) for d in aum for p in PRODUCTS]
    ssf = [(D(r["ts"]), r["syrupHoldings"], r["liquidAssetsUsd"]) for r in all_islands(fin, "SsfChart")[0]["datasets"]["ALL"]]
    bb = [(dt.datetime.strptime(r["date"], "%b %Y").date(), money(r["amountUsd"]), money(r["syrupAcquired"]), money(r["avgPrice"]) or None)
          for r in all_islands(syr, "BuybacksTable")[0]["rows"]]
    try:
        bs = balance_sheet(fin)
    except Exception as e:
        bs = None; print(f"maple site: balance sheet not parsed ({e!r}), skipping it")
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
        if bs:
            cur.execute("""INSERT INTO maple_balance_sheet VALUES (%s,%s,%s,%s) ON CONFLICT (day) DO UPDATE SET
                           syrup_amount=EXCLUDED.syrup_amount, syrup_usd=EXCLUDED.syrup_usd, liquid_assets_usd=EXCLUDED.liquid_assets_usd""",
                        (today, *bs))
        conn.commit()
    print(f"maple site: revenue {len(rev)} months · aum {len(aum)} days · ssf {len(ssf)} days · buybacks {len(bb)} months")

if __name__ == "__main__":
    main()
