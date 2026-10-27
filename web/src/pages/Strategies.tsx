import { useState } from "react";
import { ShieldAlert, Trash2 } from "lucide-react";
import { age, ct, money, price, type Json } from "../api";
import { Badge, Empty, Table } from "../components";
import { type PageProps, symbols, tone } from "../pageTypes";
import { Tabs } from "./Tabs";
import { PreviousDayBoxPanel } from "./PreviousDayBox";

function watchDollars(rows: Json[]) {
  let won = 0,
    lost = 0;
  for (const row of rows) {
    const result = row.watch_outcome;
    if (
      !["WIN", "LOSS", "BREAKEVEN"].includes(result?.state) ||
      !Number.isFinite(result?.gross_one_micro)
    )
      continue;
    const cents = Math.round(result.gross_one_micro * 100);
    if (cents > 0) won += cents;
    else lost += cents;
  }
  return { won: won / 100, lost: lost / 100, net: (won + lost) / 100 };
}

export function Strategies({ config, live, profile, act, busy }: PageProps) {
  const [tab, setTab] = useState("Active setups"),
    [historyLimit, setHistoryLimit] = useState(30),
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
  const watched: Json[] = live.alerts.filter(
    (a: Json) =>
      !(p.execution_alert_ids || []).includes(a.id) &&
      !byId.get(a.id)?.fill_price &&
      !["Intent", "Submitted", "Unknown", "Open", "Closing"].includes(
        byId.get(a.id)?.state,
      ),
  );
  const watchCounts = (state: string) =>
    watched.filter((a) => a.watch_outcome?.state === state).length;
  const watchTotals = watchDollars(watched);
  const watchHistory = watched
    .filter(
      (a) => a.status !== "Active" && (filter === "All" || a.symbol === filter),
    )
    .sort((a, b) => b.id - a.id);
  const strategyResults = [...new Set(watched.map((a) => a.strategy))]
    .sort()
    .map((strategy) => {
      const rows = watched.filter((a) => a.strategy === strategy);
      const count = (state: string) =>
        rows.filter((a) => a.watch_outcome?.state === state).length;
      const wins = count("WIN"),
        losses = count("LOSS"),
        even = count("BREAKEVEN");
      const dollars = watchDollars(rows);
      return [
        strategy,
        wins,
        losses,
        even,
        wins + losses + even
          ? ((100 * wins) / (wins + losses + even)).toFixed(1) + "%"
          : "--",
        <span className="positive">{money(dollars.won)}</span>,
        <span className="negative">{money(dollars.lost)}</span>,
        <span className={tone(dollars.net)}>{money(dollars.net)}</span>,
        count("OPEN"),
        count("DISMISSED") + count("UNSCORED"),
      ];
    });
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
          "Real trades",
          "Watch-only history",
          "Decision log",
          "Notifications",
          "Previous Day Box",
        ]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Previous Day Box" ? (
        <PreviousDayBoxPanel />
      ) : tab === "Real trades" ? (
        <section aria-label="Real trade history">
          <h2>Real trade history</h2>
          <p className="muted">
            {profile === "leader" ? "Leader" : "Practice"} broker-confirmed
            closed trades only. Net results include reported costs; watch-only
            estimates are excluded.
          </p>
          <Table
            heads={[
              "Closed / CT",
              "Strategy",
              "Symbol",
              "Side",
              "Contracts",
              "Broker exit",
              "Costs",
              "Actual net P&L",
            ]}
            rows={[...(p.trades || [])]
              .sort((a, b) =>
                String(b.closed_at).localeCompare(String(a.closed_at)),
              )
              .map((trade: Json) => [
                ct(trade.closed_at),
                trade.strategy,
                trade.symbol,
                trade.direction,
                trade.quantity,
                price(trade.exit_price),
                money(trade.costs),
                <span className={tone(trade.net)}>{money(trade.net)}</span>,
              ])}
          />
          {!p.trades?.length && (
            <Empty
              title="No reconciled closed trades"
              detail="Only matched broker entries and exits appear here."
            />
          )}
        </section>
      ) : tab === "Watch-only history" ? (
        <section aria-label="Watch-only history">
          <h2>Watch-only results by strategy</h2>
          <div
            className="watch-results"
            aria-label="Hypothetical watch results"
          >
            <span className="positive">{watchCounts("WIN")} wins</span>
            <span className="negative">{watchCounts("LOSS")} losses</span>
            <span>{watchCounts("BREAKEVEN")} break-even</span>
            <span className="positive">
              Hypothetical won {money(watchTotals.won)}
            </span>
            <span className="negative">
              Hypothetical lost {money(watchTotals.lost)}
            </span>
            <span className={tone(watchTotals.net)}>
              Hypothetical net {money(watchTotals.net)}
            </span>
            <small>
              USD gross estimates for one micro contract per signal, before fees
              and slippage. Loaded watch-only history, not actual account
              profit. Open, cleared and unscored alerts are excluded from dollar
              totals; cleared and unscored alerts are excluded from win rate.
            </small>
          </div>
          <Table
            heads={[
              "Strategy",
              "Wins",
              "Losses",
              "Break-even",
              "Win rate",
              "Hypothetical won ($)",
              "Hypothetical lost ($)",
              "Hypothetical net ($)",
              "Open",
              "Cleared / unscored",
            ]}
            rows={strategyResults}
          />
          <h2>Watch-only history</h2>
          <select
            aria-label="Watch-only symbol"
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setHistoryLimit(30);
            }}
          >
            {["All", ...symbols, "MNQ=F", "MES=F", "MYM=F"].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {watchHistory.slice(0, historyLimit).map((alert) => (
            <Alert
              key={alert.id}
              row={alert}
              job={byId.get(alert.id)}
              live={live}
              decision={p.entry_decisions?.[alert.id]}
              profile={profile}
            />
          ))}
          {!watchHistory.length && (
            <Empty
              title="No closed watch-only alerts"
              detail="Untraded signals appear here after a strategy exit or manual clear."
            />
          )}
          {watchHistory.length > historyLimit && (
            <button onClick={() => setHistoryLimit(historyLimit + 30)}>
              Show more watch-only results
            </button>
          )}
        </section>
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
                decision={p.entry_decisions?.[alert.id]}
                profile={profile}
              />
            ))}
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
  decision,
  profile,
}: {
  row: Json;
  job?: Json;
  live: Json;
  decision?: Json;
  profile: string;
}) {
  const entered = !!job && ["Open", "Closing"].includes(job.state),
    pending = !!job && ["Intent", "Submitted", "Unknown"].includes(job.state),
    last = live.prices[row.symbol]?.price;
  const watchOnly =
    !entered && !pending && !job?.fill_price && row.status === "Active";
  const hypothetical = !entered && !pending && !job?.fill_price;
  const outcome = row.watch_outcome || {};
  const completedWatch =
    hypothetical && ["WIN", "LOSS", "BREAKEVEN"].includes(outcome.state);
  const blockedReason =
    job?.state === "Rejected" && job.error_message
      ? job.error_message
      : decision?.detail;
  const entry = job?.fill_price ?? row.entry,
    mark =
      hypothetical && row.status !== "Active"
        ? completedWatch
          ? row.exit_price
          : null
        : last,
    move =
      mark != null && entry != null
        ? (mark - entry) * (row.signal === "LONG" ? 1 : -1)
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
        <Badge
          tone={
            entered
              ? "warning"
              : completedWatch
                ? outcome.state === "WIN"
                  ? "positive"
                  : outcome.state === "LOSS"
                    ? "negative"
                    : ""
                : ""
          }
        >
          {entered
            ? "IN TRADE"
            : pending
              ? job?.state
              : row.status === "Active"
                ? "WATCH ONLY"
                : completedWatch
                  ? "WATCH " + outcome.state
                  : row.status}
        </Badge>
      </header>
      <div className="alert-time">
        #{row.id} · {ct(row.entry_time || row.detected_at)}
        {job?.symbol ? " · " + job.quantity + " " + job.symbol : ""}
      </div>
      <div className="alert-live">
        <span>
          {hypothetical && row.status !== "Active"
            ? "Hypothetical exit"
            : "Last"}{" "}
          <b>{price(mark)}</b>
        </span>
        {move != null && (
          <span className={tone(move)}>
            {move > 0 ? "+" : ""}
            {move.toFixed(2)} pts{" "}
            {job?.fill_price
              ? "from broker fill"
              : completedWatch
                ? "hypothetical result"
                : "hypothetical open movement"}
          </span>
        )}
      </div>
      <div className="alert-levels">
        {[
          [job?.fill_price ? "Broker fill" : "Hypothetical entry", entry],
          ["Protective stop", row.stop],
          ["Target reference", row.target],
          [
            hypothetical ? "Hypothetical exit" : "Observed exit",
            hypothetical && !completedWatch ? null : row.exit_price,
          ],
        ].map(([label, value]) => (
          <div key={String(label)}>
            <small>{label}</small>
            <b>{price(value as number)}</b>
          </div>
        ))}
      </div>
      {hypothetical && (
        <div className="watch-lifecycle">
          <span>
            Hypothetical entry: {ct(row.entry_time || row.detected_at)}
          </span>
          <span>
            Exit:{" "}
            {completedWatch
              ? ct(row.exit_time)
              : row.status === "Active"
                ? "Open / tracking strategy exit"
                : "No observed strategy exit"}
          </span>
          {completedWatch && (
            <span className={tone(outcome.gross_one_micro)}>
              1 {outcome.instrument}: {money(outcome.gross_one_micro)} gross
              estimate, before fees and slippage
            </span>
          )}
          {row.status !== "Active" && (
            <span>{row.exit_reason || "No exit reason recorded"}</span>
          )}
          <small>
            Signal prices are theoretical, not guaranteed fills or actual
            account results.
          </small>
        </div>
      )}
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
      {watchOnly && (
        <div className="entry-block" role="note">
          <ShieldAlert size={14} />
          <div>
            <b>
              No trade entered ({profile === "leader" ? "Leader" : "Practice"})
            </b>
            <p>
              {blockedReason ||
                "No execution decision recorded for this alert yet. A watch signal does not confirm an order."}
            </p>
            {decision?.time && (
              <small>Last recorded decision: {ct(decision.time)}</small>
            )}
            {decision?.previous?.map((earlier: Json) => (
              <p key={earlier.id}>
                <small>
                  Earlier block ({ct(earlier.time)}): {earlier.detail}
                </small>
              </p>
            ))}
          </div>
        </div>
      )}
    </article>
  );
}
