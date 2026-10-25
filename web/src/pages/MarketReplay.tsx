import { memo, useEffect, useState } from "react";
import {
  Play,
  Pause,
  Square,
  StepForward,
  RotateCcw,
  Plus,
  Download,
  FlaskConical,
} from "lucide-react";
import { api, money, price, ct, type Json } from "../api";
import { Field, Metric, Notice, Table, Toggle, Badge } from "../components";
import { Tabs } from "./Tabs";
import { ReplayChart } from "./ReplayChart";
import type { PageProps } from "../pageTypes";

function MarketReplayPage(_: PageProps) {
  const [overview, setOverview] = useState<Json>({
      datasets: [],
      sessions: [],
      strategies: [],
    }),
    [session, setSession] = useState<Json | null>(null),
    [bars, setBars] = useState<Json[]>([]),
    [box, setBox] = useState<Json | null>(null),
    [symbol, setSymbol] = useState(""),
    [tab, setTab] = useState("Replay"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<string[]>([]),
    [strategies, setStrategies] = useState<string[]>(["crt", "reversal"]),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [balance, setBalance] = useState(50000),
    [fee, setFee] = useState(0.5),
    [slip, setSlip] = useState(1),
    [risk, setRisk] = useState(75),
    [portfolio, setPortfolio] = useState(150),
    [daily, setDaily] = useState(500),
    [positions, setPositions] = useState(1),
    [quantity, setQuantity] = useState(1),
    [mode, setMode] = useState("conservative"),
    [exit, setExit] = useState("baseline"),
    [tickId, setTickId] = useState(""),
    [configs, setConfigs] = useState("{}"),
    [advanced, setAdvanced] = useState("{}");
  const load = async () => setOverview(await api("/replay"));
  useEffect(() => {
    void load().catch((e) => setError(String(e)));
  }, []);
  useEffect(() => {
    if (!session) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const refresh = async () => {
      try {
        const next = await api("/replay/" + session.id);
        if (!stopped)
          setSession((old) => (old?.revision === next.revision ? old : next));
      } catch (e) {
        if (!stopped) setError(String(e));
      }
      if (!stopped) timer = setTimeout(refresh, 500);
    };
    timer = setTimeout(refresh, 500);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [session?.id]);
  useEffect(() => {
    if (!session || !symbol) return;
    let stopped = false;
    void api(`/replay/${session.id}/chart?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => {
        if (!stopped) {
          setBars(r.bars);
          setBox(r.box || null);
        }
      })
      .catch((e) => {
        if (!stopped) setError(String(e));
      });
    return () => {
      stopped = true;
    };
  }, [session?.id, session?.next_index, symbol]);
  const perform = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };
  const open = (r: Json) => {
    setSession(r);
    const meta = overview.datasets.find((d: Json) =>
      r.request.datasets.includes(d.id),
    );
    setSymbol(meta?.symbol || "");
    setBars([]);
    setBox(null);
    setTab("Replay");
  };
  const control = (action: string, values: Json = {}) =>
    void perform(async () => {
      const r = await api(`/replay/${session?.id}/control`, {
        action,
        ...values,
      });
      if (r.id === session?.id) setSession(r);
      else {
        open(r);
        await load();
      }
    });
  const create = () =>
    void perform(async () => {
      const custom = JSON.parse(advanced);
      open(
        await api("/replay", {
          datasets: selected,
          strategies,
          start,
          end,
          initial_balance: balance,
          configurations: JSON.parse(configs),
          ...(tickId ? { ticks: tickId } : {}),
          execution: {
            commission_per_side: fee,
            zero_cost_acknowledged: fee === 0,
            slippage_ticks: slip,
            max_trade_risk: risk,
            max_open_risk: portfolio,
            max_group_risk: portfolio,
            max_daily_loss: daily,
            max_daily_loss_with_open: daily,
            max_positions: positions,
            max_group_positions: positions,
            requested_quantity: quantity,
            max_contracts: quantity,
            mode,
          },
          exit_policy: {
            enabled: true,
            mode: exit,
            ...(exit === "partial" || exit === "hybrid"
              ? { partial_targets: [[1, 1]] }
              : {}),
            ...custom,
          },
        }),
      );
      await load();
    });
  const a = session?.virtual_account;
  return (
    <>
      <div className="section-heading">
        <Badge>OFFLINE / SIMULATED</Badge>
        <button onClick={() => setTab("Configuration")}>
          <Plus size={16} />
          New replay
        </button>
      </div>
      {error && <Notice danger>{error}</Notice>}
      <Tabs
        values={["Replay", "Configuration", "Saved sessions", "Recorded ticks"]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Configuration" && (
        <section className="replay-config">
          <div>
            <h2>Historical source</h2>
            {!overview.datasets.length && (
              <Notice>
                No historical datasets. Import genuine minute OHLCV or retrieve
                contract history in Strategy Validation Lab.
              </Notice>
            )}
            {overview.datasets.map((d: Json) => (
              <Toggle
                key={d.id}
                label={`${d.symbol} / ${d.contract_id} / ${d.quality.status}`}
                value={selected.includes(d.id)}
                onChange={(on) => {
                  setSelected((old) =>
                    on ? [...old, d.id] : old.filter((k) => k !== d.id),
                  );
                  if (on) {
                    setStart(d.start);
                    setEnd(d.end);
                  }
                }}
              />
            ))}
            <div className="form-grid">
              <Field label="Start / UTC">
                <input
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                />
              </Field>
              <Field label="End exclusive / UTC">
                <input value={end} onChange={(e) => setEnd(e.target.value)} />
              </Field>
            </div>
            <h2>Strategies</h2>
            <div className="replay-strategies">
              {overview.strategies.map((s: Json) => (
                <Toggle
                  key={s.id}
                  label={`${s.name} / ${s.minutes}m`}
                  value={strategies.includes(s.id)}
                  onChange={(on) =>
                    setStrategies((old) =>
                      on ? [...old, s.id] : old.filter((k) => k !== s.id),
                    )
                  }
                />
              ))}
            </div>
            <Field label="Frozen strategy configuration / JSON">
              <textarea
                value={configs}
                onChange={(e) => setConfigs(e.target.value)}
                rows={5}
              />
            </Field>
            <Field label="Recorded tick snapshot / optional">
              <input
                value={tickId}
                onChange={(e) => setTickId(e.target.value)}
              />
            </Field>
          </div>
          <div>
            <h2>Virtual account</h2>
            <div className="form-grid">
              {[
                ["Starting simulated balance", balance, setBalance],
                ["Risk / trade", risk, setRisk],
                ["Portfolio risk", portfolio, setPortfolio],
                ["Maximum daily loss", daily, setDaily],
                ["Maximum positions", positions, setPositions],
                ["Contracts / entry", quantity, setQuantity],
                ["Commission / contract / side", fee, setFee],
                ["Adverse slippage / ticks", slip, setSlip],
              ].map(([label, value, setter]: any) => (
                <Field key={label} label={label}>
                  <input
                    type="number"
                    value={value}
                    min={0}
                    step={label.includes("Commission") ? 0.01 : 1}
                    onChange={(e) => setter(Number(e.target.value))}
                  />
                </Field>
              ))}
              <Field label="Arbitration">
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  {[
                    "conservative",
                    "first_confirmed",
                    "configured_priority",
                  ].map((m) => (
                    <option key={m}>{m}</option>
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
                  ].map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="Exit-policy overrides / JSON">
              <textarea
                value={advanced}
                rows={5}
                onChange={(e) => setAdvanced(e.target.value)}
              />
            </Field>
            <button
              disabled={busy || !selected.length || !strategies.length}
              onClick={create}
            >
              <Plus size={16} />
              Create simulated session
            </button>
          </div>
        </section>
      )}
      {tab === "Saved sessions" && (
        <Table
          heads={["Session", "State", "Cursor time", "Action"]}
          rows={overview.sessions.map((r: Json) => [
            r.id.slice(-10),
            r.status,
            ct(r.clock),
            <button
              onClick={() =>
                void perform(async () => open(await api("/replay/" + r.id)))
              }
            >
              <Play size={15} />
              Inspect session
            </button>,
          ])}
        />
      )}
      {tab === "Recorded ticks" && (
        <>
          <Notice>
            Actual ordered trade CSV: sequence, time, price, volume,
            contract_id. Must reconcile to the complete declared minute dataset.
            No OHLC-generated ticks.
          </Notice>
          <Field label="Tick source dataset">
            <select
              value={selected[0] || ""}
              onChange={(e) => setSelected([e.target.value])}
            >
              <option value="">Select dataset</option>
              {overview.datasets.map((d: Json) => (
                <option key={d.id} value={d.id}>
                  {d.symbol} / {d.contract_id}
                </option>
              ))}
            </select>
          </Field>
          <TickImport dataset={selected[0]} saved={setTickId} />
        </>
      )}
      {tab === "Replay" &&
        (!session ? (
          <Notice>
            Select a saved session or create an offline replay from genuine
            historical data. ProjectX is not required for saved data.
          </Notice>
        ) : (
          <>
            <div className="replay-toolbar">
              <Badge>{session.status.toUpperCase()}</Badge>
              <strong>{ct(session.clock)}</strong>
              <span>
                {session.next_index} / {session.total_steps ?? "--"}{" "}
                {session.ticks ? "actual trades" : "minutes"}
              </span>
              {[
                ["Play", "play", Play],
                ["Pause", "pause", Pause],
                ["Step event", "step", StepForward],
                ["Step candle", "candle", StepForward],
                ["Stop", "stop", Square],
                ["Restart", "restart", RotateCcw],
              ].map(([label, action, Icon]: any) => (
                <button
                  key={action}
                  title={label}
                  aria-label={label}
                  disabled={busy}
                  onClick={() => control(action)}
                >
                  <Icon size={17} />
                </button>
              ))}
              <Field label="Replay speed">
                <select
                  value={session.speed}
                  onChange={(e) =>
                    control("speed", {
                      speed:
                        e.target.value === "maximum"
                          ? "maximum"
                          : Number(e.target.value),
                    })
                  }
                >
                  {[1, 5, 10, 30, 60, "maximum"].map((s) => (
                    <option value={s} key={s}>
                      {s === "maximum" ? "Maximum" : s + "x"}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Replay instrument">
                <select
                  value={symbol}
                  onChange={(e) => {
                    setSymbol(e.target.value);
                    setBars([]);
                  }}
                >
                  {overview.datasets
                    .filter((d: Json) =>
                      session.request.datasets.includes(d.id),
                    )
                    .map((d: Json) => (
                      <option key={d.id} value={d.symbol}>
                        {d.symbol} / {d.contract_id}
                      </option>
                    ))}
                </select>
              </Field>
              <a
                className="button"
                href={`/api/replay/${session.id}/export`}
                download="offline-replay.json"
              >
                <Download size={16} />
                Export
              </a>
            </div>
            {session.status === "playing" && !session.player_alive && (
              <Notice>
                Playback process is no longer active. Resume explicitly; the
                saved cursor prevents duplicate fills.
              </Notice>
            )}
            {session.error && <Notice danger>{session.error}</Notice>}
            <div className="replay-metrics">
              <Metric label="Simulated balance" value={money(a.balance)} />
              <Metric label="Marked equity" value={money(a.equity)} />
              <Metric label="Realized" value={money(a.realized)} />
              <Metric label="Unrealized" value={money(a.unrealized)} />
              <Metric label="Planned risk" value={money(a.planned_open_risk)} />
              <Metric label="Available risk" value={money(a.available_risk)} />
              <Metric label="Daily drawdown" value={money(a.daily_drawdown)} />
              <Metric label="Consecutive losses" value={a.consecutive_losses} />
            </div>
            <ReplayChart
              bars={bars}
              session={{
                ...session,
                box,
                symbol,
                trades: session.trades.filter((t: Json) => t.symbol === symbol),
                positions: session.positions.filter(
                  (p: Json) => p.exposure.symbol === symbol,
                ),
              }}
            />
            <section>
              <h2>Trade management</h2>
              <Table
                heads={[
                  "Instrument",
                  "Owner",
                  "Qty",
                  "Entry",
                  "Stop",
                  "Target",
                  "Current R / Max R",
                  "Protection / latest decision",
                ]}
                rows={session.positions.map((p: Json) => [
                  p.exposure.symbol,
                  p.candidate.strategy_name,
                  p.exposure.quantity,
                  price(p.exposure.entry),
                  price(p.exposure.stop),
                  price(p.trade_management?.target ?? p.candidate.target),
                  `${p.trade_management?.current_r?.toFixed(2) ?? "--"} / ${p.trade_management?.max_r?.toFixed(2) ?? "--"}`,
                  <>
                    <span>
                      {p.trade_management?.decisions?.at(-1)?.reason ||
                        p.pending_exit ||
                        "Holding / no exit condition triggered"}
                    </span>
                    <details>
                      <summary>Management evidence</summary>
                      <pre>
                        {JSON.stringify(p.hold_evidence || {}, null, 2)}
                      </pre>
                      <pre>{JSON.stringify(p.analytics || {}, null, 2)}</pre>
                    </details>
                  </>,
                ])}
              />
            </section>
            <section>
              <h2>Strategy activity</h2>
              <Table
                heads={[
                  "Strategy",
                  "Instrument",
                  "Timeframe",
                  "Confirmed at",
                  "Eligibility",
                  "Confirmed",
                  "Decision reason",
                ]}
                rows={session.decisions
                  .slice(-20)
                  .reverse()
                  .map((d: Json) => [
                    d.strategy_id,
                    session.candidates.find(
                      (c: Json) => c.candidate_id === d.candidate_id,
                    )?.symbol,
                    `${overview.strategies.find((s: Json) => s.id === d.strategy_id)?.minutes ?? "--"}m`,
                    ct(
                      session.candidates.find(
                        (c: Json) => c.candidate_id === d.candidate_id,
                      )?.confirmed_at,
                    ),
                    d.eligibility,
                    d.selected ? "Selected" : "Rejected",
                    d.reasons?.join(" / "),
                  ])}
              />
              {!!session.waits.length && (
                <Table
                  heads={["Strategy", "Instrument", "Latest evaluation"]}
                  rows={session.waits
                    .slice(-7)
                    .map((w: Json) => [w.strategy_id, w.symbol, w.reason])}
                />
              )}
            </section>
            <section>
              <div className="section-heading">
                <h2>Simulated trades</h2>
                <button
                  disabled={busy || !session.trades.length || !!session.ticks}
                  onClick={() =>
                    void perform(async () => {
                      const r = { ...session.request };
                      delete r.code;
                      await api("/validation-lab/run", {
                        ...r,
                        compare_exits: true,
                      });
                      setError(
                        "Exit comparison queued in Strategy Validation Lab; results are simulated, not assumed improvements.",
                      );
                    })
                  }
                >
                  <FlaskConical size={16} />
                  Compare exit policies
                </button>
              </div>
              <Table
                heads={[
                  "Strategy",
                  "Side",
                  "Entry / exit",
                  "Net",
                  "Exit reason",
                  "Management analytics",
                ]}
                rows={session.trades
                  .slice()
                  .reverse()
                  .map((t: Json) => [
                    t.strategy,
                    t.direction,
                    `${price(t.entry)} / ${price(t.exit)}`,
                    money(t.net),
                    t.reason,
                    <details>
                      <summary>Inspect profit protection</summary>
                      <pre>
                        {JSON.stringify(t.management_analytics || t, null, 2)}
                      </pre>
                      <pre>
                        {JSON.stringify(
                          {
                            fills: t.partial_fills || [],
                            decisions: t.management_decisions || [],
                            target_touched: t.target_touched,
                            baseline: t.final_baseline,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    </details>,
                  ])}
              />
            </section>
            <section>
              <h2>Replay events</h2>
              <Table
                heads={["Historical time", "Event", "Evidence"]}
                rows={session.events
                  .slice()
                  .reverse()
                  .map((e: Json) => [
                    ct(e.time),
                    e.type,
                    <details>
                      <summary>Evidence</summary>
                      <pre>{JSON.stringify(e.detail || {}, null, 2)}</pre>
                    </details>,
                  ])}
              />
            </section>
          </>
        ))}
    </>
  );
}
function TickImport({
  dataset,
  saved,
}: {
  dataset: string;
  saved: (id: string) => void;
}) {
  const [source, setSource] = useState(""),
    [complete, setComplete] = useState(false),
    [message, setMessage] = useState("");
  return (
    <>
      <Field label="Recording source">
        <input value={source} onChange={(e) => setSource(e.target.value)} />
      </Field>
      <Toggle
        label="Complete actual recorded trade sequence"
        value={complete}
        onChange={setComplete}
      />
      <button
        disabled={!dataset || !complete}
        onClick={() =>
          void api("/replay/ticks/saved", {
            dataset,
            complete_recording: complete,
          })
            .then((r) => {
              saved(r.id);
              setMessage(
                `Saved ${r.event_count} captured actual trades / ${r.id}`,
              );
            })
            .catch((e) => setMessage(String(e)))
        }
      >
        <Download size={16} />
        Import captured trade ticks
      </button>
      <Field label="Actual recorded trade CSV">
        <input
          type="file"
          accept=".csv"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            if (file.size > 1500000) {
              setMessage("CSV exceeds 1.5 MB");
              return;
            }
            void file
              .text()
              .then((csv) =>
                api("/replay/ticks", {
                  dataset,
                  source,
                  complete_recording: complete,
                  csv,
                }),
              )
              .then((r) => {
                saved(r.id);
                setMessage(`Saved ${r.event_count} actual trades / ${r.id}`);
              })
              .catch((e) => setMessage(String(e)));
          }}
        />
      </Field>
      {message && <Notice>{message}</Notice>}
    </>
  );
}
export const MarketReplay = memo(MarketReplayPage, () => true);
