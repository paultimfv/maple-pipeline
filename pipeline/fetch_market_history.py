"""SYRUP derivatives and DEX liquidity history, from free public sources -> syrup_market_history (day, source, metric, value).

- Binance USD-M perp SYRUPUSDT: open interest (last 5-minute reading of each day) and daily quote volume, from Binance's
  public data archive data.binance.vision (the live API blocks US servers; the archive does not). Files appear a day late.
- OKX perp SYRUP-USDT-SWAP: open interest (rubik stats, daily) and daily quote volume (candles).
- Hyperliquid perp SYRUP: daily volume (candles: base volume × close). No open interest history is published.
- Bitget perp SYRUPUSDT: daily quote volume (candles).
- DEX pools holding SYRUP (Uniswap v3/v4, Aerodrome): daily liquidity, DefiLlama yields charts.
Bybit also blocks US servers and has no public archive for open interest, so it is only in the daily snapshot (syrup_venues).
Incremental: Binance days already stored are skipped; the other sources are cheap and fully refreshed.
"""
import csv, datetime as dt, io, zipfile, requests
from common import db

UA = {"User-Agent": "maple-pipeline"}
D = lambda ms: dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).date()
LLAMA_POOLS = {"d8490bb4-a01e-4f21-aaaf-15e6e953951d": "Uniswap v4 ETH/SYRUP", "7f1c4126-3998-4334-9ce3-c640e869d682": "Uniswap v3 SYRUP/WETH",
               "7113cbce-92d1-469c-9fe4-9dbfa9f1618e": "Aerodrome WETH/SYRUP (Base)", "3a1b814d-a869-479c-af39-4b1523c202e3": "Uniswap v3 WETH/SYRUP (Base)"}
BV = "https://data.binance.vision/data/futures/um"

def zcsv(url):
    r = requests.get(url, timeout=60, headers=UA)
    if r.status_code != 200: return None
    z = zipfile.ZipFile(io.BytesIO(r.content)); return list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))))

def binance(have):
    rows, today = [], dt.date.today()
    # daily volume: monthly kline files, then daily files for the current month
    m = dt.date(2025, 4, 1)
    while m <= today:
        k = zcsv(f"{BV}/monthly/klines/SYRUPUSDT/1d/SYRUPUSDT-1d-{m:%Y-%m}.zip") if (m.year, m.month) != (today.year, today.month) else None
        if k is None and (m.year, m.month) == (today.year, today.month):
            k = []
            for d in range(1, today.day):
                x = zcsv(f"{BV}/daily/klines/SYRUPUSDT/1d/SYRUPUSDT-1d-{m.replace(day=d)}.zip"); k += x or []
        for r in k or []:
            if r and r[0].isdigit(): rows.append((D(r[0]), "Binance", "perp_volume_usd", float(r[7])))
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    # open interest: one metrics file per day; last reading of the day
    first = min((r[0] for r in rows), default=today)
    d = first
    while d < today:
        if (d, "oi") not in have:
            x = zcsv(f"{BV}/daily/metrics/SYRUPUSDT/SYRUPUSDT-metrics-{d}.zip")
            if x and len(x) > 1: rows.append((d, "Binance", "oi_usd", float(x[-1][3])))
        d += dt.timedelta(days=1)
    return rows

def okx():
    rows, end = [], ""
    for _ in range(20):
        j = requests.get("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-history",
                         params={"instId": "SYRUP-USDT-SWAP", "period": "1D", "limit": 100, **({"end": end} if end else {})}, headers=UA, timeout=60).json().get("data") or []
        if not j: break
        rows += [(D(r[0]), "OKX", "oi_usd", float(r[3])) for r in j]; end = j[-1][0]
    after = ""
    for _ in range(20):
        j = requests.get("https://www.okx.com/api/v5/market/history-candles",
                         params={"instId": "SYRUP-USDT-SWAP", "bar": "1Dutc", "limit": 100, **({"after": after} if after else {})}, headers=UA, timeout=60).json().get("data") or []
        if not j: break
        rows += [(D(r[0]), "OKX", "perp_volume_usd", float(r[7])) for r in j if r[8] == "1"]; after = j[-1][0]
    return rows

def hyperliquid():
    j = requests.post("https://api.hyperliquid.xyz/info", json={"type": "candleSnapshot", "req": {"coin": "SYRUP", "interval": "1d", "startTime": 1700000000000}}, timeout=60).json()
    return [(D(c["t"]), "Hyperliquid", "perp_volume_usd", float(c["v"]) * float(c["c"])) for c in j][:-1]  # last candle is today, partial

def bitget():
    rows, end = [], ""
    for _ in range(10):
        j = requests.get("https://api.bitget.com/api/v2/mix/market/history-candles", params={"symbol": "SYRUPUSDT", "productType": "usdt-futures",
                         "granularity": "1D", "limit": 200, **({"endTime": end} if end else {})}, headers=UA, timeout=60).json().get("data") or []
        new = [(D(r[0]), "Bitget", "perp_volume_usd", float(r[6])) for r in j]
        if not new or (rows and new[0][0] >= rows[-1][0]): break
        rows += new; end = str(int(j[0][0]) - 1)
    return rows

def llama():
    rows = []
    for pid, name in LLAMA_POOLS.items():
        for r in requests.get(f"https://yields.llama.fi/chart/{pid}", headers=UA, timeout=60).json().get("data", []):
            rows.append((dt.date.fromisoformat(r["timestamp"][:10]), name, "dex_liquidity_usd", float(r["tvlUsd"] or 0)))
    return rows

def main():
    with db() as conn:
        have = {(r[0], "oi") for r in conn.execute("SELECT day FROM syrup_market_history WHERE source='Binance' AND metric='oi_usd'")}
        rows = []
        for name, fn in (("binance", lambda: binance(have)), ("okx", okx), ("hyperliquid", hyperliquid), ("bitget", bitget), ("llama", llama)):
            try: got = fn(); rows += got; print(f"market_history {name}: {len(got)}")
            except Exception as e: print(f"market_history {name} skipped: {e}")
        keep = {}
        for r in rows: keep[r[:3]] = r
        conn.cursor().executemany("""INSERT INTO syrup_market_history VALUES (%s,%s,%s,%s) ON CONFLICT (day, source, metric) DO UPDATE SET value=EXCLUDED.value""", list(keep.values()))
        conn.commit()

if __name__ == "__main__":
    main()
