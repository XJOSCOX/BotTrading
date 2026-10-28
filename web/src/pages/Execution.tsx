import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { RefreshCw, Play, Pause, ShieldAlert } from "lucide-react";
import { ct, money, price, type Json } from "../api";
import { Badge, Field, Metric, Notice, Table, Toggle } from "../components";
import { type PageProps, tone, fresh } from "../pageTypes";
import { Tabs } from "./Tabs";

export function Execution({ live, config, profile, act, busy }: PageProps) {
  const p = live.profiles[profile] || {},
    settings = p.settings || {},
    runtime = p.runtime || {},
    [dialog, setDialog] = useState(""),
    [name, setName] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [ack, setAck] = useState(false),
    [tab, setTab] = useState("Order attempts");
  const valid = fresh(runtime.updated_at),
    credential = !!config.credentials_present,
    target = config.targets[profile],
    automation = settings.automation || settings.strategy_testing,
    savedStrategies = (config.policies?.[profile]?.strategies || [])
      .map(
        (name: string) =>
          config.strategies.find((s: Json) => s.name === name)?.id,
      )
      .filter(Boolean),
    activeSizes = Object.fromEntries(
      automation?.policy?.symbol_quantities || [],
    );
  const lossLimit =
    p.safeguards?.active?.loss_lock ??
    config.safeguards?.[profile]?.active?.loss_lock;
  const sizeFor = (symbol: string) => {
    if (
      (symbol === "MYM" && !settings.enable_mym) ||
      (settings.enabled &&
        automation &&
        !automation.policy.symbols.includes(symbol))
    )
      return "Off";
    if (!settings.enabled) return settings.quantities?.[symbol] ?? "Not set";
    const requested = automation
      ? (activeSizes[symbol] ?? automation.policy.requested_quantity)
      : settings.quantities?.[symbol];
    const cap = p.effective_limits?.max_contracts;
    if (!Number.isFinite(requested) || !Number.isFinite(cap))
      return "Not verified";
    return Math.min(requested, cap, automation?.policy?.max_contracts ?? cap);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const result = await act(`/execution/${profile}/${dialog}`, {
      name,
      safeguards: confirmed,
      acknowledge_loss: ack,
      strategies: savedStrategies,
      quantities: settings.quantities,
    });
    if (result) setDialog("");
  };
  const open = (action: string) => {
    setDialog(action);
    setName("");
    setConfirmed(false);
    setAck(false);
  };
  return (
    <>
      <div className="context-bar">
        <Badge tone={settings.enabled ? "positive" : ""}>
          {settings.enabled ? "Entries enabled" : "Entries paused"}
        </Badge>
        <span>
          {target.name.startsWith("YOUR_")
            ? "No account configured"
            : target.name}
        </span>
        <span>
          {valid
            ? "Worker updated " + ct(runtime.updated_at)
            : "Worker offline or stale"}
        </span>
      </div>
      <div className="execution-layout">
        <aside className="run-panel">
          <h2>Run controls</h2>
          <p className="runtime-message">
            {runtime.message || "Worker not started"}
          </p>
          <div className="minor-metrics">
            {["MNQ", "MES", "MYM"].map((s) => (
              <Metric
                key={s}
                label={`${s} ${settings.enabled ? "active max" : "saved"}`}
                value={sizeFor(s)}
              />
            ))}
          </div>
          <Metric
            label={`Realized account loss / ${lossLimit != null ? money(lossLimit) : "configured"} lock`}
            value={p.gate?.loss != null ? money(p.gate.loss) : "Not verified"}
            tone={p.gate?.locked ? "negative" : ""}
          />
          {config.restart_required && (
            <Notice danger>
              Account changed. Restart the interface and workers before
              authorization.
            </Notice>
          )}
          <button
            className="primary"
            disabled={
              busy ||
              !credential ||
              !valid ||
              settings.enabled ||
              (profile === "practice" && !savedStrategies.length) ||
              config.restart_required
            }
            onClick={() => open(profile === "practice" ? "start" : "arm")}
          >
            <Play size={16} />
            {profile === "practice"
              ? "Start Practice automation"
              : "Start Leader"}
          </button>
          <button
            disabled={busy}
            onClick={() =>
              void act(`/execution/${profile}/pause`, {
                name: "",
                safeguards: false,
              })
            }
          >
            <Pause size={16} />
            Pause new entries
          </button>
          {profile === "leader" && !valid && (
            <button
              disabled={busy || !credential || config.restart_required}
              onClick={() =>
                void act("/execution/leader/monitor", {
                  name: "",
                  safeguards: false,
                })
              }
            >
              <RefreshCw size={16} />
              Start Leader monitor
            </button>
          )}
          <button
            className="danger-button"
            disabled={busy || !credential}
            onClick={() => open("emergency")}
          >
            <ShieldAlert size={16} />
            Emergency close
          </button>
          <p className="footnote">
            Pause leaves existing positions monitored. Closing this browser does
            not stop workers.
          </p>
        </aside>
        <section>
          <div className="metric-band compact">
            <Metric label="Winning exits" value={p.totals?.wins ?? 0} />
            <Metric label="Losing exits" value={p.totals?.losses ?? 0} />
            <Metric
              label="Bot net P&L"
              value={money(p.totals?.net ?? 0)}
              tone={tone(p.totals?.net ?? 0)}
            />
          </div>
          <div className="section-heading">
            <h2>Broker exposure</h2>
            <span>
              {fresh(p.broker?.updated_at) && !p.broker?.error
                ? "Updated " + ct(p.broker.updated_at)
                : "Unavailable / stale"}
            </span>
          </div>
          {!fresh(p.broker?.updated_at) || p.broker?.error ? (
            <Notice>
              Do not assume the account is flat while the broker snapshot is
              unavailable.
            </Notice>
          ) : (
            <Table
              heads={["Contract", "Position", "Average fill", "Broker stop"]}
              rows={(p.broker.positions || []).map((r: Json) => [
                r.contractId,
                r.size,
                price(r.averagePrice),
                (p.broker.orders || [])
                  .filter(
                    (o: Json) =>
                      o.contractId === r.contractId &&
                      o.type === 4 &&
                      (p.jobs || []).some(
                        (j: Json) =>
                          j.protected &&
                          j.contract_id === r.contractId &&
                          o.parentOrderId === j.order_id &&
                          o.size === j.quantity &&
                          o.side === 1 - j.side,
                      ),
                  )
                  .map((o: Json) => price(o.stopPrice))
                  .join(", ") || "Not verified",
              ])}
              empty="Broker reports no open positions"
            />
          )}
          <Tabs
            values={["Order attempts", "Broker fills", "Rejected signals"]}
            selected={tab}
            onChange={setTab}
          />
          {tab === "Order attempts" ? (
            <Table
              heads={[
                "Submitted / CT",
                "Symbol",
                "Qty",
                "State",
                "Confirmation",
                "Actual fill",
                "Protection",
                "Reason",
              ]}
              rows={(p.jobs || []).map((j: Json) => [
                ct(j.sent_at ? new Date(j.sent_at * 1000).toISOString() : null),
                j.symbol,
                j.quantity,
                <Badge
                  tone={
                    j.state === "Rejected" || j.state === "Unknown"
                      ? "negative"
                      : j.state === "Open"
                        ? "positive"
                        : ""
                  }
                >
                  {j.state}
                </Badge>,
                j.entry_confirmation_mode || "--",
                price(j.fill_price),
                j.protected ? "Verified" : "Not verified",
                j.error_message || j.close_reason || "--",
              ])}
            />
          ) : tab === "Rejected signals" ? (
            <Table
              heads={["Time / CT", "Alert", "Reason"]}
              rows={(live.events || [])
                .filter(
                  (r: Json) =>
                    r.kind === "Entry blocked" &&
                    (profile === "leader") ===
                      String(r.topic || "").startsWith("leader:"),
                )
                .map((r: Json) => [ct(r.time), r.alert_id, r.detail])}
              empty="No rejected signals recorded"
            />
          ) : (
            <Table
              heads={[
                "Time / CT",
                "Account",
                "Contract",
                "Side",
                "Qty",
                "Fill",
                "Realized P&L",
                "Fees",
              ]}
              rows={(p.fills || []).map((f: Json) => [
                ct(f.creationTimestamp),
                f.accountId,
                f.contractId,
                f.side === 0 ? "Buy" : "Sell",
                f.size,
                price(f.price),
                money(f.profitAndLoss),
                money(f.fees),
              ])}
            />
          )}
        </section>
      </div>
      {dialog && (
        <Modal
          title={
            dialog === "arm" || dialog === "start"
              ? "Authorize " + profile + " trading"
              : "Request emergency close"
          }
          close={() => setDialog("")}
        >
          <form onSubmit={submit}>
            <Notice danger>
              {dialog === "arm" || dialog === "start"
                ? dialog === "start"
                  ? `Authorizes automatic Practice entries through the manager with these saved sizes: ${(config.policies?.practice?.symbols || []).map((s: string) => `${s} ${settings.quantities?.[s]}`).join(", ")}. Strategies: ${(config.policies?.practice?.strategies || []).join(", ")}. Existing risk limits remain authoritative and can reduce or block size. Leader is not enabled. Pause stops entries, not exit management.`
                  : "This explicitly enables new automatic entries after broker preflight."
                : "This pauses entries and requests a close of bot-owned positions. A request is not a confirmed fill."}
            </Notice>
            <Field label={"Type the exact account name: " + target.name}>
              <input
                autoFocus
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Toggle
              label="I verified the account identity, Auto OCO protection, copier setup, and no manual trading."
              value={confirmed}
              onChange={setConfirmed}
            />
            {p.gate?.locked && (
              <Toggle
                label={`I acknowledge the ${lossLimit != null ? money(lossLimit) : "configured"} loss lock and authorize resetting this account's baseline.`}
                value={ack}
                onChange={setAck}
              />
            )}
            <div className="modal-actions">
              <button type="button" onClick={() => setDialog("")}>
                Cancel
              </button>
              <button
                className="primary"
                disabled={
                  busy ||
                  !confirmed ||
                  name !== target.name ||
                  ((dialog === "arm" || dialog === "start") &&
                    p.gate?.locked &&
                    !ack)
                }
              >
                {dialog === "arm" || dialog === "start" ? (
                  <Play size={16} />
                ) : (
                  <ShieldAlert size={16} />
                )}
                Confirm{" "}
                {dialog === "arm" || dialog === "start"
                  ? "start"
                  : "close request"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!dialog.current?.open) dialog.current?.showModal();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="modal"
      aria-label={title}
      onCancel={(event) => {
        event.preventDefault();
        close();
      }}
    >
      <h2>{title}</h2>
      {children}
    </dialog>
  );
}
