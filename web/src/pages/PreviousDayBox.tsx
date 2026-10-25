import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Save } from "lucide-react";
import { api, ct, price, type Json } from "../api";
import { Badge, Field, Metric, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";
import { DynamicField } from "./Controls";
const MarketChart = lazy(() =>
  import("../Chart").then((module) => ({ default: module.MarketChart })),
);

const groups: Record<string, string[]> = {
  "Monitoring & permissions": [
    "monitor_enabled",
    "practice_enabled",
    "leader_enabled",
    "paper_enabled",
    "enabled_symbols",
    "notify_signals",
    "notify_wait",
  ],
  "Reference session & zones": [
    "session",
    "custom_open",
    "custom_close",
    "buy_percent",
    "sell_percent",
    "outside_mode",
  ],
  "Completed-candle confirmation": [
    "confirmation",
    "combined_logic",
    "wick_body_enabled",
    "wick_body_ratio",
    "wick_range_enabled",
    "wick_range_ratio",
    "directional_close",
    "close_midpoint",
    "close_location",
    "min_candle_ticks",
    "min_sweep_ticks",
    "sweep_boundary",
    "next_candle_confirmation",
    "swing_lookback",
  ],
  "Entry timing": [
    "entry_window_seconds",
    "max_data_age_seconds",
    "max_zone_extension_percent",
    "max_entry_drift_ticks",
    "cooldown_minutes",
    "max_entries_per_box",
    "time_filter_enabled",
    "entry_open",
    "entry_close",
  ],
  "Stops & targets": [
    "stop_method",
    "stop_buffer_ticks",
    "fixed_stop_ticks",
    "atr_length",
    "atr_multiple",
    "target_method",
    "reward_risk",
    "management_minutes",
    "trail_start_r",
  ],
  "Experimental filters": [
    "atr_filter_enabled",
    "atr_min_ticks",
    "atr_max_ticks",
    "volume_enabled",
    "volume_lookback",
    "volume_multiplier",
    "ema_enabled",
    "ema_length",
    "vwap_enabled",
    "min_box_enabled",
    "min_box_ticks",
    "max_box_enabled",
    "max_box_ticks",
    "previous_direction_enabled",
    "minimum_effective_rr",
    "estimated_commission_per_side",
    "zero_cost_sensitivity",
  ],
  "Forward paper costs": [
    "paper_quantity",
    "paper_commission_per_side",
    "paper_zero_cost_sensitivity",
    "paper_slippage_ticks",
    "paper_max_initial_risk_usd",
    "paper_min_effective_rr",
  ],
};

export function BoxParameters({
  config,
  act,
  busy,
}: Pick<PageProps, "config" | "act" | "busy">) {
  const [draft, setDraft] = useState<Json>(config.previous_day_box || {}),
    [dirty, setDirty] = useState(false),
    [saved, setSaved] = useState(false);
  const edited = useRef(false);
  useEffect(() => {
    if (!edited.current) setDraft(config.previous_day_box || {});
  }, [config]);
  return (
    <form
      data-section="box"
      onSubmit={async (event) => {
        event.preventDefault();
        const result = await act("/previous-day-box", draft);
        if (result) {
          edited.current = false;
          setDirty(false);
          setSaved(true);
        }
      }}
    >
      <Notice>
        Previous Day Box Reversal · Completed 15-minute candles ·
        America/Chicago · Independent account authorization
      </Notice>
      <div className="control-save-status" role="status">
        {dirty ? (
          <Badge tone="warning">Unsaved box settings</Badge>
        ) : saved ? (
          "Box settings saved. No account armed."
        ) : (
          "Saved box configuration"
        )}
      </div>
      {Object.entries(groups).map(([heading, names]) => (
        <details
          className="box-settings-group"
          key={heading}
          open={
            heading === "Monitoring & permissions" ||
            heading === "Reference session & zones"
          }
        >
          <summary>{heading}</summary>
          <div className="fields three">
            {names
              .filter((name) => name in draft)
              .map((name) =>
                name === "stop_method" ? (
                  <Field key={name} label="Box stop method">
                    <select
                      value={draft[name]}
                      onChange={(event) => {
                        edited.current = true;
                        setDirty(true);
                        setSaved(false);
                        setDraft({ ...draft, [name]: event.target.value });
                      }}
                    >
                      {[
                        "rejection",
                        "box",
                        "swing",
                        "atr",
                        "fixed",
                        "buffered",
                      ].map((value) => (
                        <option key={value}>{value}</option>
                      ))}
                    </select>
                  </Field>
                ) : (
                  <DynamicField
                    key={name}
                    name={name}
                    value={draft[name]}
                    set={(value) => {
                      edited.current = true;
                      setDirty(true);
                      setSaved(false);
                      setDraft({ ...draft, [name]: value });
                    }}
                  />
                ),
              )}
          </div>
        </details>
      ))}
      <button className="primary" disabled={busy}>
        <Save size={16} />
        Save box parameters
      </button>
    </form>
  );
}

export function PreviousDayBoxPanel() {
  const [symbol, setSymbol] = useState("NQ=F"),
    [data, setData] = useState<Json | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    const load = () =>
      api("/previous-day-box/" + encodeURIComponent(symbol))
        .then((value) => {
          if (!stopped) {
            setData(value);
            setError("");
          }
        })
        .catch((error) => {
          if (!stopped) setError(String(error));
        });
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [symbol]);
  const box = data?.box,
    signal = data?.signal;
  return (
    <section>
      <div className="filters">
        <h2>Previous Day Box Reversal</h2>
        <Field label="Box instrument">
          <select
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
          >
            {["NQ", "ES", "YM", "MNQ", "MES", "MYM"].map((value) => (
              <option key={value} value={value + "=F"}>
                {value}
              </option>
            ))}
          </select>
        </Field>
      </div>
      {error && <Notice danger>{error}</Notice>}
      <div className="context-bar">
        <Badge>{signal?.signal || "WAIT"}</Badge>
        <span>Reference: {box?.session_id || "Unavailable"}</span>
        <span>{data?.session_definition || "futures"} / America/Chicago</span>
        <span>{data?.contract_id}</span>
      </div>
      <div className="minor-metrics box-metrics">
        {[
          ["PDH", box?.pdh],
          ["PDL", box?.pdl],
          ["Midpoint", box?.midpoint],
          ["Box range", box?.range],
          ["Buy zone upper", box?.buy_upper],
          ["Sell zone lower", box?.sell_lower],
        ].map(([name, value]) => (
          <Metric
            key={name}
            label={String(name)}
            value={price(value as number)}
          />
        ))}
      </div>
      <Notice>
        {signal?.reason || "Loading contract-specific session history"}
      </Notice>
      <div className="context-bar">
        <span>Zone: {signal?.zone || "Unavailable"}</span>
        <span>Bias: {signal?.direction || "WAIT"}</span>
        <span>Confirmation: {ct(signal?.confirmed_at)}</span>
        <span>Expires: {ct(signal?.expires_at)}</span>
        <span>Trade: {ct(data?.quote_time)}</span>
        <span>
          Signal window:{" "}
          {data?.next_eligible_entry
            ? ct(data.next_eligible_entry)
            : "Awaiting confirmation"}
        </span>
        <span>Last signal opened: {ct(data?.last_entry)}</span>
        <span>Last signal closed: {ct(data?.last_exit)}</span>
      </div>
      <Suspense fallback={<Notice>Loading chart</Notice>}>
        <MarketChart
          symbol={symbol}
          minutes={15}
          hours={48}
          height={720}
          endpoint={"/previous-day-box/" + encodeURIComponent(symbol)}
        />
      </Suspense>
      <h2 className="spaced">Confirmed box events</h2>
      <Table
        heads={[
          "Detected (CT)",
          "Direction",
          "Method",
          "Entry",
          "Stop",
          "Target",
          "Reference session",
        ]}
        rows={(data?.events || []).map((event: Json) => [
          ct(event.detected_at),
          event.direction,
          event.confirmation_method,
          price(event.entry),
          price(event.initial_stop),
          price(event.target),
          event.session_id,
        ])}
      />
    </section>
  );
}
