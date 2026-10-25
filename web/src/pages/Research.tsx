import { useEffect, useState } from "react";
import { RefreshCw, FlaskConical, ExternalLink } from "lucide-react";
import { api, ct, money, type Json } from "../api";
import { Field, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";

export function Research({ config, act, busy }: PageProps) {
  const [runs, setRuns] = useState<Json[]>([]),
    [csv, setCsv] = useState(""),
    [symbol, setSymbol] = useState("MNQ"),
    [contract, setContract] = useState(""),
    [strategy, setStrategy] = useState("VWAP EMA Cross"),
    [fee, setFee] = useState(""),
    [zero, setZero] = useState(false),
    [slip, setSlip] = useState(1),
    [qty, setQty] = useState(1);
  const load = () => api("/research").then((r) => setRuns(r.runs));
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
            VWAP parameters come from Control Center. Realtime and anticipatory
            modes require tick data and are not supported by this minute-CSV
            form.
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
    </>
  );
}
