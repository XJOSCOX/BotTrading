import { useEffect, useState } from "react";
import { RefreshCw, FlaskConical, ExternalLink } from "lucide-react";
import { api, ct, money, type Json } from "../api";
import { Field, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";

export function Research({ config, act, busy }: PageProps) {
  const [runs, setRuns] = useState<Json[]>([]),
    [paper, setPaper] = useState<Json>({}),
    [selectedRun, setSelectedRun] = useState(""),
    [csv, setCsv] = useState(""),
    [symbol, setSymbol] = useState("MNQ"),
    [contract, setContract] = useState(""),
    [strategy, setStrategy] = useState("VWAP EMA Cross"),
    [fee, setFee] = useState(""),
    [zero, setZero] = useState(false),
    [slip, setSlip] = useState(1),
    [qty, setQty] = useState(1),
    [walk, setWalk] = useState(false);
  const load = () =>
    api("/research").then((r) => {
      setRuns(r.runs);
      setPaper(r.paper_summary || {});
    });
  useEffect(() => {
    void load();
  }, []);
  return (
    <>
      <Notice>
        Historical simulations and broker P&L are separate. No profitability is
        inferred from synthetic or missing data.
      </Notice>
      <div className="form-layout">
        <form
          className="editor"
          onSubmit={async (e) => {
            e.preventDefault();
            const r = await act("/research", {
              symbol,
              contract_id: contract,
              strategy,
              csv,
              commission: fee === "" && zero ? 0 : +fee,
              zero_cost_sensitivity: zero,
              slippage: slip,
              quantity: qty,
              walk_forward: walk,
            });
            if (r) void load();
          }}
        >
          <h2>Historical backtest</h2>
          <div className="fields two">
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
            <Field label="Strategy">
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
              >
                {config.strategies.map((s: Json) => (
                  <option key={s.id}>{s.name}</option>
                ))}
              </select>
            </Field>
          </div>
          <Field label="Actual contract ID">
            <input
              required
              value={contract}
              onChange={(e) => setContract(e.target.value)}
            />
          </Field>
          <Toggle
            label="Walk-forward validation"
            value={walk}
            onChange={setWalk}
          />
          <Field label="Actual minute OHLCV CSV">
            <input
              type="file"
              accept=".csv,text/csv"
              required
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f && f.size <= 1500000) setCsv(await f.text());
                else setCsv("");
              }}
            />
          </Field>
          <div className="fields three">
            <Field label="Commission / contract / side ($)">
              <input
                required={!zero}
                type="number"
                min="0"
                step="0.01"
                value={fee}
                onChange={(e) => setFee(e.target.value)}
              />
            </Field>
            <Field label="Adverse slippage / fill (ticks)">
              <input
                type="number"
                min="0"
                max="100"
                value={slip}
                onChange={(e) => setSlip(+e.target.value)}
              />
            </Field>
            <Field label="Contracts">
              <input
                type="number"
                min="1"
                max="4"
                value={qty}
                onChange={(e) => setQty(+e.target.value)}
              />
            </Field>
          </div>
          <Toggle
            label="Explicit zero-cost sensitivity scenario"
            value={zero}
            onChange={setZero}
          />
          <button
            className="primary"
            disabled={busy || !csv || (!fee && !zero)}
          >
            <FlaskConical size={16} />
            Run simulated backtest
          </button>
        </form>
        <aside className="policy-aside">
          <h2>Dataset requirements</h2>
          <p className="muted">
            Timezone-aware time, open, high, low, close and actual traded
            volume. Single contract only. No reconstructed intrabar entries.
          </p>
          <p className="muted">
            Strategy parameters come from Control Center. Realtime and
            anticipatory modes require tick data and are not supported by this
            minute-CSV form.
          </p>
          <a
            href="http://127.0.0.1:8502/?page=Bot"
            target="_blank"
            rel="noreferrer"
            className="text-link"
          >
            <ExternalLink size={14} />
            Advanced research in legacy workspace
          </a>
        </aside>
      </div>
      <div className="section-heading">
        <h2>Saved simulated results</h2>
        <button onClick={() => void load()}>
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>
      <Table
        heads={[
          "Saved / CT",
          "Strategy",
          "Period",
          "Trades",
          "Net",
          "Profit factor",
          "Commission / side",
          "Slippage",
        ]}
        rows={runs.map((r) => [
          ct(r.created_at),
          r.result.strategy,
          ct(r.result.start) + " to " + ct(r.result.end),
          r.result.summary.trades,
          money(r.result.summary.net),
          r.result.summary.profit_factor?.toFixed(2) ?? "--",
          money(r.result.simulation.commission_per_side),
          r.result.simulation.slippage_ticks + " ticks",
        ])}
      />
      {runs.length > 0 && (
        <section className="spaced">
          <Field label="Research run details">
            <select
              value={selectedRun}
              onChange={(event) => setSelectedRun(event.target.value)}
            >
              <option value="">Select a saved run</option>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  #{run.id} · {run.result.strategy} · {ct(run.created_at)}
                </option>
              ))}
            </select>
          </Field>
          {runs
            .filter((run) => String(run.id) === selectedRun)
            .map((run) => (
              <div key={run.id}>
                <Table
                  heads={["Metric", "Value"]}
                  rows={Object.entries(run.result.summary).map(
                    ([key, value]) => [
                      key.replaceAll("_", " "),
                      typeof value === "number"
                        ? value.toLocaleString(undefined, {
                            maximumFractionDigits: 3,
                          })
                        : "--",
                    ],
                  )}
                />
                <h3 className="spaced">
                  Direction / session / monthly performance
                </h3>
                <Table
                  heads={[
                    "Grouping",
                    "Segment",
                    "Trades",
                    "Win rate",
                    "Net",
                    "Profit factor",
                  ]}
                  rows={Object.entries(run.result.breakdown).flatMap(
                    ([group, values]) =>
                      Object.entries(values as Json).map(([segment, value]) => [
                        group,
                        segment,
                        value.trades,
                        value.win_rate == null
                          ? "--"
                          : value.win_rate.toFixed(1) + "%",
                        money(value.net),
                        value.profit_factor?.toFixed(2) ?? "--",
                      ]),
                  )}
                />
                <h3 className="spaced">Monthly returns</h3>
                <Table
                  heads={[
                    "Month",
                    "Starting balance",
                    "Ending balance",
                    "Net",
                    "Closed return (%)",
                  ]}
                  rows={Object.entries(run.result.monthly_returns || {}).map(
                    ([month, value]: [string, any]) => [
                      month,
                      money(value.starting_balance),
                      money(value.ending_balance),
                      money(value.net),
                      value.closed_trade_return_percent?.toFixed(2) ?? "--",
                    ],
                  )}
                />
                <h3 className="spaced">Entry decisions / data sufficiency</h3>
                <Table
                  heads={["Reason", "Count"]}
                  rows={Object.entries(run.result.decisions || {})}
                />
                {run.result.walk_forward && (
                  <>
                    <h3 className="spaced">Walk-forward validation</h3>
                    <Table
                      heads={[
                        "Fold",
                        "Split (CT)",
                        "Train trades",
                        "Test trades",
                        "Test net",
                      ]}
                      rows={run.result.walk_forward.map((fold: Json) => [
                        fold.fold,
                        ct(fold.split_at),
                        fold.in_sample.summary.trades,
                        fold.out_of_sample.summary.trades,
                        money(fold.out_of_sample.summary.net),
                      ])}
                    />
                  </>
                )}
              </div>
            ))}
        </section>
      )}
      <section className="spaced">
        <h2>Forward paper / simulated fills only</h2>
        <Table
          heads={[
            "Strategy",
            "Trades",
            "Wins",
            "Losses",
            "Net",
            "Profit factor",
            "Commission",
          ]}
          rows={Object.entries(paper).map(([name, value]) => [
            name,
            value.trades,
            value.wins,
            value.losses,
            money(value.net),
            value.profit_factor?.toFixed(2) ?? "--",
            money(value.commissions),
          ])}
        />
      </section>
    </>
  );
}
