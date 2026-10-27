import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Play, RefreshCw, Save } from "lucide-react";
import { api, ct, money, type Json } from "../api";
import { Badge, Field, Metric, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";
import { Tabs } from "./Tabs";

export function StrategyManager({ config, profile, act, busy }: PageProps) {
  const revision = useRef(0);
  const [view, setView] = useState<Json | null>(null),
    [draft, setDraft] = useState<Json | null>(null);
  const [tab, setTab] = useState("Overview"),
    [error, setError] = useState(""),
    [dirty, setDirty] = useState(false);
  const [datasets, setDatasets] = useState<Json[]>([
    { symbol: "MNQ", contract_id: "", csv: "" },
  ]);
  const [walk, setWalk] = useState(false),
    [compare, setCompare] = useState(false),
    [selectedRun, setSelectedRun] = useState("");
  const load = async () => {
    const requested = revision.current;
    try {
      const next = await api("/manager?profile=" + profile);
      if (requested === revision.current) {
        setView(next);
        setError("");
      }
      return next;
    } catch (e) {
      if (requested === revision.current) setError(String(e));
      return null;
    }
  };
  useEffect(() => {
    revision.current += 1;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const requested = revision.current;
      try {
        const next = await api("/manager?profile=" + profile);
        if (active && requested === revision.current) {
          setView(next);
          setError("");
        }
      } catch (e) {
        if (active && requested === revision.current) setError(String(e));
      }
      if (active) timer = setTimeout(() => void poll(), 5000);
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [profile]);
  useEffect(() => {
    if (view && !dirty) setDraft(structuredClone(view.policy));
  }, [view, dirty]);
  const change = (name: string, value: any) => {
    setDirty(true);
    setDraft((previous) => ({ ...previous, [name]: value }));
  };
  if (!view || !draft)
    return (
      <Notice danger={!!error}>{error || "Loading strategy manager"}</Notice>
    );
  const names: Record<string, string> = Object.fromEntries(
    config.strategies.map((spec: Json) => [spec.id, spec.name]),
  );
  const candidates: Json[] = view.candidates || [],
    decisions: Json[] = view.decisions || [];
  const byId = Object.fromEntries(
    decisions.map((row) => [row.candidate_id, row]),
  );
  const paper = view.runs.find(
    (run: Json) => run.kind === "portfolio_forward_paper",
  )?.record;
  const runs = view.runs.filter(
    (run: Json) => run.kind === "portfolio_backtest",
  );
  const run = runs.find((row: Json) => row.id === selectedRun)?.record;
  const result = tab === "Paper portfolio" ? paper : run;
  const arrayToggle = (name: string, id: string, enabled: boolean) => {
    const next = enabled
      ? [...draft[name], id]
      : draft[name].filter((value: string) => value !== id);
    change(name, next);
    if (name === "monitoring" && !enabled)
      change(
        "participating",
        draft.participating.filter((value: string) => value !== id),
      );
  };
  const candidateTable = (
    <Table
      heads={[
        "Strategy",
        "Instrument",
        "Direction",
        "Interval / mode",
        "Confirmed",
        "Price",
        "Stop",
        "Target",
        "Risk",
        "Eligibility",
        "Priority",
        "Decision",
        "Reason",
      ]}
      rows={candidates.map((row) => {
        const decision = byId[row.candidate_id] || {};
        return [
          names[row.strategy_id],
          row.symbol,
          row.direction,
          `${row.timeframe}m / ${row.classification}`,
          ct(row.confirmed_at),
          row.price ?? "--",
          row.stop ?? "--",
          row.target ?? "--",
          money(decision.planned_risk),
          decision.eligibility || "Unavailable",
          view.policy.priority.includes(row.strategy_id)
            ? view.policy.priority.indexOf(row.strategy_id) + 1
            : "--",
          decision.selected ? "Would select / not sent" : "Not selected",
          (decision.reasons || []).join("; "),
        ];
      })}
    />
  );
  return (
    <section className="strategy-manager" inert={busy}>
      <div className="section-heading">
        <div>
          <Badge>SHADOW / RESEARCH</Badge>
          <span className="muted">
            {profile === "leader" ? "Leader" : "Practice"} account view
          </span>
        </div>
        <button title="Refresh manager" onClick={() => void load()}>
          <RefreshCw size={16} /> Refresh
        </button>
      </div>
      {error && <Notice danger>{error}</Notice>}
      <Notice>
        Broker cutover is disabled. Research settings do not change account
        execution permissions, sizing or account loss safeguards.
      </Notice>
      <Tabs
        values={[
          "Overview",
          "Research policy",
          "Portfolio backtest",
          "Paper portfolio",
          "Decision journal",
        ]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Overview" && (
        <>
          <div className="metric-grid">
            <Metric
              label="Arbitration"
              value={view.policy.mode.replaceAll("_", " ")}
            />
            <Metric
              label="Research risk / trade"
              value={money(view.policy.max_trade_risk)}
            />
            <Metric
              label="Research open-risk budget"
              value={money(view.policy.max_open_risk)}
            />
            <Metric
              label="Pending reservations"
              value={view.reservations.length}
            />
          </div>
          <div className="detail-row">
            <span>Separate paper risk used / available</span>
            <span>
              {money(paper?.summary.planned_open_risk ?? 0)} /{" "}
              {money(
                Math.max(
                  0,
                  view.policy.max_open_risk -
                    (paper?.summary.planned_open_risk ?? 0),
                ),
              )}
            </span>
          </div>
          <div className="detail-row">
            <span>Broker snapshot</span>
            <Badge tone={view.broker_fresh ? "positive" : "warning"}>
              {view.broker_fresh
                ? "Fresh local reconciliation"
                : "Unavailable / stale"}
            </Badge>
          </div>
          <div className="detail-row">
            <span>Entry session</span>
            <span>{view.session.reason}</span>
          </div>
          <div className="detail-row">
            <span>Open-account exposure</span>
            <span>
              {!view.broker_fresh
                ? "Unknown / fresh broker snapshot required"
                : view.account_exposure_unresolved
                  ? "Present / not risk-authorized"
                  : "No unresolved exposure in local snapshot"}
            </span>
          </div>
          <h2>Current candidates</h2>
          {candidateTable}
          {view.adapter_rejections.length > 0 && (
            <Table
              heads={["Alert", "Strategy", "Adapter result"]}
              rows={view.adapter_rejections.map((row: Json) => [
                row.alert_id,
                row.strategy,
                row.reason,
              ])}
            />
          )}
          <button
            onClick={async () => {
              if (await act("/manager/evaluate/" + profile, {})) await load();
            }}
          >
            <Save size={16} /> Record shadow decisions
          </button>
        </>
      )}
      {tab === "Research policy" && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const saved = await act("/manager/policy", draft);
            if (saved) {
              revision.current += 1;
              setView((previous) =>
                previous ? { ...previous, policy: saved.policy } : previous,
              );
              setDirty(false);
              setDraft(saved.policy);
              await load();
            }
          }}
        >
          <div className="section-heading">
            <h2>Shared strategy participation</h2>
            {dirty && <Badge tone="warning">Unsaved changes</Badge>}
          </div>
          <Field label="Arbitration policy">
            <select
              value={draft.mode}
              onChange={(e) => change("mode", e.target.value)}
            >
              <option value="conservative">Conservative</option>
              <option value="first_confirmed">
                First valid confirmed signal
              </option>
              <option value="configured_priority">
                Configured strategy priority
              </option>
              <option value="evidence_research">
                Evidence ranking / unavailable pending reviewed OOS results
              </option>
            </select>
          </Field>
          <div className="manager-strategy-list">
            {draft.priority.map((id: string, index: number) => (
              <div className="manager-strategy-row" key={id}>
                <strong>{names[id]}</strong>
                <Toggle
                  label={names[id] + " monitoring"}
                  value={draft.monitoring.includes(id)}
                  onChange={(value) => arrayToggle("monitoring", id, value)}
                />
                <Toggle
                  label={names[id] + " research participation"}
                  value={draft.participating.includes(id)}
                  disabled={!draft.monitoring.includes(id)}
                  onChange={(value) => arrayToggle("participating", id, value)}
                />
                <Field label="Strategy risk budget ($)">
                  <input
                    aria-label={names[id] + " research budget"}
                    type="number"
                    min="0.01"
                    step="0.01"
                    placeholder="Shared budget"
                    value={
                      draft.strategy_budgets.find(
                        (row: any[]) => row[0] === id,
                      )?.[1] ?? ""
                    }
                    onChange={(e) =>
                      change("strategy_budgets", [
                        ...draft.strategy_budgets.filter(
                          (row: any[]) => row[0] !== id,
                        ),
                        ...(e.target.value ? [[id, +e.target.value]] : []),
                      ])
                    }
                  />
                </Field>
                <div className="manager-priority">
                  <span>{index + 1}</span>
                  {[-1, 1].map((delta) => (
                    <button
                      key={delta}
                      type="button"
                      className="icon"
                      title={
                        (delta < 0 ? "Increase" : "Decrease") +
                        " priority for " +
                        names[id]
                      }
                      disabled={
                        index + delta < 0 ||
                        index + delta >= draft.priority.length
                      }
                      onClick={() => {
                        const next = [...draft.priority];
                        [next[index], next[index + delta]] = [
                          next[index + delta],
                          next[index],
                        ];
                        change("priority", next);
                      }}
                    >
                      {delta < 0 ? (
                        <ArrowUp size={16} />
                      ) : (
                        <ArrowDown size={16} />
                      )}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <h2>Research instruments</h2>
          <div className="fields three">
            {["MNQ", "MES", "MYM", "NQ", "ES", "YM"].map((symbol) => (
              <Toggle
                key={symbol}
                label={symbol}
                value={draft.symbols.includes(symbol)}
                onChange={(enabled) =>
                  change(
                    "symbols",
                    enabled
                      ? [...draft.symbols, symbol]
                      : draft.symbols.filter(
                          (value: string) => value !== symbol,
                        ),
                  )
                }
              />
            ))}
          </div>
          <h2>Research portfolio limits</h2>
          <div className="fields three">
            {[
              "max_trade_risk",
              "max_open_risk",
              "max_daily_loss",
              "max_daily_loss_with_open",
              "max_positions",
              "max_per_symbol",
              "max_contracts",
              "requested_quantity",
              "max_group_positions",
              "max_group_risk",
              "max_group_gross",
              "max_group_net",
              "max_daily_trades",
              "max_consecutive_losses",
              "cooldown_minutes",
              "minimum_rr",
              "commission_per_side",
              "slippage_ticks",
              "protective_buffer",
            ].map((name) => (
              <Field key={name} label={name.replaceAll("_", " ")}>
                <input
                  type="number"
                  min="0"
                  step={
                    name.includes("risk") ||
                    name.includes("loss") ||
                    name.includes("gross") ||
                    name.includes("net") ||
                    [
                      "minimum_rr",
                      "commission_per_side",
                      "protective_buffer",
                    ].includes(name)
                      ? "0.01"
                      : "1"
                  }
                  required={name !== "commission_per_side"}
                  value={draft[name] ?? ""}
                  onChange={(e) =>
                    change(name, e.target.value === "" ? null : +e.target.value)
                  }
                />
              </Field>
            ))}
          </div>
          <Toggle
            label="Explicit zero-cost sensitivity acknowledgement"
            value={draft.zero_cost_acknowledged}
            onChange={(value) => change("zero_cost_acknowledged", value)}
          />
          <Toggle
            label="Enable separate portfolio paper entries"
            value={draft.paper_enabled}
            onChange={(value) => change("paper_enabled", value)}
          />
          <button className="primary" disabled={busy}>
            <Save size={16} /> Save research policy
          </button>
        </form>
      )}
      {tab === "Portfolio backtest" && (
        <>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (
                await act("/manager/backtest", {
                  datasets,
                  walk_forward: walk,
                  compare,
                })
              )
                await load();
            }}
          >
            <h2>Actual contract datasets</h2>
            <div className="fields three">
              <Field label="Instruments">
                <select
                  value={datasets.length}
                  onChange={(e) => {
                    const count = +e.target.value;
                    setDatasets(
                      Array.from(
                        { length: count },
                        (_, index) =>
                          datasets[index] || {
                            symbol: ["MNQ", "MES", "MYM"][index],
                            contract_id: "",
                            csv: "",
                          },
                      ),
                    );
                  }}
                >
                  {[1, 2, 3].map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </Field>
            </div>
            {datasets.map((dataset, index) => (
              <div className="fields three" key={index}>
                <Field label="Instrument">
                  <select
                    value={dataset.symbol}
                    onChange={(e) =>
                      setDatasets(
                        datasets.map((row, i) =>
                          i === index
                            ? { ...row, symbol: e.target.value }
                            : row,
                        ),
                      )
                    }
                  >
                    {["MNQ", "MES", "MYM", "NQ", "ES", "YM"].map((symbol) => (
                      <option key={symbol}>{symbol}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Actual contract ID">
                  <input
                    required
                    value={dataset.contract_id}
                    onChange={(e) =>
                      setDatasets(
                        datasets.map((row, i) =>
                          i === index
                            ? { ...row, contract_id: e.target.value }
                            : row,
                        ),
                      )
                    }
                  />
                </Field>
                <Field label="Finalized minute OHLCV / CSV">
                  <input
                    required
                    type="file"
                    accept=".csv"
                    onChange={async (e) => {
                      const file = e.target.files?.[0];
                      if (file) {
                        const contents = await file.text();
                        setDatasets((previous) =>
                          previous.map((row, i) =>
                            i === index ? { ...row, csv: contents } : row,
                          ),
                        );
                      }
                    }}
                  />
                </Field>
              </div>
            ))}
            <Toggle
              label="Chronological out-of-sample folds / fixed policy"
              value={walk}
              onChange={setWalk}
            />
            <Toggle
              label="Compare individual strategies and arbitration policies"
              value={compare}
              onChange={setCompare}
            />
            <button
              className="primary"
              disabled={busy || datasets.some((row) => !row.csv)}
            >
              <Play size={16} /> Run portfolio simulation
            </button>
          </form>
          <Field label="Saved portfolio backtest">
            <select
              value={selectedRun}
              onChange={(e) => setSelectedRun(e.target.value)}
            >
              <option value="">Select a run</option>
              {runs.map((row: Json) => (
                <option key={row.id} value={row.id}>
                  {row.id.slice(0, 12)} / {row.record.summary.metrics.trades}{" "}
                  trades
                </option>
              ))}
            </select>
          </Field>
        </>
      )}
      {tab === "Paper portfolio" && (
        <>
          <div className="section-heading">
            <Badge tone={view.policy.paper_enabled ? "positive" : ""}>
              {view.policy.paper_enabled
                ? "Paper entries enabled"
                : "Paper entries off"}
            </Badge>
            <span className="muted">
              {paper?.state.last_poll_at
                ? "Last worker observation " + ct(paper.state.last_poll_at)
                : "No worker observations"}
            </span>
          </div>
          <div className="form-actions">
            <button
              disabled={!view.policy.paper_enabled || busy}
              onClick={async () => {
                if (await act("/manager/paper/start", {})) await load();
              }}
            >
              <Play size={16} /> Start paper worker
            </button>
            <button
              onClick={async () => {
                if (await act("/manager/paper", {})) await load();
              }}
            >
              <RefreshCw size={16} /> Evaluate paper observations
            </button>
          </div>
          {!paper && (
            <Notice>
              No separate portfolio paper results. Existing strategy-level paper
              and broker history are unchanged.
            </Notice>
          )}
        </>
      )}
      {result && ["Paper portfolio", "Portfolio backtest"].includes(tab) && (
        <>
          <div className="metric-grid">
            <Metric
              label="Portfolio net"
              value={money(result.summary.metrics.net)}
            />
            <Metric
              label="Drawdown"
              value={money(result.summary.metrics.max_drawdown)}
            />
            <Metric
              label="Win rate"
              value={
                result.summary.metrics.win_rate == null
                  ? "--"
                  : result.summary.metrics.win_rate.toFixed(1) + "%"
              }
            />
            <Metric
              label="Expectancy"
              value={money(result.summary.metrics.expectancy)}
            />
            <Metric
              label="Profit factor"
              value={result.summary.metrics.profit_factor?.toFixed(2) ?? "--"}
            />
            <Metric
              label="Planned open risk"
              value={money(result.summary.planned_open_risk)}
            />
          </div>
          <h2>Strategy contribution</h2>
          <Table
            heads={["Strategy", "Trades", "Net", "Drawdown"]}
            rows={Object.entries(result.summary.strategies).map(
              ([name, row]: any) => [
                name,
                row.trades,
                money(row.net),
                money(row.max_drawdown),
              ],
            )}
          />
          <h2>Open simulated positions</h2>
          <Table
            heads={[
              "Owner",
              "Instrument",
              "Quantity",
              "Entry",
              "Protective stop",
            ]}
            rows={result.state.positions.map((row: Json) => [
              names[row.exposure.strategy_id],
              row.exposure.symbol,
              row.exposure.quantity,
              row.exposure.entry,
              row.exposure.stop,
            ])}
          />
          <h2>Simulated trades</h2>
          <Table
            heads={[
              "Closed",
              "Strategy",
              "Instrument",
              "Side",
              "Qty",
              "Entry",
              "Exit",
              "Net",
              "Reason",
            ]}
            rows={[...result.state.trades]
              .reverse()
              .slice(0, 100)
              .map((row: Json) => [
                ct(row.exit_time),
                names[row.strategy_id],
                row.symbol,
                row.direction,
                row.quantity,
                row.entry,
                row.exit,
                money(row.net),
                row.reason,
              ])}
          />
          <h2>Eligibility counts</h2>
          <Table
            heads={["Result", "Count"]}
            rows={Object.entries(result.summary.rejection_counts)}
          />
          {result.comparisons && (
            <>
              <h2>Policy comparisons</h2>
              <Table
                heads={["Scenario", "Trades", "Net", "Drawdown"]}
                rows={Object.entries(result.comparisons).map(
                  ([name, row]: any) => [
                    name,
                    row.metrics.trades,
                    money(row.metrics.net),
                    money(row.metrics.max_drawdown),
                  ],
                )}
              />
            </>
          )}
          {result.walk_forward && (
            <>
              <h2>Out-of-sample folds</h2>
              <Table
                heads={["Test begins", "Test ends", "Trades", "Net"]}
                rows={result.walk_forward.map((row: Json) => [
                  ct(row.test_start),
                  ct(row.test_end),
                  row.summary.metrics.trades,
                  money(row.summary.metrics.net),
                ])}
              />
            </>
          )}
          <h2>Portfolio decisions</h2>
          <DecisionTable rows={result.state.decisions} names={names} />
        </>
      )}
      {tab === "Decision journal" && (
        <>
          <h2>Persisted shadow and research decisions</h2>
          <DecisionTable rows={view.journal} names={names} />
          <h2>Persistent research reservations</h2>
          <Table
            heads={["Candidate", "Profile", "State", "Reconciliation"]}
            rows={view.reservations.map((row: Json) => [
              row.candidate.slice(0, 12),
              row.profile,
              row.status,
              row.reconciliation,
            ])}
          />
        </>
      )}
    </section>
  );
}

function DecisionTable({
  rows,
  names,
}: {
  rows: Json[];
  names: Record<string, string>;
}) {
  return (
    <Table
      heads={[
        "Time",
        "Strategy",
        "Profile",
        "Result",
        "Selected",
        "Qty",
        "Risk",
        "Available",
        "Scope",
        "Reason",
      ]}
      rows={[...rows]
        .sort((a, b) => b.decision_at.localeCompare(a.decision_at))
        .slice(0, 200)
        .map((row) => [
          ct(row.decision_at),
          names[row.strategy_id],
          row.account_profile,
          row.eligibility,
          row.selected ? "Simulation only" : "No",
          row.quantity,
          money(row.planned_risk),
          money(row.available_budget),
          row.checks_scope,
          row.reasons.join("; "),
        ])}
    />
  );
}
