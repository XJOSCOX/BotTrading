"""Credential-free exports from immutable research snapshots, never account results."""
import csv
import io
import json
import html

from goxtrade.data import lab_store as store


def trades_csv(run):
    fields = ["strategy","symbol","contract_id","direction","entry_time","entry","initial_stop","target","quantity","exit_time","exit","reason","gross","costs","net","mfe_dollars","mae_dollars","profit_giveback","maximum_r","regimes"]
    output = io.StringIO()
    writer = csv.DictWriter(output,fieldnames=fields,extrasaction="ignore")
    writer.writeheader()
    for trade in run["result"]["state"]["trades"]:
        row = {**trade,**trade.get("management_analytics",{})}
        row["regimes"] = "; ".join(trade["regimes"])
        # Escape spreadsheet formula prefixes in any externally sourced text.
        writer.writerow({key:("'"+str(value) if isinstance(value,str) and value.startswith(("=","+","-","@")) else value) for key,value in row.items() if key in fields})
    return output.getvalue()


def html_report(run):
    def block(value):
        return "<pre>"+html.escape(json.dumps(value,indent=2,default=str))+"</pre>"
    metrics = run["result"]["summary"]
    return "<!doctype html><html lang='en'><meta charset='utf-8'><title>GoXTrade research report</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#172020}pre{white-space:pre-wrap;overflow-wrap:anywhere;border-top:1px solid #ccc;padding:16px 0}h2{margin-top:32px}</style><h1>Strategy Validation Lab</h1><p>Historical simulated results, not actual account profits. No broker checks or execution.</p>"+"".join("<h2>"+html.escape(title)+"</h2>"+block(value) for title,value in (
        ("Identity",dict(id=run["id"],created_at=run["created_at"],code=run["code"])),("Datasets and coverage",run["datasets"]),
        ("Frozen research inputs",run["request"]),("Metrics and portfolio accounting",metrics),
        ("Regimes and giveback",run["result"]["lab"]),("Comparisons",run["comparisons"]),
        ("Limitations and next steps",run["recommendation"])))+"</html>"


def export_dataset(identifier):
    """Stream bounded chunks instead of materializing a full long-range CSV."""
    from contextlib import closing
    meta = store.get("lab_datasets",identifier)
    columns = ["time","open","high","low","close","volume","instrument","contract_id","expiration","source","retrieved_at","timezone","granularity","volume_provenance"]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    yield output.getvalue()
    with closing(store.connect()) as conn:
        cursor = conn.execute("SELECT time,open,high,low,close,volume FROM lab_bars WHERE dataset=? ORDER BY time",(identifier,))
        while True:
            rows = cursor.fetchmany(2000)
            if not rows:
                break
            output.seek(0)
            output.truncate(0)
            for row in rows:
                retrieved=next((event["retrieved_at"] for event in meta.get("retrieval_events",[]) if event["start"]<=row["time"]<event["end"]),meta["retrieved_at"])
                values=[*row,meta["symbol"],meta["contract_id"],meta.get("expiration"),meta["source"],retrieved,"UTC",1,meta["volume_provenance"]]
                writer.writerow(["'"+value if isinstance(value,str) and value.startswith(("=","+","-","@")) else value for value in values])
            yield output.getvalue()
