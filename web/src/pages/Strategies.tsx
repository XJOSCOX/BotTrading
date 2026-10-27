import { useState } from "react";
import { ShieldAlert, Trash2 } from "lucide-react";
import { age, ct, price, type Json } from "../api";
import { Badge, Empty, Table } from "../components";
import { type PageProps, symbols, tone } from "../pageTypes";
import { Tabs } from "./Tabs";
import { PreviousDayBoxPanel } from "./PreviousDayBox";

export function Strategies({ config, live, profile, act, busy }: PageProps) {
  const [tab, setTab] = useState("Active setups"),
    [past, setPast] = useState(false),
    [filter, setFilter] = useState("All");
  const p = live.profiles[profile] || {},
    jobs: Json[] = p.jobs || [],
    byId = new Map(jobs.map((j) => [j.alert_id, j])),
    active: Json[] = live.alerts.filter((a: Json) => a.status === "Active");
  active.sort(
    (a, b) =>
      Number(["Open", "Closing"].includes(byId.get(b.id)?.state)) -
        Number(["Open", "Closing"].includes(byId.get(a.id)?.state)) ||
      b.id - a.id,
  );
  const names: string[] = config.strategies.map((spec: Json) => spec.name);
  const selected: string[] = config.policies[profile]?.strategies || [];
  const authorization = (name: string) => {
    if (!selected.includes(name)) return "Watch only";
    const spec = config.strategies.find((s: Json) => s.name === name);
    const parameters =
      spec?.id === "vwap_ema_cross"
        ? config.vwap
        : spec?.id === "previous_day_box"
          ? config.previous_day_box
          : null;
    if (
      parameters &&
      (!parameters.monitor_enabled || !parameters[`${profile}_enabled`])
    )
      return "Selected / opt-in disabled";
    if (!p.settings?.enabled) return "Selected / entries paused";
    if (!p.runtime?.updated_at || age(p.runtime.updated_at) > 45)
      return "Selected / worker stale";
    const session = p.settings.automation || p.settings.strategy_testing;
    if (profile === "practice" && !session?.strategies?.includes(spec?.id))
      return "Selected / session restart needed";
    return "Selected / entries armed";
  };
  return (
    <>
      <Tabs
        values={[
          "Active setups",
          "Decision log",
          "Notifications",
          "Previous Day Box",
        ]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Previous Day Box" ? (
        <PreviousDayBoxPanel />
      ) : tab === "Active setups" ? (
        <div className="strategy-layout">
          <section>
            <div className="section-heading">
              <h2>Strategy watch</h2>
              <span>NQ / ES / YM</span>
            </div>
            <div className="quote-strip">
              {symbols.map((s) => (
                <div key={s}>
                  <small>{s.replace("=F", "")}</small>
                  <strong>{price(live.prices[s]?.price)}</strong>
                  <span
                    className={
                      age(live.prices[s]?.event_time) < 15
                        ? "positive"
                        : "muted"
                    }
                  >
                    {age(live.prices[s]?.event_time) < 15
                      ? "Fresh"
                      : "Unavailable / delayed"}
                  </span>
                </div>
              ))}
            </div>
            <div className="table-scroll">
              <table className="matrix">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    {symbols.map((s) => (
                      <th key={s}>
                        {s.replace("=F", "")}
                        <small>
                          {config.policies[profile]?.symbols?.includes(
                            { "NQ=F": "MNQ", "ES=F": "MES", "YM=F": "MYM" }[s],
                          )
                            ? "Entry instrument selected"
                            : "Watch only"}
                        </small>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {names.map((name) => (
                    <tr key={name}>
                      <th>
                        {name}
                        <small>{authorization(name)}</small>
                      </th>
                      {symbols.map((s) => {
                        const row = live.monitor.find(
                            (r: Json) => r.symbol === s && r.strategy === name,
                          ),
                          sig = row?.signal,
                          stale = !row?.updated_at || age(row.updated_at) > 30;
                        return (
                          <td key={s}>
                            <Badge
                              tone={
                                sig?.signal === "LONG"
                                  ? "positive"
                                  : sig?.signal === "SHORT"
                                    ? "negative"
                                    : ""
                              }
                            >
                              {stale
                                ? "NO CURRENT RESULT"
                                : sig?.signal || "WAIT"}
                            </Badge>
                            <small>
                              {stale
                                ? live.session?.is_open
                                  ? "Awaiting worker evaluation"
                                  : "Market closed"
                                : sig?.signal === "WAIT"
                                  ? row?.indicator_snapshot?.reason ||
                                    sig?.reason ||
                                    "Waiting for a setup"
                                  : row?.focus_value ||
                                    sig?.reason ||
                                    "No current evaluation"}
                            </small>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!names.length && (
              <Empty
                title="Monitor has no current results"
                detail="The market worker runs independently of this interface."
              />
            )}
          </section>
          <section className="alerts-column">
            <div className="section-heading">
              <h2>
                Active alerts <Badge>{active.length}</Badge>
              </h2>
              <button
                disabled={busy || !active.length}
                onClick={() =>
                  void act("/alerts/clear", { ids: active.map((a) => a.id) })
                }
              >
                <Trash2 size={14} />
                Clear watch only
              </button>
            </div>
            {!active.length && (
              <Empty
                title="Watching for the next setup"
                detail="No active signal is recorded. A watch alert is not a broker fill."
              />
            )}
            {active.map((alert) => (
              <Alert
                key={alert.id}
                row={alert}
                job={byId.get(alert.id)}
                live={live}
                events={live.events}
                profile={profile}
              />
            ))}
            <button
              className="disclosure"
              aria-expanded={past}
              onClick={() => setPast(!past)}
            >
              {past ? "Hide" : "Show"} past alerts
            </button>
            {past && (
              <>
                <select
                  aria-label="Past alert symbol"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  {["All", ...symbols].map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
                {live.alerts
                  .filter(
                    (a: Json) =>
                      a.status !== "Active" &&
                      (filter === "All" || a.symbol === filter),
                  )
                  .slice(0, 30)
                  .map((alert: Json) => (
                    <Alert
                      key={alert.id}
                      row={alert}
                      job={byId.get(alert.id)}
                      live={live}
                      events={live.events}
                      profile={profile}
                    />
                  ))}
              </>
            )}
          </section>
        </div>
      ) : (
        <Table
          heads={["Time / CT", "Event", "Evidence", "Alert"]}
          rows={live.events
            .filter(
              (event: Json) =>
                (profile === "leader") === event.topic.startsWith("leader:") &&
                (tab !== "Notifications" || event.unread),
            )
            .map((event: Json) => [
              ct(event.time),
              <Badge tone={event.severity === "critical" ? "negative" : ""}>
                {event.kind}
              </Badge>,
              event.detail,
              event.alert_id,
            ])}
        />
      )}
    </>
  );
}

function Alert({
  row,
  job,
  live,
  events,
  profile,
}: {
  row: Json;
  job?: Json;
  live: Json;
  events: Json[];
  profile: string;
}) {
  const entered = !!job && ["Open", "Closing"].includes(job.state),
    pending = !!job && ["Intent", "Submitted", "Unknown"].includes(job.state),
    last = live.prices[row.symbol]?.price;
  const decisions = events.filter(
    (e) =>
      e.alert_id === row.id &&
      e.kind === "Entry blocked" &&
      (profile === "leader") === e.topic.startsWith("leader:"),
  );
  const entry = job?.fill_price ?? row.entry,
    move =
      last != null && entry != null
        ? (last - entry) * (row.signal === "LONG" ? 1 : -1)
        : null;
  return (
    <article className={"alert-item " + (entered ? "in-trade" : "")}>
      <header>
        <div>
          <b>{row.symbol?.replace("=F", "")}</b>
          <Badge tone={row.signal === "LONG" ? "positive" : "negative"}>
            {row.signal}
          </Badge>
          <span>{row.strategy}</span>
        </div>
        <Badge tone={entered ? "warning" : ""}>
          {entered
            ? "IN TRADE"
            : pending
              ? job?.state
              : row.status === "Active"
                ? "WATCH ONLY"
                : row.status}
        </Badge>
      </header>
      <div className="alert-time">
        #{row.id} · {ct(row.entry_time || row.detected_at)}
        {job?.symbol ? " · " + job.quantity + " " + job.symbol : ""}
      </div>
      <div className="alert-live">
        <span>
          Last <b>{price(last)}</b>
        </span>
        {move != null && (
          <span className={tone(move)}>
            {move > 0 ? "+" : ""}
            {move.toFixed(2)} pts{" "}
            {job?.fill_price ? "from broker fill" : "signal movement"}
          </span>
        )}
      </div>
      <div className="alert-levels">
        {[
          [entered ? "Broker fill" : "Signal entry", entry],
          ["Protective stop", row.stop],
          ["Target reference", row.target],
          ["Observed exit", row.exit_price],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <small>{label}</small>
            <b>{price(value as number)}</b>
          </div>
        ))}
      </div>
      <div className="evidence-grid">
        <div>
          <b>Setup evidence</b>
          <p>{row.trigger_detail || row.reason || "No evidence recorded."}</p>
        </div>
        <div>
          <b>Adaptive exit</b>
          <p>
            {row.exit_evidence ||
              row.management_status ||
              row.exit_reason ||
              "Waiting for a management update."}
          </p>
        </div>
      </div>
      {!entered && decisions.length > 0 && (
        <div className="entry-block">
          <ShieldAlert size={14} />
          {decisions[0].detail}
        </div>
      )}
    </article>
  );
}
