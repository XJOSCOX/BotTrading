import { memo, useEffect, useState } from "react";
import { isConnected } from "../store";
import {
  Download,
  Play,
  RefreshCw,
  Upload,
  Square,
  RotateCcw,
} from "lucide-react";
import { api, money, ct, type Json } from "../api";
import { Field, Metric, Notice, Table, Toggle, Badge } from "../components";
import { Tabs } from "./Tabs";
import { type PageProps } from "../pageTypes";

function local(value: Date) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}
function Plot({
  values,
  label,
  bars = false,
}: {
  values: number[];
  label: string;
  bars?: boolean;
}) {
  if (!values.length)
    return (
      <Notice>No completed observations for {label.toLowerCase()}.</Notice>
    );
  const lo = bars ? Math.min(0, ...values) : Math.min(...values),
    hi = Math.max(0, ...values),
    span = hi - lo || 1;
  const y = (v: number) => 160 - (140 * (v - lo)) / span;
  return (
    <figure className="lab-plot">
      <figcaption>{label}</figcaption>
      <svg viewBox="0 0 640 180" role="img" aria-label={label}>
        <line
          x1="36"
          x2="630"
          y1={y(0)}
          y2={y(0)}
          stroke="currentColor"
          opacity=".2"
        />
        <text x="0" y="18" fill="currentColor" fontSize="11">
          {hi.toFixed(0)}
        </text>
        <text x="0" y="160" fill="currentColor" fontSize="11">
          {lo.toFixed(0)}
        </text>
        {bars ? (
          values.map((v, i) => (
            <rect
              key={i}
              x={38 + (i * 590) / values.length}
              y={Math.min(y(v), y(0))}
              width={Math.max(1, 580 / values.length)}
              height={Math.max(1, Math.abs(y(v) - y(0)))}
              fill={v >= 0 ? "#78bfa5" : "#dc8f8f"}
            >
              <title>{v.toFixed(2)}</title>
            </rect>
          ))
        ) : (
          <polyline
            points={values
              .map(
                (v, i) =>
                  `${38 + (i * 590) / Math.max(1, values.length - 1)},${y(v)}`,
              )
              .join(" ")}
            fill="none"
            stroke="#9db8a7"
            strokeWidth="2"
          />
        )}
      </svg>
    </figure>
  );
}

function Candles({ bars }: { bars: Json[] }) {
  const rows = bars.slice(0, 160);
  if (!rows.length) return null;
  const low = Math.min(...rows.map((r) => r.low)),
    high = Math.max(...rows.map((r) => r.high));
  const y = (v: number) => 210 - (190 * (v - low)) / (high - low || 1);
  return (
    <figure className="lab-plot">
      <figcaption>
        Actual minute bars / {ct(rows[0].time)} – {ct(rows.at(-1)?.time)}
      </figcaption>
      <svg
        viewBox="0 0 800 230"
        role="img"
        aria-label="Historical trade candles"
      >
        {rows.map((r, i) => {
          const x = 10 + (i * 780) / rows.length,
            color = r.close >= r.open ? "#78bfa5" : "#dc8f8f";
          return (
            <g key={r.time}>
              <title>{`${r.time} O ${r.open} H ${r.high} L ${r.low} C ${r.close}`}</title>
              <line x1={x} x2={x} y1={y(r.high)} y2={y(r.low)} stroke={color} />
              <rect
                x={x - 1}
                y={Math.min(y(r.open), y(r.close))}
                width={Math.max(1, 600 / rows.length)}
                height={Math.max(1, Math.abs(y(r.open) - y(r.close)))}
                fill={color}
              />
            </g>
          );
        })}
      </svg>
    </figure>
  );
}

