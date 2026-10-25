import { useEffect, useState } from "react";
import { RefreshCw, Save, Play, Plus, Trash2 } from "lucide-react";
import { api, ct, money, type Json } from "../api";
import { Badge, Field, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";
import { Tabs } from "./Tabs";

export function TradeManagement({ profile, act, busy }: PageProps) {
  const [view, setView] = useState<Json | null>(null),
    [draft, setDraft] = useState<Json | null>(null),
    [dirty, setDirty] = useState(false),
    [tab, setTab] = useState("Positions"),
    [error, setError] = useState("");
  const [symbol, setSymbol] = useState("MNQ"),
    [contract, setContract] = useState(""),
    [csv, setCsv] = useState(""),
    [folds, setFolds] = useState(false);
  const load = async () => {
    try {
      const next = await api("/trade-management?profile=" + profile);
      setView(next);
      setError("");
      return next;
    } catch (e) {
      setError(String(e));
      return null;
    }
  };
  useEffect(() => {
    let active = true;
    void api("/trade-management?profile=" + profile)
      .then((next) => active && setView(next))
      .catch((e) => active && setError(String(e)));
    return () => {
      active = false;
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
      <Notice danger={!!error}>{error || "Loading trade management"}</Notice>
    );
  return (
    <section className="trade-management" inert={busy}>
      <div className="section-heading">
        <Badge>RESEARCH / PAPER</Badge>
        <button onClick={() => void load()}>
          <RefreshCw size={16} /> Refresh positions
        </button>
      </div>
      <Notice>
        Broker amendments and partial exits are blocked. New policies apply only
        to new opted-in research/paper positions. Software levels are not
        broker-confirmed orders.
      </Notice>
      {error && <Notice danger>{error}</Notice>}
      <Tabs
        values={[
          "Positions",
          "Exit policy",
          "Giveback review",
          "Policy comparison",
        ]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Positions" && (
        <>
          <h2>Broker positions / original management</h2>
          <Table
            heads={[
              "Strategy",
              "Instrument",
              "Actual fill",
              "Quantity",
              "Reported broker stop",
              "Protection",
              "Snapshot",
            ]}
            rows={view.broker_positions.map((row: Json) => [
              row.strategy,
              row.symbol,
              row.entry,
              row.quantity,
              row.broker_stop,
              row.protection,
              ct(row.broker_observed_at),
            ])}
          />
          <h2>Separate paper positions</h2>
          <Table
            heads={[
              "Population",
              "Strategy",
              "Instrument",
              "Fill",
              "Qty",
              "Mark",
              "Unrealized gross",
              "Peak episode gross",
              "MFE",
              "Giveback",
              "Current / max R",
              "Policy",
              "Protection",
            ]}
            rows={view.paper_positions.map((row: Json) => [
              row.population,
              row.strategy,
              row.symbol,
              row.entry,
              row.remaining,
              row.current_price,
              money(row.marked_unrealized_gross),
              money(row.peak_mark_gross),
              money(row.analytics.mfe_dollars),
              money(row.giveback_gross),
              row.current_r.toFixed(2) + " / " + row.max_r.toFixed(2),
              row.policy.mode,
              row.protection_status,
            ])}
          />
          {view.paper_positions.map((row: Json) => (
            <section className="protection-levels" key={row.trade_id}>
              <h3>
                {row.strategy} / {row.symbol}
              </h3>
              <Table
                heads={[
                  "Initial stop",
                  "Software stop",
                  "Break-even estimate",
                  "Profit-lock level",
                  "Next partial R",
                  "Final target",
                  "Protective quantity",
                ]}
                rows={[
                  [
                    row.initial_stop,
                    row.stop,
                    row.break_even_level,
                    row.locked_stop,
                    row.policy.partial_targets.find(
                      (_: any, index: number) =>
                        !row.completed_partials.includes(index),
                    )?.[0] ?? "--",
                    row.target,
                    row.remaining,
                  ],
                ]}
              />
            </section>
          ))}
        </>
      )}
      {tab === "Exit policy" && (
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            const result = await act("/trade-management/policy", draft);
            if (result) {
              setView((previous) =>
                previous ? { ...previous, policy: result.policy } : previous,
              );
              setDirty(false);
              setDraft(result.policy);
            }
          }}
        >
          <div className="section-heading">
            <h2>New-position research policy</h2>
            {dirty && <Badge tone="warning">Unsaved changes</Badge>}
          </div>
          <Toggle
            label="Apply central exits to new research/paper positions"
            value={draft.enabled}
            onChange={(value) => change("enabled", value)}
          />
          <div className="fields three">
            {Object.entries(draft)
              .filter(
                ([key, value]) =>
                  !["enabled", "version", "partial_targets"].includes(key) &&
                  typeof value !== "boolean",
              )
              .map(([key, value]) => {
                const choices: Record<string, any[]> = {
                  mode: [
                    "baseline",
                    "fixed",
                    "breakeven",
                    "trailing",
                    "profit_lock",
                    "partial",
                    "hybrid",
                  ],
                  target_method: [
                    "strategy",
                    "structural",
                    "rr",
                    "ticks",
                    "points",
                  ],
                  trailing_method: [
                    "fixed_ticks",
                    "atr",
                    "structure",
                    "extreme",
                    "adaptive",
                  ],
                  management_minutes: [5, 10, 15],
                };
                return (
                  <Field key={key} label={key.replaceAll("_", " ")}>
                    {choices[key] ? (
                      <select
                        value={value as any}
                        onChange={(e) =>
                          change(
                            key,
                            typeof value === "number"
                              ? +e.target.value
                              : e.target.value,
                          )
                        }
                      >
                        {choices[key].map((choice) => (
                          <option key={choice} value={choice}>
                            {choice}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="number"
                        min="0"
                        required
                        step="any"
                        value={value as number}
                        onChange={(e) => change(key, +e.target.value)}
                      />
                    )}
                  </Field>
                );
              })}
          </div>
          <div className="fields three">
            {Object.entries(draft)
              .filter(
                ([key, value]) =>
                  key !== "enabled" && typeof value === "boolean",
              )
              .map(([key, value]) => (
                <Toggle
                  key={key}
                  label={key.replaceAll("_", " ")}
                  value={value as boolean}
                  onChange={(next) => change(key, next)}
                />
              ))}
          </div>
          <h2>Explicit whole-contract partial targets</h2>
          {draft.partial_targets.map((row: any[], index: number) => (
            <div className="fields three" key={index}>
              <Field label={`Target ${index + 1} / R`}>
                <input
                  type="number"
                  required
                  min="0.01"
                  step="0.01"
                  value={row[0]}
                  onChange={(e) =>
                    change(
                      "partial_targets",
                      draft.partial_targets.map((v: any[], i: number) =>
                        i === index ? [+e.target.value, v[1]] : v,
                      ),
                    )
                  }
                />
              </Field>
              <Field label={`Target ${index + 1} / contracts`}>
                <input
                  type="number"
                  required
                  min="1"
                  max="4"
                  value={row[1]}
                  onChange={(e) =>
                    change(
                      "partial_targets",
                      draft.partial_targets.map((v: any[], i: number) =>
                        i === index ? [v[0], +e.target.value] : v,
                      ),
                    )
                  }
                />
              </Field>
              <button
                type="button"
                style={{ alignSelf: "end", height: 42 }}
                onClick={() =>
                  change(
                    "partial_targets",
                    draft.partial_targets.filter(
                      (_: any, i: number) => i !== index,
                    ),
                  )
                }
              >
                <Trash2 size={16} /> Remove target
              </button>
            </div>
          ))}
          <div className="form-actions">
            <button
              type="button"
              onClick={() =>
                change("partial_targets", [
                  ...draft.partial_targets,
                  [(draft.partial_targets.at(-1)?.[0] || 0) + 1, 1],
                ])
              }
            >
              <Plus size={16} /> Add partial target
            </button>
            <button className="primary" disabled={busy}>
              <Save size={16} /> Save exit policy
            </button>
          </div>
        </form>
      )}
      {tab === "Giveback review" && (
        <>
          <h2>Completed paper episodes / not broker results</h2>
          <Table
            heads={[
              "Population",
              "Closed",
              "Strategy",
              "Symbol",
              "Net",
              "MFE",
              "MAE",
              "Giveback",
              "Giveback %",
              "Max R",
              "Captured R",
              "Peak to exit",
              "Reason",
              "Diagnostics",
            ]}
            rows={view.paper_closed.map((row: Json) => {
              const a = row.management_analytics;
              return [
                row.population,
                ct(row.exit_time),
                row.strategy,
                row.symbol,
                money(row.net),
                money(a.mfe_dollars),
                money(a.mae_dollars),
                money(a.profit_giveback),
                a.giveback_percent?.toFixed(1) ?? "--",
                a.maximum_r.toFixed(2),
                a.captured_r?.toFixed(2) ?? "--",
                a.seconds_peak_to_exit + "s",
                row.reason,
                a.diagnostic_categories.join("; "),
              ];
            })}
          />
        </>
      )}
      {tab === "Policy comparison" && (
        <>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (
                await act("/trade-management/compare", {
                  datasets: [{ symbol, contract_id: contract, csv }],
                  walk_forward: folds,
                  compare: false,
                })
              )
                await load();
            }}
          >
            <div className="fields three">
              <Field label="Instrument">
                <select
                  value={symbol}
                  onChange={(e) => setSymbol(e.target.value)}
                >
                  {["MNQ", "MES", "MYM"].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
              </Field>
              <Field label="Actual historical contract">
                <input
                  required
                  value={contract}
                  onChange={(e) => setContract(e.target.value)}
                />
              </Field>
              <Field label="Finalized minute CSV">
                <input
                  type="file"
                  accept=".csv"
                  required
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (file) setCsv(await file.text());
                  }}
                />
              </Field>
            </div>
            <Toggle
              label="Chronological fixed-policy test folds"
              value={folds}
              onChange={setFolds}
            />
            <button className="primary" disabled={busy || !csv}>
              <Play size={16} /> Compare ten exit policies
            </button>
          </form>
          {view.comparisons.map((run: Json) => (
            <section key={run.id}>
              <h2>Exit comparison {run.id.slice(0, 10)}</h2>
              <Table
                heads={[
                  "Policy",
                  "Trades",
                  "Net",
                  "Win %",
                  "Profit factor",
                  "Expectancy",
                  "Drawdown",
                  "Avg MFE",
                  "Avg MAE",
                  "Avg giveback",
                  "Capture %",
                ]}
                rows={Object.entries(run.result.policies).map(
                  ([name, row]: any) => [
                    name,
                    row.summary.metrics.trades,
                    money(row.summary.metrics.net),
                    row.summary.metrics.win_rate?.toFixed(1) ?? "--",
                    row.summary.metrics.profit_factor?.toFixed(2) ?? "--",
                    money(row.summary.metrics.expectancy),
                    money(row.summary.metrics.max_drawdown),
                    money(row.diagnostics.average_mfe),
                    money(row.diagnostics.average_mae),
                    money(row.diagnostics.average_giveback),
                    row.diagnostics.average_profit_captured?.toFixed(1) ?? "--",
                  ],
                )}
              />
            </section>
          ))}
        </>
      )}
    </section>
  );
}
