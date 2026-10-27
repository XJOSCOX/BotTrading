import { useState } from "react";
import { ct, money, type Json } from "../api";
import { Badge, Empty, Metric, Table } from "../components";
import { type PageProps, tone, fresh } from "../pageTypes";
import { Activity, ShieldCheck, ArrowUpRight } from "lucide-react";
import "./Dashboard.css";

export function Dashboard({ live, profile }: PageProps) {
  const [period, setPeriod] = useState("All saved"),
    [scope, setScope] = useState("Current account");
  const p = live.profiles[profile] || {},
    jobs = p.jobs || [],
    all: Json[] = p.trades || [];
  let cutoff = 0;
  if (period === "Today") {
    const now = new Date(),
      day = new Intl.DateTimeFormat("en-CA", {
        timeZone: "America/Chicago",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      }).format(now);
    cutoff = Date.parse(
      day +
        "T00:00:00" +
        (new Intl.DateTimeFormat("en-US", {
          timeZone: "America/Chicago",
          timeZoneName: "short",
        })
          .format(now)
          .includes("CDT")
          ? "-05:00"
          : "-06:00"),
    );
  } else if (period !== "All saved")
    cutoff = Date.now() - (period === "7 days" ? 7 : 30) * 86400000;
  const rows = all
    .filter(
      (r) =>
        (scope !== "Current account" || r.account_id === p.target?.id) &&
        Date.parse(r.closed_at) >= cutoff,
    )
    .sort((a, b) => Date.parse(a.closed_at) - Date.parse(b.closed_at));
  const wins = rows.filter((r) => r.net > 0),
    losses = rows.filter((r) => r.net < 0),
    net = rows.reduce((n, r) => n + r.net, 0),
    gain = wins.reduce((n, r) => n + r.net, 0),
    loss = losses.reduce((n, r) => n + r.net, 0);
  let equity = 0,
    peak = 0,
    drawdown = 0;
  const curve = [
    0,
    ...rows.map((r) => {
      equity += r.net;
      peak = Math.max(peak, equity);
      drawdown = Math.max(drawdown, peak - equity);
      return equity;
    }),
  ];
  const ranks = [...new Set(rows.map((r) => r.strategy))]
    .map((name) => {
      const group = rows.filter((r) => r.strategy === name);
      return {
        name,
        count: group.length,
        net: group.reduce((n, r) => n + r.net, 0),
        win: (100 * group.filter((r) => r.net > 0).length) / group.length,
      };
    })
    .sort((a, b) => b.net - a.net);
  const health = p.broker || {},
    synced = fresh(health.updated_at) && !health.error;
  return (
    <div className="dashboard">
      <div className="filters">
        <div className="segmented">
          {["Today", "7 days", "30 days", "All saved"].map((v) => (
            <button
              key={v}
              aria-pressed={v === period}
              onClick={() => setPeriod(v)}
            >
              {v}
            </button>
          ))}
        </div>
        <select
          aria-label="History scope"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        >
          <option>Current account</option>
          <option>All saved accounts</option>
        </select>
      </div>
      <div className="context-bar">
        <Activity size={15} />
        <Badge tone={p.settings?.enabled ? "positive" : ""}>
          {p.settings?.enabled ? "Entries enabled" : "Entries paused"}
        </Badge>
        <span>
          {synced
            ? "Broker synced " + ct(health.updated_at)
            : "Broker data unavailable or stale"}
        </span>
        <span>
          {synced
            ? `${health.positions?.length || 0} positions / ${health.orders?.length || 0} orders`
            : "Exposure not verified"}
        </span>
        <span className="push">
          Loss lock:{" "}
          {p.gate?.locked
            ? "Locked"
            : p.gate?.baseline != null
              ? "Clear"
              : "Not verified"}
        </span>
      </div>
      <div className="metric-band">
        <Metric
          label="Net realized P&L"
          value={money(net)}
          tone={tone(net)}
          detail="Broker-matched trades, after costs"
        />
        <Metric
          label="Win rate"
          value={
            rows.length
              ? `${((100 * wins.length) / rows.length).toFixed(1)}%`
              : "--"
          }
          detail={`${wins.length} wins / ${losses.length} losses`}
        />
        <Metric label="Closed trades" value={rows.length} />
        <Metric
          label="Profit factor"
          value={loss ? (gain / -loss).toFixed(2) : "--"}
        />
        <Metric label="Max drawdown" value={money(drawdown)} />
      </div>
      <div className="analysis-grid">
        <section>
          <div className="section-heading">
            <h2>Realized equity</h2>
            <span className="equity-label">USD / CLOSED TRADES</span>
          </div>
          <Equity values={curve} />
          <div className="minor-metrics">
            <Metric
              label="Average win"
              value={wins.length ? money(gain / wins.length) : "--"}
            />
            <Metric
              label="Average loss"
              value={losses.length ? money(loss / losses.length) : "--"}
            />
            <Metric
              label="Expectancy / trade"
              value={rows.length ? money(net / rows.length) : "--"}
            />
            <Metric
              label="Trading costs"
              value={money(rows.reduce((n, r) => n + r.costs, 0))}
            />
          </div>
        </section>
        <section className="aside-divider">
          <div className="dashboard-status">
            <div className="section-heading">
              <h2>Execution status</h2>
              <ShieldCheck size={17} />
            </div>
            <div className="detail-row">
              <span>Broker connection</span>
              <b className={synced ? "positive" : "warning"}>
                {synced ? "Verified" : "Unverified"}
              </b>
            </div>
            <div className="detail-row">
              <span>Open positions</span>
              <b>{synced ? health.positions?.length || 0 : "--"}</b>
            </div>
            <div className="detail-row">
              <span>Working orders</span>
              <b>{synced ? health.orders?.length || 0 : "--"}</b>
            </div>
            <a href="#execution">
              View execution <ArrowUpRight size={14} />
            </a>
          </div>
          <div className="section-heading">
            <h2>Strategy performance</h2>
          </div>
          {ranks.length ? (
            ranks.map((r) => (
              <div className="rank-row" key={r.name}>
                <div>
                  <b>{r.name}</b>
                  <small>
                    {r.count} trades · {r.win.toFixed(0)}% win rate
                  </small>
                </div>
                <strong className={tone(r.net)}>{money(r.net)}</strong>
                <span className="rank-track">
                  <i
                    style={{
                      width: `${Math.max(2, (Math.abs(r.net) / Math.max(1, ...ranks.map((x) => Math.abs(x.net)))) * 100)}%`,
                      background:
                        r.net < 0 ? "var(--negative)" : "var(--positive)",
                    }}
                  />
                </span>
              </div>
            ))
          ) : (
            <Empty title="Awaiting completed trades" />
          )}
          <h3 className="spaced">By instrument</h3>
          {["MNQ", "MES", "MYM"].map((s) => (
            <div className="detail-row" key={s}>
              <span>{s}</span>
              <b>
                {money(
                  rows
                    .filter((r) => r.symbol === s)
                    .reduce((n, r) => n + r.net, 0),
                )}
              </b>
            </div>
          ))}
        </section>
      </div>
      <div className="section-heading">
        <h2>Execution journal</h2>
        <span>Newest first · Chicago time</span>
      </div>
      <Table
        heads={[
          "Closed",
          "Instrument",
          "Strategy",
          "Side",
          "Qty",
          "Net P&L",
          "Costs",
        ]}
        rows={[...rows]
          .reverse()
          .slice(0, 40)
          .map((r) => [
            ct(r.closed_at),
            r.symbol,
            r.strategy,
            <Badge tone={r.direction === "LONG" ? "positive" : "negative"}>
              {r.direction}
            </Badge>,
            r.quantity,
            <b className={tone(r.net)}>{money(r.net)}</b>,
            money(r.costs),
          ])}
        empty="No matched closed executions in this period"
      />
      <div className="footnote">
        Watch signals, manual trades and tests are excluded.{" "}
        {Math.max(
          0,
          jobs.filter((j: Json) => j.state === "Closed").length - all.length,
        )}{" "}
        unmatched closed jobs excluded.{" "}
        {rows.length < 20 ? "Small sample: fewer than 20 closed trades." : ""}
      </div>
    </div>
  );
}

