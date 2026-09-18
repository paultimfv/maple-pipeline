"""SYRUP price/mcap/volume from CoinGecko (free, trailing 365d) -> syrup_price; buybacks CSV -> syrup_buybacks."""
import csv, datetime as dt, requests
from pathlib import Path
from common import db, ROOT

CG = "https://api.coingecko.com/api/v3/coins/syrup/market_chart"

def main():
    r = requests.get(CG, params={"vs_currency": "usd", "days": "365", "interval": "daily"}, timeout=60,
                     headers={"User-Agent": "maple-pipeline"})
    r.raise_for_status(); j = r.json()
    by_day = {}
    for key, out in (("prices", "p"), ("market_caps", "m"), ("total_volumes", "v")):
        for ts, val in j[key]:
            by_day.setdefault(dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date(), {})[out] = val
    rows = [(d, x.get("p"), x.get("m"), x.get("v")) for d, x in sorted(by_day.items()) if x.get("p")]
    bb = []
    f = ROOT / "config" / "syrup_buybacks.csv"
    if f.exists():
        for r_ in csv.DictReader(open(f)):
            amt = float(r_["amount"].replace("$", "").replace(",", "") or 0)
            if amt <= 0: continue
            bb.append((dt.datetime.strptime(r_["month"], "%b %Y").date(), amt, float(r_["syrup_bought"]),
                       float(r_["avg_price"].replace("$", "")) if r_.get("avg_price") else None))
    e = requests.get("https://api.coingecko.com/api/v3/coins/ethereum/market_chart", params={"vs_currency": "usd", "days": "365", "interval": "daily"},
                     timeout=60, headers={"User-Agent": "maple-pipeline"}).json()
    eth_rows = [(dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date(), v) for ts, v in e["prices"]]
    with db() as conn:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO eth_price VALUES (%s,%s) ON CONFLICT (day) DO UPDATE SET price_usd=EXCLUDED.price_usd", eth_rows)
            cur.executemany("INSERT INTO syrup_price VALUES (%s,%s,%s,%s) ON CONFLICT (day) DO UPDATE SET price_usd=EXCLUDED.price_usd, mcap_usd=EXCLUDED.mcap_usd, volume_usd=EXCLUDED.volume_usd", rows)
            cur.executemany("INSERT INTO syrup_buybacks VALUES (%s,%s,%s,%s) ON CONFLICT (month) DO UPDATE SET amount_usd=EXCLUDED.amount_usd, syrup_bought=EXCLUDED.syrup_bought, avg_price=EXCLUDED.avg_price", bb)
        conn.commit()
        print("syrup_price", conn.execute("SELECT count(*), min(day), max(day) FROM syrup_price").fetchone(), "buybacks", len(bb))

if __name__ == "__main__":
    main()
