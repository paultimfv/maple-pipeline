"""
Fork the Maple Finance Business Analysis dashboard: old Dune account -> new.
Drives the Dune MCP HTTP endpoint directly with two keys. Resumable via fork_map.csv.

  python3 dune/fork.py            # run everything
  tail -f dune/fork.log           # watch
"""
import csv, json, os, re, subprocess, sys, time
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / "dune"
LEDGER = D / "fork_map.csv"
LOG = open(D / "fork.log", "a")
MCP = "https://api.dune.com/mcp/v1"

def log(*a):
    s = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(s); LOG.write(s + "\n"); LOG.flush()

# ---- keys (never printed) ----
OLD = subprocess.run(["claude", "mcp", "get", "dune"], capture_output=True, text=True).stdout
OLD = re.search(r"x-dune-api-key:?\s+(\S+)", OLD).group(1)
NEW = re.search(r"^DUNE_NEW_KEY=(\S+)", open(ROOT / ".env").read(), re.M).group(1)

def mcp(key, name, args, retries=3):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}}
    for i in range(retries):
        try:
            r = requests.post(MCP, json=body, timeout=300, headers={"x-dune-api-key": key,
                "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
            data = [l[6:] for l in r.text.splitlines() if l.startswith("data: ")]
            j = json.loads(data[-1]) if data else r.json()
            if "error" in j: raise RuntimeError(j["error"])
            res = j["result"]
            if res.get("isError"): raise RuntimeError(res.get("content", [{}])[0].get("text", "")[:300])
            if "structuredContent" in res: return res["structuredContent"]
            return json.loads(res["content"][0]["text"])
        except Exception as e:
            if i == retries - 1: raise
            log(f"   retry {name}: {str(e)[:120]}"); time.sleep(3 * (i + 1))

# ---- dashboard query list, in section order (from CSV export mapping) ----
SECTIONS = [
 ("Overview / Protocol", [8087877, 8254314, 8259647, 7850189, 7794968, 7795642, 8165798]),
 ("Supply-Side", [8164301, 8164208, 7811498, 8163448, 7812085, 7812105, 7811948, 7811870, 7812198]),
 ("Demand-Side", [8165699, 7829130, 8165870, 8165715, 7829235, 8165816, 7820984]),
 ("Revenue Model / Fees", [7850791, 8088441, 8117342, 7850594, 8117336, 7828334, 8096589]),
 ("SYRUP Token / Valuation", [8226973, 8107853, 8232796, 8096819, 8108196, 8108258, 8166262]),
 ("syrupUSDG", [8084139, 8087879, 8035988, 8087891]),
]
PRE_EXISTING = {8226973: 8713706, 8232796: 8714143}   # created during the test run

# ---- ledger ----
COLS = ["section", "old_query", "new_query", "query_name", "old_viz", "new_viz", "viz_name", "viz_type", "status", "note"]
ledger = []
if LEDGER.exists(): ledger = list(csv.DictReader(open(LEDGER)))
def save():
    with open(LEDGER, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(ledger)
def done(old_q, old_v=None):
    return next((r for r in ledger if r["old_query"] == str(old_q) and r["old_viz"] == str(old_v or "") and r["status"] in ("ok", "skipped")), None)

# ---- viz option conversion (Dune raw options -> MCP generateVisualization config) ----
def convert(v):
    """returns (chartType, config, fix_notes[])"""
    o, ct, fix = v.get("options") or {}, v.get("chartType"), []
    if ct == "counter":
        return ct, {"chart_type": "counter", "column": o.get("counterColName", ""), "row_num": o.get("rowNumber", 1) or 1,
                    "decimal_places": o.get("stringDecimal", 2) if o.get("stringDecimal") is not None else 2,
                    "prefix": o.get("stringPrefix", "") or "", "suffix": o.get("stringSuffix", "") or "",
                    "label": o.get("counterLabel", "") or "", "color_positive": bool(o.get("colorPositive")), "color_negative": bool(o.get("colorNegative"))}, fix
    if ct == "table":
        cols = o.get("columns") or []
        if not cols: return None, None, ["default results table - skipped"]
        return ct, {"chart_type": "table", "columns": [{"name": c["name"], "title": c.get("title") or c["name"],
                    "column_type": "progressbar" if c.get("type") == "progressbar" else "normal",
                    "data_type": "numeric" if c.get("numberFormat") else "string", "align": c.get("alignContent") or "left",
                    "is_hidden": bool(c.get("isHidden")), "color_positive": None, "color_negative": None,
                    "number_format": c.get("numberFormat")} for c in cols]}, fix
    cm = o.get("columnMapping") or {}
    xs = [c for c, r in cm.items() if r == "x"]; ys = [c for c, r in cm.items() if r == "y"]; gs = [c for c, r in cm.items() if r == "series"]
    if not xs or not ys: return None, None, [f"no x/y mapping for {ct}"]
    so = o.get("seriesOptions") or {}
    if ct == "pie":
        return ct, {"chart_type": "pie", "x_axis_column": xs[0], "y_axis_column": ys[0], "y_axis_title": ys[0],
                    "y_axis_label_format": o.get("numberFormat") or "0,0", "show_labels": True,
                    "enable_legend": (o.get("legend") or {}).get("enabled", True)}, fix
    if ct not in ("line", "area", "column", "scatter"): return None, None, [f"unsupported chartType {ct}"]
    right = [c for c in ys if (so.get(c) or {}).get("yAxis") == 1]; left = [c for c in ys if c not in right]
    types = {(so.get(c) or {}).get("type") or ct for c in ys}
    if len(types) > 1: fix.append(f"mixed series types {sorted(types)} -> all {ct}")
    if right and ct not in ("line", "area"): fix.append(f"dual axis on {ct} -> rebuilt as line"); ct = "line"
    ya = o.get("yAxis") or [{}]
    stacking = (o.get("series") or {}).get("stacking")
    cfg = {"chart_type": ct, "enable_legend": (o.get("legend") or {}).get("enabled", True), "stacked": stacking in ("normal", "percent"),
           "x_axis": {"column": xs[0], "title": ((o.get("xAxis") or {}).get("title") or {}).get("text") or xs[0], "sort_x": o.get("sortX", True)},
           "y_axes": {"left": {"label_format": o.get("numberFormat") or "0,0", "series": [{"column": c, "title": (so.get(c) or {}).get("name") or c} for c in left]},
                      "right_enabled": bool(right), "right_label_format": o.get("numberFormatRightYAxisSeries") or "" if right else "",
                      "right_series": [{"column": c, "title": (so.get(c) or {}).get("name") or c} for c in right]}}
    if ya and ya[0].get("tickFormat"): cfg["y_axes"]["left"]["tick_format"] = ya[0]["tickFormat"]
    if ya and (ya[0].get("title") or {}).get("text"): cfg["y_axes"]["left"]["title"] = ya[0]["title"]["text"]
    if right and len(ya) > 1 and ya[1].get("tickFormat"): cfg["y_axes"]["right_tick_format"] = ya[1]["tickFormat"]
    if stacking == "percent": cfg["normalize_to_percentage"] = True
    if gs: cfg["group_by_column"] = gs[0]
    if cfg["stacked"]: cfg["when_duplicate_x"] = "sum"
    return ct, cfg, fix

# ---- main ----
def fork_query(section, old_q):
    q = mcp(OLD, "getDuneQuery", {"query_id": old_q})
    name = q["name"]
    (D / "queries" / f"{old_q}.sql").write_text(f"-- {name}\n-- old query id {old_q}\n" + q["query"])
    row = done(old_q)
    if row: new_q = int(row["new_query"])
    elif old_q in PRE_EXISTING: new_q = PRE_EXISTING[old_q]
    else:
        args = {"name": name, "description": q.get("description") or "", "query": q["query"], "is_private": False, "is_temp": False}
        if q.get("parameters"): args["parameters"] = [{"key": p["key"], "type": p.get("type", "text"), "value": str(p.get("value", ""))} for p in q["parameters"]]
        new_q = mcp(NEW, "createDuneQuery", args)["query_id"]
    if not row:
        ledger.append({"section": section, "old_query": old_q, "new_query": new_q, "query_name": name, "old_viz": "", "new_viz": "", "viz_name": "", "viz_type": "query", "status": "ok", "note": ""}); save()
    log(f"[{old_q} -> {new_q}] {name}")

    vizzes = mcp(OLD, "listQueryVisualizations", {"queryId": old_q, "limit": 100})["results"]
    todo = [v for v in vizzes if not done(old_q, v["id"])]
    if not todo: log("   all viz done"); return
    # execute once on new account so charts can attach
    ex = mcp(NEW, "executeQueryById", {"query_id": new_q, "performance": "medium"})
    res = mcp(NEW, "getExecutionResults", {"executionId": ex["execution_id"], "limit": 1, "timeout": 600})
    state = res.get("state")
    if state != "COMPLETED" and state != "QUERY_STATE_COMPLETED":
        log(f"   EXEC {state}: {str(res)[:200]}")
        for v in todo:
            ledger.append({"section": section, "old_query": old_q, "new_query": new_q, "query_name": name, "old_viz": v["id"], "new_viz": "", "viz_name": v["name"], "viz_type": v["type"], "status": "exec_failed", "note": str(res)[:200]})
        save(); return
    cost = (res.get("resultMetadata") or {}).get("executionCostCredits"); log(f"   executed ({cost} credits)")
    query_fix = False
    for v in todo:
        full = mcp(OLD, "getVisualization", {"visualizationId": v["id"]})
        (D / "viz" / f"{v['id']}.json").write_text(json.dumps(full, indent=1))
        ct, cfg, fix = convert(full)
        if cfg is None:
            ledger.append({"section": section, "old_query": old_q, "new_query": new_q, "query_name": name, "old_viz": v["id"], "new_viz": "", "viz_name": v["name"], "viz_type": full.get("chartType"), "status": "skipped", "note": "; ".join(fix)}); save()
            log(f"   skip viz {v['id']} {v['name']!r}: {fix}"); continue
        vname = ("[FIX] " if fix else "") + v["name"]
        try:
            out = mcp(NEW, "generateVisualization", {"queryId": new_q, "visualizationName": vname, "chartType": ct, "config": cfg})
            new_v = out.get("visualizationId") or out.get("id") or (out.get("visualization") or {}).get("id")
            st = "ok"; note = "; ".join(fix)
        except Exception as e:
            new_v, st, note = "", "viz_failed", str(e)[:200]; fix = fix + ["create failed"]
        if fix: query_fix = True
        ledger.append({"section": section, "old_query": old_q, "new_query": new_q, "query_name": name, "old_viz": v["id"], "new_viz": new_v, "viz_name": vname, "viz_type": ct, "status": st, "note": note}); save()
        log(f"   viz {v['id']} -> {new_v} {vname!r} {st} {note}")
    if query_fix and not name.startswith("[FIX]"):
        mcp(NEW, "updateDuneQuery", {"query_id": new_q, "name": "[FIX] " + name}); log("   query renamed with [FIX]")

def build_dashboard():
    ids, text = [], ["# Maple Finance Business Analysis (New)\n\nForked from ptmfv/maple-finance. Widgets are grouped by section below in order; `[FIX]` marks charts whose config could not be reproduced exactly and need a manual touch.\n"]
    for sec, qs in SECTIONS:
        names = []
        for q in qs:
            for r in ledger:
                if r["old_query"] == str(q) and r["viz_type"] != "query" and r["status"] == "ok" and r["new_viz"]:
                    ids.append(int(r["new_viz"])); names.append(f"{r['query_name']} — {r['viz_name']}")
        text.append(f"## {sec}\n" + "\n".join(f"- {n}" for n in names))
    out = mcp(NEW, "createDashboard", {"name": "Maple Finance Business Analysis (New)", "isPrivate": False, "columnsPerRow": 2,
                                        "visualizationIds": ids, "textWidgets": [{"text": "\n\n".join(text)}]})
    log("DASHBOARD:", json.dumps(out)[:400]); (D / "dashboard_new.json").write_text(json.dumps(out, indent=1))

if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    if only == "dashboard": build_dashboard(); sys.exit()
    for sec, qs in SECTIONS:
        log(f"=== {sec} ===")
        for q in qs:
            try: fork_query(sec, q)
            except Exception as e:
                log(f"   FAILED {q}: {str(e)[:300]}")
                ledger.append({"section": sec, "old_query": q, "new_query": "", "query_name": "", "old_viz": "", "new_viz": "", "viz_name": "", "viz_type": "query", "status": "failed", "note": str(e)[:200]}); save()
            time.sleep(1)
    build_dashboard()
    log("DONE")