export const ValidationLab = memo(
  function ValidationLab({ act, busy }: PageProps) {
    const [view, setView] = useState<Json | null>(null),
      [error, setError] = useState(""),
      [tab, setTab] = useState("Datasets");
    const [symbol, setSymbol] = useState("MNQ"),
      [contract, setContract] = useState(""),
      [expiration, setExpiration] = useState("");
    const [start, setStart] = useState(
        local(new Date(Date.now() - 7 * 86400000)),
      ),
      [end, setEnd] = useState(local(new Date()));
    const [review, setReview] = useState(false),
      [note, setNote] = useState(""),
      [csv, setCsv] = useState(""),
      [source, setSource] = useState(""),
      [quality, setQuality] = useState<Json | null>(null);
    const [datasets, setDatasets] = useState<string[]>([]),
      [strategies, setStrategies] = useState<string[]>(["crt", "reversal"]);
    const [fees, setFees] = useState(0.5),
      [slip, setSlip] = useState(1),
      [quantity, setQuantity] = useState(1),
      [risk, setRisk] = useState(75),
      [positions, setPositions] = useState(1),
      [cooldown, setCooldown] = useState(5),
      [balance, setBalance] = useState(50000);
    const [session, setSession] = useState("all"),
      [arbitration, setArbitration] = useState("conservative"),
      [exit, setExit] = useState("baseline"),
      [compareExits, setCompareExits] = useState(false),
      [comparePortfolios, setComparePortfolios] = useState(false),
      [folds, setFolds] = useState(false),
      [sensitivity, setSensitivity] = useState(false);
    const [run, setRun] = useState<Json | null>(null),
      [window, setWindow] = useState<Json | null>(null);
    const [configText, setConfigText] = useState<string | null>(null);
    const load = async () => {
      try {
        const data = await api("/validation-lab");
        setView(data);
        setConfigText(
          (previous) =>
            previous ?? JSON.stringify(data.configurations, null, 2),
        );
        setError("");
      } catch (e) {
        setError(String(e));
      }
    };
    useEffect(() => {
      void load();
      const refresh = () => void load();
      globalThis.window.addEventListener("gox-research-updated", refresh);
      const timer = setInterval(() => {
        if (!isConnected()) void load();
      }, 2000);
      return () => {
        clearInterval(timer);
        globalThis.window.removeEventListener("gox-research-updated", refresh);
      };
    }, []);
    const choose = (list: string[], value: string, checked: boolean) =>
      checked ? [...list, value] : list.filter((v) => v !== value);
    const metadata = () => ({
      symbol,
      contract_id: contract,
      expiration,
      start: new Date(start).toISOString(),
      end: new Date(end).toISOString(),
      calendar_reviewed: review,
      calendar_note: note,
    });
    const selectedRun = async (id: string) => {
      try {
        setRun(await api("/validation-lab/runs/" + id));
        setWindow(null);
        setTab("Performance");
      } catch (e) {
        setError(String(e));
      }
    };
    if (!view)
      return (
        <Notice danger={!!error}>{error || "Loading research datasets"}</Notice>
      );
    const metrics = run?.result.summary.metrics;
    return (
      <section className="validation-lab">
        <div className="section-heading">
          <Badge>HISTORICAL / SIMULATED</Badge>
          <button onClick={() => void load()}>
            <RefreshCw size={16} />
            Refresh research
          </button>
        </div>
        {error && <Notice danger>{error}</Notice>}
        <Tabs
          values={[
            "Datasets",
            "Backtesting",
            "Performance",
            "Trade explorer",
            "Jobs",
          ]}
          selected={tab}
          onChange={setTab}
        />
        {tab === "Datasets" && (
          <>
            <div className="section-heading">
              <h2>Contract datasets</h2>
              <span>
                {view.credentials_present
                  ? "Provider credentials saved / history access unverified"
                  : "Provider credentials missing"}
              </span>
            </div>
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                try {
                  const result = await act(
                    "/validation-lab/history",
                    metadata(),
                  );
                  if (result) {
                    setTab("Jobs");
                    await load();
                  }
                } catch (e) {
                  setError(String(e));
                }
              }}
            >
              <div className="fields three">
                <Field label="Instrument">
                  <select
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                  >
                    {["MNQ", "MES", "MYM", "NQ", "ES", "YM"].map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Actual contract ID">
                  <input
                    required
                    value={contract}
                    onChange={(e) => setContract(e.target.value)}
                  />
                </Field>
                <Field label="Contract expiration">
                  <input
                    type="date"
                    required
                    value={expiration}
                    onChange={(e) => setExpiration(e.target.value)}
                  />
                </Field>
                <Field label="Historical period">
                  <select
                    defaultValue="7"
                    onChange={(e) => {
                      if (e.target.value !== "custom") {
                        const until = new Date();
                        setEnd(local(until));
                        setStart(
                          local(
                            new Date(
                              until.getTime() -
                                Number(e.target.value) * 86400000,
                            ),
                          ),
                        );
                      }
                    }}
                  >
                    {[7, 30, 90, 180].map((d) => (
                      <option key={d} value={d}>
                        Previous {d} days
                      </option>
                    ))}
                    <option value="custom">Custom</option>
                  </select>
                </Field>
                <Field label="Start / local time">
                  <input
                    type="datetime-local"
                    required
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  />
                </Field>
                <Field label="End exclusive / local time">
                  <input
                    type="datetime-local"
                    required
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  />
                </Field>
              </div>
              <Toggle
                label="I reviewed this interval's CME session / holiday calendar"
                value={review}
                onChange={setReview}
              />
              <Field label="Calendar review reference">
                <input
                  required={review}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </Field>
              <div className="form-actions">
                <button className="primary" disabled={busy}>
                  <Download size={16} />
                  Retrieve contract history
                </button>
                <button
                  type="button"
                  disabled={busy || !contract || !expiration}
                  onClick={async () => {
                    try {
                      const result = await act(
                        "/validation-lab/import-saved",
                        metadata(),
                      );
                      if (result) {
                        setQuality(result.dataset.quality);
                        await load();
                      }
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  <Upload size={16} />
                  Use existing saved history
                </button>
              </div>
            </form>
            <details>
              <summary>Import actual historical minute CSV</summary>
              <div className="fields three">
                <Field label="Minute CSV">
                  <input
                    type="file"
                    accept=".csv"
                    onChange={async (e) => {
                      if (e.target.files?.[0])
                        setCsv(await e.target.files[0].text());
                    }}
                  />
                </Field>
                <Field label="Historical source">
                  <input
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                  />
                </Field>
              </div>
              <button
                disabled={busy || !csv || !source || !contract || !expiration}
                onClick={async () => {
                  try {
                    const result = await act("/validation-lab/import", {
                      ...metadata(),
                      csv,
                      source,
                      volume_provenance:
                        "User-declared traded volume; see source",
                    });
                    if (result) {
                      setQuality(result.dataset.quality);
                      await load();
                    }
                  } catch (e) {
                    setError(String(e));
                  }
                }}
              >
                <Upload size={16} />
                Import research dataset
              </button>
            </details>
            <Table
              heads={[
                "Instrument",
                "Contract",
                "Status",
                "Candles",
                "Coverage",
                "Missing",
                "Verified",
                "Actions",
              ]}
              rows={view.datasets.map((d: Json) => [
                d.symbol,
                d.contract_id,
                <Badge tone={d.quality.eligible ? "" : "warning"}>
                  {d.quality.status}
                </Badge>,
                d.quality.candles,
                d.quality.coverage_percent == null
                  ? "Not verified"
                  : d.quality.coverage_percent.toFixed(2) + "%",
                d.quality.missing_candles,
                ct(d.quality.verified_at),
                <div className="form-actions">
                  <button onClick={() => setQuality(d.quality)}>Quality</button>
                  <a href={`/api/validation-lab/datasets/${d.id}/export`}>
                    <Download size={16} />
                    CSV
                  </a>
                </div>,
              ])}
            />
            {quality && (
              <>
                <h2>Data quality / {quality.symbol}</h2>
                <Table
                  heads={["Property", "Observed"]}
                  rows={Object.entries(quality).map(([k, v]) => [
                    k,
                    typeof v === "object"
                      ? JSON.stringify(v)
                      : String(v ?? "Not verified"),
                  ])}
                />
              </>
            )}
          </>
        )}
        {tab === "Backtesting" && (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const result = await act("/validation-lab/run", {
                  datasets,
                  strategies,
                  start: new Date(start).toISOString(),
                  end: new Date(end).toISOString(),
                  initial_balance: balance,
                  configurations: Object.fromEntries(
                    Object.entries(JSON.parse(configText || "{}")).filter(
                      ([key]) => strategies.includes(key),
                    ),
                  ),
                  session,
                  execution: {
                    commission_per_side: fees,
                    zero_cost_acknowledged: fees === 0,
                    slippage_ticks: slip,
                    requested_quantity: quantity,
                    max_trade_risk: risk,
                    max_open_risk: risk * positions,
                    max_group_risk: risk * positions,
                    max_positions: positions,
                    max_group_positions: positions,
                    cooldown_minutes: cooldown,
                    mode: arbitration,
                  },
                  exit_policy: {
                    enabled: true,
                    mode: exit,
                    partial_targets:
                      exit === "partial" || exit === "hybrid" ? [[1, 1]] : [],
                  },
                  compare_exits: compareExits,
                  compare_portfolios: comparePortfolios,
                  walk_forward: folds,
                  sensitivity,
                });
                if (result) {
                  setTab("Jobs");
                  await load();
                }
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            <h2>Verified contract datasets</h2>
            <div className="fields three">
              {view.datasets.map((d: Json) => (
                <Toggle
                  key={d.id}
                  label={`${d.symbol} / ${d.contract_id} / ${d.quality.status}`}
                  value={datasets.includes(d.id)}
                  disabled={
                    !d.quality.candles ||
                    ["invalid", "unsupported", "unavailable"].includes(
                      d.quality.status,
                    )
                  }
                  onChange={(v) => {
                    setDatasets(choose(datasets, d.id, v));
                    if (v) {
                      setStart(local(new Date(d.start)));
                      setEnd(local(new Date(d.end)));
                    }
                  }}
                />
              ))}
            </div>
            <h2>Registered strategies</h2>
            <div className="fields three">
              {view.strategies.map((s: Json) => (
                <Toggle
                  key={s.id}
                  label={`${s.name} / ${s.minutes} min`}
                  value={strategies.includes(s.id)}
                  onChange={(v) => setStrategies(choose(strategies, s.id, v))}
                />
              ))}
            </div>
            <details>
              <summary>Strategy configuration snapshot</summary>
              <Field label="Research-only strategy configurations">
                <textarea
                  rows={14}
                  value={configText || ""}
                  onChange={(e) => setConfigText(e.target.value)}
                />
              </Field>
            </details>
            <div className="fields three">
              {[
                ["Initial simulated balance", balance, setBalance],
                ["Commission / contract / side", fees, setFees],
                ["Adverse slippage / ticks", slip, setSlip],
                ["Maximum contracts", quantity, setQuantity],
                ["Per-trade research risk", risk, setRisk],
                ["Simultaneous positions", positions, setPositions],
                ["Cooldown / minutes", cooldown, setCooldown],
              ].map(([label, value, setter]: any) => (
                <Field key={label} label={label}>
                  <input
                    type="number"
                    min={
                      label.includes("Commission") ||
                      label.includes("Cooldown") ||
                      label.includes("slippage")
                        ? 0
                        : 1
                    }
                    step={label.includes("Commission") ? ".01" : "1"}
                    max={
                      label === "Maximum contracts"
                        ? 4
                        : label === "Simultaneous positions"
                          ? 2
                          : undefined
                    }
                    required
                    value={value}
                    onChange={(e) => setter(+e.target.value)}
                  />
                </Field>
              ))}
              <Field label="Trading session">
                <select
                  value={session}
                  onChange={(e) => setSession(e.target.value)}
                >
                  {["all", "Regular", "Overnight"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="Arbitration">
                <select
                  value={arbitration}
                  onChange={(e) => setArbitration(e.target.value)}
                >
                  {[
                    "conservative",
                    "first_confirmed",
                    "configured_priority",
                  ].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="Exit policy">
                <select value={exit} onChange={(e) => setExit(e.target.value)}>
                  {[
                    "baseline",
                    "fixed",
                    "breakeven",
                    "trailing",
                    "profit_lock",
                    "partial",
                    "hybrid",
                  ].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="Test start / local">
                <input
                  type="datetime-local"
                  required
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </Field>
              <Field label="Test end exclusive / local">
                <input
                  type="datetime-local"
                  required
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                />
              </Field>
            </div>
            <div className="fields two">
              <Toggle
                label="Compare ten exit policies"
                value={compareExits}
                onChange={setCompareExits}
              />
              <Toggle
                label="Compare portfolio arbitration / capacity / risk"
                value={comparePortfolios}
                onChange={setComparePortfolios}
              />
              <Toggle
                label="Training / validation / test and rolling windows"
                value={folds}
                onChange={setFolds}
              />
              <Toggle
                label="Commission and slippage sensitivity"
                value={sensitivity}
                onChange={setSensitivity}
              />
            </div>
            <button
              className="primary"
              disabled={busy || !datasets.length || !strategies.length}
            >
              <Play size={16} />
              Run historical validation
            </button>
          </form>
        )}
        {tab === "Performance" && (
          <>
            <h2>Saved simulated results</h2>
            <Table
              heads={["Saved", "Trades", "Net simulated", "Revision", "Open"]}
              rows={view.runs.map((r: Json) => [
                ct(r.created_at),
                r.metrics.trades,
                money(r.metrics.net),
                r.code.commit.slice(0, 8),
                <button onClick={() => void selectedRun(r.id)}>
                  Inspect run
                </button>,
              ])}
            />
            {run && (
              <>
                <div className="section-heading">
                  <h2>Research run / {run.id.slice(0, 10)}</h2>
                  <div className="form-actions">
                    <a
                      href={`/api/validation-lab/runs/${run.id}/export?format=html`}
                    >
                      <Download size={16} />
                      Report
                    </a>
                    <a
                      href={`/api/validation-lab/runs/${run.id}/export?format=csv`}
                    >
                      <Download size={16} />
                      Trades CSV
                    </a>
                  </div>
                </div>
                <Notice>{run.result.lab.statistical_warning}</Notice>
                <div className="metrics">
                  {[
                    ["Net simulated P&L", money(metrics.net)],
                    ["Trades", metrics.trades],
                    [
                      "Win rate",
                      metrics.win_rate == null
                        ? "--"
                        : metrics.win_rate.toFixed(1) + "%",
                    ],
                    [
                      "Profit factor",
                      metrics.profit_factor?.toFixed(2) ?? "--",
                    ],
                    ["Drawdown", money(metrics.max_drawdown)],
                  ].map(([k, v]) => (
                    <Metric key={String(k)} label={String(k)} value={v} />
                  ))}
                </div>
                <div className="lab-plots">
                  <Plot
                    label="Marked equity / simulated USD"
                    values={run.result.lab.equity}
                  />
                  <Plot
                    label="Drawdown / USD"
                    values={run.result.lab.drawdown}
                  />
                  <Plot
                    label="Monthly net / chronological"
                    values={Object.values(run.result.lab.months).map(
                      (r: any) => r.net,
                    )}
                    bars
                  />
                  <Plot
                    label="Trade profit distribution / count by USD bin"
                    values={run.result.lab.profit_histogram.map(
                      (r: Json) => r.count,
                    )}
                    bars
                  />
                </div>
                <details>
                  <summary>Complete metrics and accounting</summary>
                  <Table
                    heads={["Metric", "Value"]}
                    rows={Object.entries({
                      ...metrics,
                      ...run.result.lab.diagnostics,
                      open_positions: run.result.summary.open_positions,
                      realized: run.result.summary.realized,
                      unrealized: run.result.summary.unrealized,
                      planned_open_risk: run.result.summary.planned_open_risk,
                      peak_risk_utilization_percent:
                        run.result.lab.peak_risk_utilization_percent,
                    })
                      .filter(([, v]) => typeof v !== "object")
                      .map(([k, v]) => [k, String(v ?? "Insufficient data")])}
                  />
                </details>
                <div className="lab-breakdowns">
                  {[
                    ["Strategy contribution", run.result.summary.strategies],
                    ["Session performance", run.result.lab.sessions],
                    [
                      "Market regime / overlapping labels",
                      run.result.lab.regimes,
                    ],
                    ["Exit-policy comparison", run.comparisons.exits?.policies],
                    ["Portfolio comparison", run.comparisons.portfolios],
                    ["Cost sensitivity", run.comparisons.costs],
                  ].map(
                    ([label, groups]: any) =>
                      groups && (
                        <section key={label}>
                          <h2>{label}</h2>
                          <Plot
                            label={label + " / simulated net USD"}
                            values={Object.values(groups).map(
                              (r: any) =>
                                r.summary?.metrics.net ??
                                r.metrics?.net ??
                                r.net,
                            )}
                            bars
                          />
                          <Table
                            heads={["Group", "Trades", "Net", "Drawdown"]}
                            rows={Object.entries(groups).map(
                              ([name, row]: any) => {
                                const m =
                                  row.summary?.metrics ?? row.metrics ?? row;
                                return [
                                  name,
                                  m.trades,
                                  money(m.net),
                                  money(m.max_drawdown),
                                ];
                              },
                            )}
                          />
                        </section>
                      ),
                  )}
                </div>
                {run.comparisons.chronological && (
                  <>
                    <h2>Chronological windows / fixed parameters</h2>
                    <Table
                      heads={[
                        "Window",
                        "Start",
                        "End",
                        "Trades",
                        "Net",
                        "Fitted",
                      ]}
                      rows={run.comparisons.chronological.map((r: Json) => [
                        r.label,
                        ct(r.start),
                        ct(r.end),
                        r.summary.metrics.trades,
                        money(r.summary.metrics.net),
                        String(r.parameters_fitted),
                      ])}
                    />
                  </>
                )}
              </>
            )}
          </>
        )}
        {tab === "Trade explorer" &&
          (!run ? (
            <Notice>Select a saved historical run in Performance.</Notice>
          ) : (
            <>
              <h2>Completed simulated trades</h2>
              <Table
                heads={[
                  "Strategy",
                  "Instrument",
                  "Signal detected",
                  "Strategy confirmed",
                  "Entry fill time",
                  "Entry",
                  "Qty",
                  "Exit",
                  "Net",
                  "Details",
                ]}
                rows={run.result.state.trades.map((t: Json, i: number) => [
                  t.strategy,
                  t.symbol,
                  ct(t.signal_detected_at),
                  ct(t.confirmed_at),
                  ct(t.entry_time),
                  t.entry,
                  t.quantity,
                  ct(t.exit_time),
                  money(t.net),
                  <button
                    onClick={async () => {
                      try {
                        setWindow(
                          await api(
                            `/validation-lab/runs/${run.id}/trades/${i}`,
                          ),
                        );
                      } catch (e) {
                        setError(String(e));
                      }
                    }}
                  >
                    Inspect trade
                  </button>,
                ])}
              />
              {window && (
                <>
                  <Candles bars={window.bars} />
                  <Table
                    heads={["Field", "Observed / simulated value"]}
                    rows={Object.entries(window.trade).map(([k, v]) => [
                      k,
                      typeof v === "object"
                        ? JSON.stringify(v)
                        : String(v ?? "--"),
                    ])}
                  />
                </>
              )}
            </>
          ))}
        {tab === "Jobs" && (
          <>
            <h2>Persistent research jobs</h2>
            <Table
              heads={[
                "Kind",
                "Status",
                "Phase / blocker",
                "Progress",
                "Updated",
                "Actions",
              ]}
              rows={view.jobs.map((j: Json) => [
                j.kind,
                <Badge>{j.status}</Badge>,
                j.message || j.phase || "--",
                (j.progress * 100).toFixed(0) + "%",
                ct(j.updated_at),
                <div className="form-actions">
                  {j.status !== "complete" && (
                    <>
                      <button
                        disabled={!j.can_resume || busy}
                        onClick={async () => {
                          await act(`/validation-lab/jobs/${j.id}/resume`, {});
                          await load();
                        }}
                      >
                        <RotateCcw size={16} />
                        Resume
                      </button>
                      <button
                        disabled={busy}
                        onClick={async () => {
                          await act(`/validation-lab/jobs/${j.id}/cancel`, {});
                          await load();
                        }}
                      >
                        <Square size={16} />
                        Cancel
                      </button>
                    </>
                  )}
                  {j.kind === "validation" && j.status === "complete" && (
                    <button onClick={() => void selectedRun(j.result_id)}>
                      Results
                    </button>
                  )}
                </div>,
              ])}
            />
          </>
        )}
      </section>
    );
  },
  (previous, next) =>
    previous.busy === next.busy && previous.profile === next.profile,
);
