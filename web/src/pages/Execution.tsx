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
    target = config.targets[profile];
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const result = await act(`/execution/${profile}/${dialog}`, {
      name,
      safeguards: confirmed,
      acknowledge_loss: ack,
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
                label={s}
                value={
                  s === "MYM" && !settings.enable_mym
                    ? "Off"
                    : (settings.quantities?.[s] ?? 2)
                }
              />
            ))}
          </div>
          <Metric
            label="Realized account loss / $500 lock"
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
              config.restart_required
            }
            onClick={() => open("arm")}
          >
            <Play size={16} />
            Start {profile}
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
              heads={["Contract", "Position", "Average fill"]}
              rows={(p.broker.positions || []).map((r: Json) => [
                r.contractId,
                r.size,
                price(r.averagePrice),
              ])}
              empty="Broker reports no open positions"
            />
          )}
          <Tabs
            values={["Order attempts", "Broker fills"]}
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
                price(j.fill_price),
                j.protected ? "Verified" : "Not verified",
                j.error_message || j.close_reason || "--",
              ])}
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
            dialog === "arm"
              ? "Authorize " + profile + " trading"
              : "Request emergency close"
          }
          close={() => setDialog("")}
        >
          <form onSubmit={submit}>
            <Notice danger>
              {dialog === "arm"
                ? "This explicitly enables new automatic entries after broker preflight."
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
                label="I acknowledge the $500 loss and authorize resetting this account's baseline."
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
                  (dialog === "arm" && p.gate?.locked && !ack)
                }
              >
                {dialog === "arm" ? (
                  <Play size={16} />
                ) : (
                  <ShieldAlert size={16} />
                )}
                Confirm {dialog === "arm" ? "start" : "close request"}
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
