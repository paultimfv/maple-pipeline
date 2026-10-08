"""Blockscout (robinhoodchain.blockscout.com) -> raw chain activity + token holder counts.
stats-service needs no key; REST holder counters use BLOCKSCOUT_KEY (free tier, Bearer)."""
import datetime as dt, os, time, requests
from common import db, RH_USDG, RH_TOKENS, RH_EARN_VAULT_V2

STATS = "https://robinhoodchain.blockscout.com/stats-service/api/v1/lines"
REST = "https://api.blockscout.com/4663/api/v2"
KEY = os.environ.get("BLOCKSCOUT_KEY")
H = {"User-Agent": "maple-pipeline"}
START = "2026-05-01"

# chart id -> column in bs_chain_daily
SERIES = {"newTxns": "txns", "activeAccounts": "active_accounts", "newAccounts": "new_accounts",
          "txnsFee": "fees_eth", "averageTxnFee": "avg_fee_eth", "newContracts": "new_contracts",
          "newUserOps": "user_ops", "newAccountAbstractionWallets": "new_aa_wallets", "txnsSuccessRate": "success_rate"}

def get(url, tries=3, **kw):
    for i in range(tries):
        r = requests.get(url, timeout=60, headers={**H, **kw.pop("headers", {})}, **kw)
        if r.status_code == 200: return r.json()
        time.sleep(2 ** i)
    raise RuntimeError(f"blockscout {r.status_code} {url}")

def chain_daily(conn):
    days = {}
    for cid, col in SERIES.items():
        try:
            for p in get(f"{STATS}/{cid}", params={"resolution": "DAY", "from": START})["chart"]:
                days.setdefault(p["date"], {})[col] = float(p["value"]) if p.get("value") not in (None, "") else None
        except Exception as e:
            print(f"  {cid} skipped: {e}")
    cols = list(SERIES.values())
    rows = [(dt.date.fromisoformat(d), *[v.get(c) for c in cols]) for d, v in sorted(days.items())]
    with conn.cursor() as cur:
        cur.executemany(f"""INSERT INTO bs_chain_daily (day,{','.join(cols)}) VALUES ({','.join(['%s']*(len(cols)+1))})
            ON CONFLICT (day) DO UPDATE SET {','.join(f'{c}=EXCLUDED.{c}' for c in cols)}""", rows)
    conn.commit()
    print("bs_chain_daily", conn.execute("SELECT count(*), max(day) FROM bs_chain_daily").fetchone())

def holders(conn):
    """Holder counts today for the tokens the dashboard talks about (one REST call each)."""
    if not KEY: print("  no BLOCKSCOUT_KEY, holders skipped"); return
    toks = {"USDG": RH_USDG, "steakUSDG (Earn)": RH_EARN_VAULT_V2, **RH_TOKENS}
    today = dt.datetime.now(dt.timezone.utc).date()
    for name, addr in toks.items():
        try:
            j = get(f"{REST}/tokens/{addr}/counters", headers={"Authorization": f"Bearer {KEY}"})
            conn.execute("INSERT INTO bs_holders VALUES (%s,%s,%s,%s,%s) ON CONFLICT (day,token) DO UPDATE SET holders=EXCLUDED.holders, transfers=EXCLUDED.transfers",
                         (today, name, addr, int(j.get("token_holders_count") or 0), int(j.get("transfers_count") or 0)))
            time.sleep(0.25)   # free tier: 5 rps
        except Exception as e:
            print(f"  holders {name} skipped: {e}")
    conn.commit()
    print("bs_holders", conn.execute("SELECT count(*) FROM bs_holders WHERE day=%s", (today,)).fetchone())

def main():
    with db() as conn:
        chain_daily(conn); holders(conn)

if __name__ == "__main__":
    main()
