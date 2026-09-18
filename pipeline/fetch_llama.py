"""DeFiLlama Robinhood Chain TVL -> chain_tvl."""
import datetime as dt, requests
from common import db

URL = "https://api.llama.fi/v2/historicalChainTvl/Robinhood%20Chain"

def main():
    rows = requests.get(URL, timeout=30).json()
    with db() as conn:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO chain_tvl VALUES (%s,%s) ON CONFLICT (day) DO UPDATE SET tvl_usd=EXCLUDED.tvl_usd",
                            [(dt.datetime.fromtimestamp(r["date"], dt.timezone.utc).date(), r["tvl"]) for r in rows])
        conn.commit()
        print(conn.execute("SELECT count(*), max(day), max(tvl_usd) FROM chain_tvl").fetchone())

if __name__ == "__main__":
    main()