function Equity({ values }: { values: number[] }) {
  const root = useState(() => Math.random().toString(36).slice(2))[0];
  if (values.length < 2)
    return (
      <div className="equity-empty">
        <Empty
          title="No realized equity curve yet"
          detail="The curve appears after matched broker exits."
        />
      </div>
    );
  // Domain chart, not a decorative background; all points are actual closed-trade results.
  const min = Math.min(0, ...values),
    max = Math.max(1, ...values),
    span = max - min || 1;
  const points = values
    .map(
      (n, i) =>
        `${40 + (i / (values.length - 1)) * 720},${210 - ((n - min) / span) * 180}`,
    )
    .join(" ");
  return (
    <svg
      className="equity-chart"
      viewBox="0 0 800 250"
      role="img"
      aria-label="Realized closed-trade equity"
    >
      <title id={root}>Realized equity</title>
      {[0, 0.5, 1].map((r) => (
        <g key={r}>
          <line
            x1="40"
            x2="760"
            y1={210 - r * 180}
            y2={210 - r * 180}
            stroke="#343c33"
          />
          <text x="40" y={200 - r * 180} fill="#899385" fontSize="11">
            {money(min + r * span)}
          </text>
        </g>
      ))}
      <polyline points={points} fill="none" stroke="#b3c9a3" strokeWidth="2" />
    </svg>
  );
}
