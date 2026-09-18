"""DeFiLlama -> Robinhood Chain macro: TVL, fees, revenue, DEX volume (chain totals + per-protocol daily). No key."""
import datetime as dt, time, requests
from common import db

H = {"User-Agent": "maple-pipeline"}
def get(url, tries=5):
    for i in range(tries):
        r = requests.get(url, timeout=60, headers=H)
        if r.status_code == 200: return r.json()
        time.sleep(2 ** i)
    raise RuntimeError(f"llama {r.status_code} {url}")

D = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).date()

def main():
    tvl = {D(r["date"]): r["tvl"] for r in get("https://api.llama.fi/v2/historicalChainTvl/Robinhood%20Chain")}
    seq = {D(a): b for a, b in get("https://api.llama.fi/summary/fees/robinhood-chain?dataType=dailyFees")["totalDataChart"]}
    totals, per = {}, []
    for metric, url in (("fees", "https://api.llama.fi/overview/fees/robinhood?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyFees"),
                        ("revenue", "https://api.llama.fi/overview/fees/robinhood?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false&dataType=dailyRevenue"),
                        ("dex_volume", "https://api.llama.fi/overview/dexs/robinhood?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=false")):
        j = get(url)
        cat = {p["name"]: p.get("category") for p in j.get("protocols", [])}
        for ts, v in j["totalDataChart"]: totals.setdefault(D(ts), {})[metric] = v
        for ts, m in j["totalDataChartBreakdown"]:
            for name, v in m.items(): per.append((D(ts), name, cat.get(name), metric, v))
    days = set(tvl) | set(seq) | set(totals)
    rows = [(d, tvl.get(d), totals.get(d, {}).get("fees"), totals.get(d, {}).get("revenue"), totals.get(d, {}).get("dex_volume"), seq.get(d)) for d in sorted(days)]
    with db() as conn:
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO llama_chain_daily VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (day) DO UPDATE SET
                tvl_usd=EXCLUDED.tvl_usd, fees_usd=EXCLUDED.fees_usd, revenue_usd=EXCLUDED.revenue_usd, dex_volume_usd=EXCLUDED.dex_volume_usd, sequencer_fees_usd=EXCLUDED.sequencer_fees_usd""", rows)
            cur.executemany("INSERT INTO llama_protocol_daily VALUES (%s,%s,%s,%s,%s) ON CONFLICT (day,protocol,metric) DO UPDATE SET value_usd=EXCLUDED.value_usd, category=EXCLUDED.category", per)
            # keep legacy chain_tvl in sync for the existing share widget
            cur.executemany("INSERT INTO chain_tvl VALUES (%s,%s) ON CONFLICT (day) DO UPDATE SET tvl_usd=EXCLUDED.tvl_usd", [(d, v) for d, v in tvl.items()])
        conn.commit()
        print("llama_chain_daily", conn.execute("SELECT count(*), max(day) FROM llama_chain_daily").fetchone(), "protocol rows", len(per))

if __name__ == "__main__":
    main()
