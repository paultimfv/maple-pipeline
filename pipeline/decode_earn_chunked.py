"""Earn vault: decode all raw rows in memory, delete raw, vacuum, then insert (Neon 512MB cap)."""
import psycopg
from common import DATABASE_URL, RH_EARN_VAULT_V2
from decode import TOPIC, addr, data_words
V = RH_EARN_VAULT_V2
with psycopg.connect(DATABASE_URL, autocommit=True) as c:
    rows = c.execute("""SELECT r.topics, r.data, r.block_number, r.tx_hash, r.log_index, b.block_time, r.topic0
        FROM raw_logs r JOIN blocks b ON b.chain=r.chain AND b.block_number=r.block_number
        WHERE r.chain='robinhood' AND r.address=%s""", (V,)).fetchall()
    out = []
    for topics, data, bn, tx, li, bt, t0 in rows:
        assets, shares = data_words(data, 2)
        kind, owner = ("deposit", addr(topics[2])) if t0 == TOPIC["e_dep"] else ("withdraw", addr(topics[3]))
        out.append((bt, bn, tx, li, kind, owner, assets/1e6, shares/1e18))
    print("decoded in memory:", len(out), flush=True)
    n = c.execute("DELETE FROM raw_logs WHERE chain='robinhood' AND address=%s AND (tx_hash, log_index) IN (SELECT tx_hash, log_index FROM raw_logs r JOIN blocks b ON b.chain=r.chain AND b.block_number=r.block_number WHERE r.chain='robinhood' AND r.address=%s)", (V, V)).rowcount
    c.execute("vacuum full raw_logs"); c.execute("vacuum full earn_flows")
    print("deleted raw", n, "db", c.execute("select pg_size_pretty(pg_database_size(current_database()))").fetchone()[0], flush=True)
    with c.cursor() as cur:
        for i in range(0, len(out), 50000):
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS te (LIKE earn_flows)"); cur.execute("TRUNCATE te")
            with cur.copy("COPY te FROM STDIN") as cp:
                for r in out[i:i+50000]: cp.write_row(r)
            cur.execute("INSERT INTO earn_flows SELECT * FROM te ON CONFLICT DO NOTHING")
            print("inserted", i + 50000, flush=True)
    print(c.execute('select kind, count(*), count(distinct owner), round(sum(assets)) from earn_flows group by 1').fetchall())
    print('median/avg deposit', c.execute("select percentile_cont(0.5) within group (order by assets), round(avg(assets)) from earn_flows where kind='deposit'").fetchone())
    print('db', c.execute("select pg_size_pretty(pg_database_size(current_database()))").fetchone()[0])
