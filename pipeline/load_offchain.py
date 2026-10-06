"""Offchain inputs that cannot be rebuilt from contracts -> Postgres. Each file documents its own source in its header."""
import csv
from common import db, ROOT

def main():
    lines = [l for l in open(ROOT / "config" / "otc_revenue_monthly.csv") if not l.startswith("#")]
    rows = [(r["month"], float(r["amount_usd"])) for r in csv.DictReader(lines)]
    with db() as conn:
        conn.cursor().executemany("INSERT INTO otc_revenue VALUES (%s,%s) ON CONFLICT (month) DO UPDATE SET amount_usd=EXCLUDED.amount_usd", rows)
        lines = [l for l in open(ROOT / "config" / "syrup_price_history.csv") if not l.startswith("#")]
        px = [(r["day"], float(r["price_usd"]), float(r["mcap_usd"]) or None, float(r["volume_usd"] or 0)) for r in csv.DictReader(lines)]
        conn.cursor().executemany("INSERT INTO syrup_price VALUES (%s,%s,%s,%s) ON CONFLICT (day) DO NOTHING", px)
        conn.commit()
    print("otc_revenue", len(rows), "syrup_price history", len(px))

if __name__ == "__main__":
    main()
