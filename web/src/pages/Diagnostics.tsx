import { memo, useEffect, useState } from "react";
import { RefreshCw, KeyRound, Search, Download } from "lucide-react";
import { api, ct, type Json } from "../api";
import { Badge, Field, Notice, Table } from "../components";
import type { PageProps } from "../pageTypes";

function DiagnosticsPage(_: PageProps) {
  const [data, setData] = useState<Json | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [symbol, setSymbol] = useState("MNQ"),
    [contract, setContract] = useState(""),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [live, setLive] = useState(false);
  const load = async () => {
    try {
      setData(await api("/diagnostics"));
      setError("");
    } catch (e) {
      setError(String(e));
    }
  };
  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const r = await api("/diagnostics");
        if (!stopped) {
          setData(r);
          setError("");
        }
      } catch (e) {
        if (!stopped) setError(String(e));
      }
      if (!stopped) timer = setTimeout(refresh, 3000);
    };
    void refresh();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);
  const probe = async (action: string) => {
    setBusy(true);
    setError("");
    try {
      await api(
        "/diagnostics",
        action === "authenticate"
          ? { action }
          : { action, symbol, contract_id: contract, start, end, live },
      );
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const download = () => {
    const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      }),
      url = URL.createObjectURL(blob),
      a = document.createElement("a");
    a.href = url;
    a.download = "sanitized-projectx-diagnostics.json";
    a.click();
    URL.revokeObjectURL(url);
  };
  if (!data)
    return <Notice>{error || "Loading local diagnostic evidence"}</Notice>;
  return (
    <>
      <div className="section-heading">
        <Badge>READ-ONLY / NO ORDERS</Badge>
        <button onClick={download}>
          <Download size={16} />
          Export sanitized report
        </button>
      </div>
      {error && <Notice danger>{error}</Notice>}
      <section className="replay-config">
        <div>
          <h2>Configuration</h2>
          <Table
            heads={["Check", "Evidence"]}
            rows={[
              ["API host", data.configuration.api.host],
              ["API URL valid", String(data.configuration.api.valid)],
              ["Market hub", data.configuration.market_hub.host],
              ["Username present", String(data.configuration.username_present)],
              ["API key present", String(data.configuration.api_key_present)],
              [
                "Practice configured",
                String(data.configuration.profiles.practice),
              ],
              ["Leader configured", String(data.configuration.profiles.leader)],
            ]}
          />
          <h2>Authentication</h2>
          <p>
            {data.authenticated
              ? `Successful probe: ${ct(data.authenticated_at)}`
              : "Not tested in this interface process"}
          </p>
          <button disabled={busy} onClick={() => void probe("authenticate")}>
            <KeyRound size={16} />
            Test authentication
          </button>
        </div>
        <div>
          <h2>Historical access</h2>
          <div className="form-grid">
            <Field label="Diagnostic instrument">
              <select
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
              >
                {["MNQ", "MES", "MYM", "NQ", "ES", "YM"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </Field>
            <Field label="Actual diagnostic contract">
              <input
                value={contract}
                onChange={(e) => setContract(e.target.value)}
                list="diagnostic-contracts"
              />
              <datalist id="diagnostic-contracts">
                {data.configuration.contracts.map((r: Json) => (
                  <option key={r.symbol} value={r.contract_id}>
                    {r.symbol}
                  </option>
                ))}
              </datalist>
            </Field>
            <Field label="History start / UTC">
              <input value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label="History end exclusive / UTC">
              <input value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
            <Field label="Data subscription">
              <select
                value={String(live)}
                onChange={(e) => setLive(e.target.value === "true")}
              >
                <option value="false">Simulated</option>
                <option value="true">Live</option>
              </select>
            </Field>
          </div>
          <button
            disabled={busy || !data.authenticated}
            onClick={() => void probe("history")}
          >
            <Search size={16} />
            Test historical data
          </button>
        </div>
      </section>
      <section>
        <div className="section-heading">
          <h2>Market-data evidence</h2>
          <button onClick={() => void load()}>
            <RefreshCw size={16} />
            Refresh evidence
          </button>
        </div>
        <div className="replay-toolbar">
          <Badge>
            {data.feed.market_open ? "MARKET OPEN" : "MARKET CLOSED"}
          </Badge>
          <span>{data.feed.connection}</span>
          <span>
            Source age:{" "}
            {data.feed.source_age_seconds == null
              ? "unknown"
              : data.feed.source_age_seconds.toFixed(1) + "s"}
          </span>
          <span>
            Reconnect attempts: {data.feed.reconnection_attempts ?? "unknown"}
          </span>
        </div>
        {data.feed.recommendations.map((r: string) => (
          <Notice key={r}>{r}</Notice>
        ))}
        <Table
          heads={[
            "Event",
            "Instrument",
            "Contract",
            "Source timestamp",
            "Local receipt",
            "Price",
          ]}
          rows={data.feed.last_events.map((r: Json) => [
            r.kind,
            r.symbol,
            r.contract_id,
            ct(r.event_time),
            ct(r.received_at),
            r.price,
          ])}
        />
        <Table
          heads={["Instrument", "Contract", "Subscription evidence"]}
          rows={data.feed.subscriptions.map((r: Json) => [
            r.symbol,
            r.contract_id,
            r.state,
          ])}
        />
      </section>
      <section className="operational-acceptance">
        <h2>Practice operations</h2>
        <Notice danger={data.practice_readiness?.status !== "CHECKS_PASSED"}>
          {data.practice_readiness?.status === "CHECKS_PASSED"
            ? "Current operational checks passed"
            : "Operational checks need attention"}
        </Notice>
        <Table
          heads={["Check", "Status", "Evidence"]}
          rows={(data.practice_readiness?.checks || []).map((r: Json) => [
            r.check,
            r.status,
            r.detail,
          ])}
        />
        <p className="footnote">{data.practice_readiness?.limitation}</p>
        <h2>Operational acceptance</h2>
        <Notice>
          {data.operational?.restrictions || "Readiness unavailable"}
        </Notice>
        <Table
          heads={["Storage", "Evidence status"]}
          rows={["production", "research", "replay"].map((key) => [
            key,
            data.operational?.[key]?.storage || "UNKNOWN",
          ])}
        />
        <h3>Strategy readiness</h3>
        <Table
          heads={[
            "Strategy",
            "Monitor",
            "Quote",
            "History",
            "Current signal",
            "Latest manager rejection",
            "Practice execution rejection",
          ]}
          rows={(data.operational?.strategies || []).map((r: Json) => [
            r.name,
            r.monitoring,
            r.quote_fresh ? "Fresh observation" : "STALE / UNAVAILABLE",
            r.history_readiness,
            r.latest_signal,
            r.last_rejection || "No recorded rejection / unknown",
            r.last_practice_rejection || "No recorded Practice rejection",
          ])}
        />
        <h3>Research readiness</h3>
        <Table
          heads={["Check", "Saved local evidence"]}
          rows={[
            [
              "Datasets",
              data.operational?.research?.evidence?.dataset_count ?? "UNKNOWN",
            ],
            [
              "Eligible metadata / verify integrity on use",
              data.operational?.research?.evidence?.eligible_metadata_count ??
                "UNKNOWN",
            ],
            [
              "Historical runs",
              data.operational?.research?.evidence?.run_count ?? "UNKNOWN",
            ],
            [
              "Latest historical run",
              ct(data.operational?.research?.evidence?.latest_run_at),
            ],
            [
              "Portfolio comparison",
              data.operational?.research?.evidence?.portfolio_comparison
                ? "Saved comparison"
                : "NOT VERIFIED / NO SAVED COMPARISON",
            ],
            [
              "Exit comparison",
              data.operational?.research?.evidence?.exit_comparison
                ? "Saved comparison"
                : "NOT VERIFIED / NO SAVED COMPARISON",
            ],
            [
              "Replay readiness",
              data.operational?.research?.evidence?.replay_readiness ||
                "UNKNOWN",
            ],
            [
              "Replay sessions",
              data.operational?.replay?.evidence?.session_count ?? "UNKNOWN",
            ],
            [
              "Latest replay",
              data.operational?.replay?.evidence?.latest_status || "UNKNOWN",
            ],
          ]}
        />
        <h3>Account safety evidence</h3>
        <Table
          heads={[
            "Profile",
            "Saved entry setting",
            "Selection / additional opt-ins",
            "Loss lock",
            "Recent broker snapshot",
            "Positions / orders",
            "Unresolved jobs",
            "Protection",
          ]}
          rows={["practice", "leader"].map((profile) => {
            const r =
              data.operational?.production?.evidence?.profiles?.[profile];
            return [
              profile,
              r?.saved_enabled == null
                ? "UNKNOWN"
                : r.saved_enabled
                  ? "Enabled / verify worker"
                  : "Paused setting",
              <>
                <span>
                  {r?.selected_strategies?.join(", ") || "NONE / UNKNOWN"}
                </span>
                <br />
                {Object.entries(r?.strategy_opt_ins || {})
                  .map(
                    ([name, allowed]) =>
                      `${name}: ${allowed == null ? "UNKNOWN" : allowed ? "on" : "off"}`,
                  )
                  .join("; ")}
              </>,
              r?.loss_locked == null
                ? "UNKNOWN"
                : r.loss_locked
                  ? "LOCKED"
                  : "Saved clear / verify balance",
              r?.broker_snapshot_recent
                ? "Recent saved observation"
                : "STALE / UNAVAILABLE",
              `${r?.broker_positions ?? "?"} / ${r?.broker_orders ?? "?"}`,
              r?.unresolved_jobs == null
                ? "UNKNOWN"
                : `${r.unresolved_jobs}${r.ambiguous_jobs ? " / ambiguous ownership" : ""}${r.jobs_truncated ? " / bounded view" : ""}`,
              `${r?.saved_stops_verified ?? "?"} saved stop checks / ${r?.broker_protection || "NOT VERIFIED"}`,
            ];
          })}
        />
      </section>
      <section>
        <h2>Explicit probe results</h2>
        <Table
          heads={[
            "Time",
            "Category",
            "Diagnostic code",
            "HTTP",
            "Duration",
            "Recommendation",
          ]}
          rows={data.results
            .slice()
            .reverse()
            .map((r: Json) => [
              ct(r.time),
              r.category,
              r.code,
              r.http_status ?? "--",
              r.duration_ms == null ? "--" : r.duration_ms + " ms",
              <>
                <span>{r.recommendation}</span>
                {r.quality && (
                  <details>
                    <summary>OHLCV evidence</summary>
                    <pre>{JSON.stringify(r.quality, null, 2)}</pre>
                  </details>
                )}
              </>,
            ])}
        />
      </section>
    </>
  );
}
export const Diagnostics = memo(DiagnosticsPage, () => true);
