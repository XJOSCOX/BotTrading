import { useEffect, useRef, useState, type FormEvent } from "react";
import { Save } from "lucide-react";
import { type Json } from "../api";
import { Badge, Field, Metric, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";
import { Tabs } from "./Tabs";
import { BoxParameters } from "./PreviousDayBox";

export function Controls({ config, live, profile, act, busy }: PageProps) {
  const [tab, setTab] = useState("Entry policy"),
    [draft, setDraft] = useState<Json>({}),
    [interval, setInterval] = useState<Json>({}),
    [vwap, setVwap] = useState<Json>({}),
    [dirty, setDirty] = useState({
      policy: false,
      intervals: false,
      vwap: false,
    }),
    [feedback, setFeedback] = useState("");
  const loadedProfile = useRef("");
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;
  useEffect(() => {
    const changedProfile = loadedProfile.current !== profile;
    loadedProfile.current = profile;
    const settings = config.execution_settings?.[profile] || {};
    if (changedProfile || !dirtyRef.current.policy)
      setDraft({
        ...config.policies[profile],
        quantities: {
          MNQ: 2,
          MES: 2,
          MYM: 2,
          ...settings.quantities,
        },
        enable_mym: !!settings.enable_mym,
      });
    if (changedProfile || !dirtyRef.current.intervals)
      setInterval({
        stop_minutes: config.stop_minutes,
        orb_minutes: config.orb_minutes,
      });
    if (changedProfile || !dirtyRef.current.vwap) setVwap(config.vwap);
    if (changedProfile) {
      setDirty({ policy: false, intervals: false, vwap: false });
      setFeedback("");
    }
  }, [config, profile]);
  const specs: Json[] = config.strategies,
    eligible = specs.filter((s) => s.execution_profiles.includes(profile));
  const save = async (e: FormEvent) => {
    e.preventDefault();
    const result = await act("/policy/" + profile, {
      strategies: draft.strategies,
      quantities: draft.quantities,
      cooldown: Number(draft.cooldown_minutes),
      enable_mym: draft.enable_mym,
    });
    if (result) {
      setDirty((previous) => ({ ...previous, policy: false }));
      setFeedback("Entry policy saved. Run/Pause state unchanged.");
    }
  };
  return (
    <section
      className="control-center"
      inert={busy}
      onChangeCapture={(event) => {
        const form = (event.target as HTMLElement).closest("form")?.dataset
          .section;
        if (form === "policy" || form === "intervals" || form === "vwap") {
          setDirty((previous) => ({ ...previous, [form]: true }));
          setFeedback("");
        }
      }}
    >
      <Tabs
        values={[
          "Entry policy",
          "Intervals & sessions",
          "VWAP EMA parameters",
          "Previous Day Box",
        ]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Previous Day Box" && (
        <BoxParameters config={config} act={act} busy={busy} />
      )}
      <div className="control-save-status" role="status" aria-live="polite">
        {Object.values(dirty).some(Boolean) && (
          <Badge tone="warning">Unsaved changes</Badge>
        )}
        <span>
          {feedback ||
            (!Object.values(dirty).some(Boolean) ? "Saved configuration" : "")}
        </span>
      </div>
      {config.restart_required && (
        <Notice danger>
          Account changed. Restart the interface and workers before editing
          policy.
        </Notice>
      )}
      {tab === "Entry policy" && (
        <div className="form-layout">
          <form className="editor" data-section="policy" onSubmit={save}>
            <h2>Entry configuration</h2>
            <div className="strategy-list">
              {eligible.map((s) => (
                <label className="strategy-check" key={s.id}>
                  <input
                    type="checkbox"
                    aria-label={s.name}
                    disabled={busy}
                    checked={draft.strategies?.includes(s.name) || false}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        strategies: e.target.checked
                          ? [...draft.strategies, s.name]
                          : draft.strategies.filter(
                              (n: string) => n !== s.name,
                            ),
                      })
                    }
                  />
                  <span>
                    <b>{s.name}</b>
                    <small>
                      {s.signal_minutes} min signal ·{" "}
                      {s.entry_policy === "indicator-event-v1"
                        ? "Indicator cross"
                        : s.entry_policy === "previous-box-v1"
                          ? "Previous completed session box"
                          : "Multi-timeframe confirmation"}
                    </small>
                  </span>
                  <Badge>
                    {s.execution_profiles.length === 1
                      ? "Practice opt-in"
                      : "Strategy"}
                  </Badge>
                </label>
              ))}
            </div>
            <Toggle
              label="Allow MYM entries"
              value={!!draft.enable_mym}
              onChange={(v) => setDraft({ ...draft, enable_mym: v })}
              disabled={busy}
            />
            <div className="fields three">
              {["MNQ", "MES", "MYM"].map((s) => (
                <Field key={s} label={s + " contracts"}>
                  <input
                    type="number"
                    min="1"
                    max="4"
                    required
                    disabled={busy}
                    value={draft.quantities?.[s] ?? 2}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        quantities: {
                          ...draft.quantities,
                          [s]: +e.target.value,
                        },
                      })
                    }
                  />
                </Field>
              ))}
            </div>
            <Field label="Re-enter after a confirmed close (minutes)">
              <input
                type="number"
                min="1"
                max="60"
                required
                disabled={busy}
                value={draft.cooldown_minutes ?? 5}
                onChange={(e) =>
                  setDraft({ ...draft, cooldown_minutes: +e.target.value })
                }
              />
            </Field>
            <button
              className="primary"
              disabled={busy || config.restart_required}
            >
              <Save size={16} />
              Save entry policy
            </button>
          </form>
          <aside className="policy-aside">
            <h2>Execution safeguards</h2>
            <Metric label="Account loss lock" value="$500" />
            <Metric label="Maximum per symbol" value="4 micro contracts" />
            <div className="detail-row">
              <span>Additional symbols</span>
              <b>1 contract</b>
            </div>
            <div className="detail-row">
              <span>Overnight minimum delay</span>
              <b>15 minutes</b>
            </div>
            <p className="muted">
              Strategy-based stops. Open positions keep their original
              management configuration.
            </p>
            <Notice>
              VWAP EMA Cross is prohibited on Leader. Practice also requires
              permission, complete data and a reviewed calendar.
            </Notice>
          </aside>
        </div>
      )}
      {tab === "Intervals & sessions" && (
        <>
          <div className="form-layout">
            <form
              className="editor"
              data-section="intervals"
              onSubmit={async (e) => {
                e.preventDefault();
                const result = await act("/intervals", interval);
                if (result) {
                  setDirty((previous) => ({ ...previous, intervals: false }));
                  setFeedback("Intervals saved for new setups.");
                }
              }}
            >
              <h2>Candle intervals</h2>
              <Field label="Legacy strategy signal candles">
                <select disabled>
                  <option>15 minutes</option>
                </select>
              </Field>
              <div className="fields two">
                <Field label="Opening range">
                  <select
                    value={interval.orb_minutes}
                    onChange={(e) =>
                      setInterval({ ...interval, orb_minutes: +e.target.value })
                    }
                  >
                    {[5, 15, 30].map((n) => (
                      <option key={n} value={n}>
                        {n} min
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Stop & trailing candles">
                  <select
                    value={interval.stop_minutes}
                    onChange={(e) =>
                      setInterval({
                        ...interval,
                        stop_minutes: +e.target.value,
                      })
                    }
                  >
                    {[5, 10, 15].map((n) => (
                      <option key={n} value={n}>
                        {n} min
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <button className="primary" disabled={busy}>
                <Save size={16} />
                Save intervals
              </button>
            </form>
            <aside className="policy-aside">
              <h2>Session boundaries / CT</h2>
              {[
                ["Entry cutoff", "14:50"],
                ["Flatten request", "15:05"],
                ["Trading reopens", "17:00"],
              ].map(([name, time]) => (
                <div key={name} className="detail-row">
                  <span>{name}</span>
                  <b>{time}</b>
                </div>
              ))}
              <p className="muted">
                Exchange holidays, maintenance, volatility and stale data may
                restrict entries further.
              </p>
            </aside>
          </div>
          <Table
            heads={["Strategy", "Signal interval", "Leader"]}
            rows={specs.map((s) => [
              s.name,
              s.id === "vwap_ema_cross"
                ? `${config.vwap.signal_minutes} min`
                : `${s.signal_minutes} min`,
              s.execution_profiles.includes("leader")
                ? "Eligible"
                : "Prohibited",
            ])}
          />
        </>
      )}
      {tab === "VWAP EMA parameters" && (
        <form
          data-section="vwap"
          onSubmit={async (e) => {
            e.preventDefault();
            const result = await act("/vwap", vwap);
            if (result) {
              setDirty((previous) => ({ ...previous, vwap: false }));
              setFeedback("VWAP parameters saved. No account armed.");
            }
          }}
        >
          <Notice>{config.calendar.reason}</Notice>
          <div className="fields three">
            {Object.entries(vwap).map(([name, value]) => (
              <DynamicField
                key={name}
                name={name}
                value={value}
                set={(v) => setVwap({ ...vwap, [name]: v })}
              />
            ))}
          </div>
          <button className="primary" disabled={busy}>
            <Save size={16} />
            Save VWAP parameters
          </button>
        </form>
      )}
    </section>
  );
}

export function DynamicField({
  name,
  value,
  set,
}: {
  name: string;
  value: any;
  set: (value: any) => void;
}) {
  const choices: Record<string, (string | number)[]> = {
    entry_mode: ["CONFIRMED", "REALTIME", "ANTICIPATORY"],
    signal_minutes: [1, 3, 5, 10, 15, 30, 60],
    management_minutes: [1, 3, 5, 10, 15, 30],
    ema_source: ["close", "open", "high", "low", "hlc3", "ohlc4"],
    vwap_source: ["close", "open", "high", "low", "hlc3", "ohlc4"],
    anchor: ["futures", "rth", "custom"],
    stop_method: ["atr", "swing", "fixed", "buffered"],
    management_method: ["fixed", "trailing", "breakeven", "adaptive"],
    session: ["futures", "rth", "custom"],
    confirmation: ["wick", "sweep", "structure", "combined"],
    combined_logic: ["AND", "OR"],
    outside_mode: ["ignore", "reclaim", "breakout_research"],
    sweep_boundary: ["extreme", "zone"],
    target_method: [
      "midpoint",
      "opposite_zone",
      "opposite_boundary",
      "rr",
      "adaptive",
    ],
  };
  const label = name.replaceAll("_", " ");
  if (typeof value === "boolean")
    return <Toggle label={label} value={value} onChange={set} />;
  return (
    <Field label={label}>
      {choices[name] ? (
        <select
          value={value}
          onChange={(e) =>
            set(typeof value === "number" ? +e.target.value : e.target.value)
          }
        >
          {choices[name].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      ) : Array.isArray(value) ? (
        <input
          value={value.join(", ")}
          onChange={(e) =>
            set(
              e.target.value
                .split(",")
                .map((v) => v.trim())
                .filter(Boolean),
            )
          }
        />
      ) : (
        <input
          type={typeof value === "number" ? "number" : "text"}
          min={typeof value === "number" ? 0 : undefined}
          step="any"
          value={value}
          onChange={(e) =>
            set(typeof value === "number" ? +e.target.value : e.target.value)
          }
        />
      )}
    </Field>
  );
}
