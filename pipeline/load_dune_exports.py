"""
Load every Dune CSV export in config/dune_exports/ into Postgres schema `dune` (one table per file, replaced on each run).
These are the author's own Maple dashboards on Dune (ptmfv / ptimfv_team), exported Sep 2026, before the Dune account
ran out of credits. Static history; the live pipeline tables are the source of truth from here on.
"""
import csv, re
from pathlib import Path
from common import db, ROOT

NUM = re.compile(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$")

def table_name(f):
    s = re.sub(r"[^a-z0-9]+", "_", f.stem.lower()).strip("_")
    s = re.sub(r"^maple_finance_(revenue_model_|demand_side_analysis_|v2_depositor_borrower_structure_|v2_deposits_)?", "", s)
    return s[:60]

def main():
    files = sorted((ROOT / "config" / "dune_exports").glob("*.csv"))
    with db() as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS dune")
        seen = set()
        for f in files:
            rows = list(csv.reader(open(f, encoding="utf-8-sig")))
            if len(rows) < 2: continue
            name = table_name(f)
            if name in seen: continue            # duplicate exports ("(1)" copies)
            seen.add(name)
            cols = [re.sub(r"[^a-z0-9_]", "_", c.strip().lower()) or f"c{i}" for i, c in enumerate(rows[0])]
            body = rows[1:]
            types = ["numeric" if all(NUM.match(r[i]) for r in body if i < len(r) and r[i] != "") and any(i < len(r) and r[i] for r in body) else "text"
                     for i in range(len(cols))]
            conn.execute(f'DROP TABLE IF EXISTS dune."{name}"')
            conn.execute(f'CREATE TABLE dune."{name}" (' + ", ".join(f'"{c}" {t}' for c, t in zip(cols, types)) + ")")
            with conn.cursor().copy(f'COPY dune."{name}" ({", ".join(chr(34)+c+chr(34) for c in cols)}) FROM STDIN') as cp:
                for r in body:
                    cp.write_row([(v if v != "" else None) for v in (r + [""] * len(cols))[:len(cols)]])
            print(f"dune.{name}: {len(body)} rows")
        conn.commit()
    print(f"{len(seen)} tables")

if __name__ == "__main__":
    main()
