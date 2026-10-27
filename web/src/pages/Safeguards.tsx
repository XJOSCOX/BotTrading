import { useEffect, useRef, useState, type FormEvent } from "react";
import { Save, ShieldCheck } from "lucide-react";
import { Field, Metric, Notice, Table, Toggle } from "../components";
import { money, type Json } from "../api";
import type { PageProps } from "../pageTypes";

const fields = [
  ["loss_lock", "Cumulative account loss lock ($)"],
  ["max_contracts", "Maximum contracts per symbol"],
  ["max_trade_risk", "Planned risk per trade ($)"],
  ["max_open_risk", "Total open stop-risk budget ($)"],
];

export function Safeguards({ config, live, profile, act, busy }: PageProps) {
  const record = config.safeguards?.[profile];
  const [draft, setDraft] = useState<Json>({}),
    [dirty, setDirty] = useState(false),
    [feedback, setFeedback] = useState(""),
    [review, setReview] = useState(false),
    [name, setName] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [revision, setRevision] = useState(0),
    [reviewRevision, setReviewRevision] = useState(0);
  const selected = useRef("");
  useEffect(() => {
    if (selected.current !== profile || !dirty) {
      setDraft(record?.saved || {});
      setRevision(record?.revision || 0);
    }
    if (selected.current !== profile) {
      setDirty(false);
      setReview(false);
      setFeedback("");
      setName("");
      setConfirmed(false);
    }
    selected.current = profile;
  }, [profile, record, dirty]);
  if (!record)
    return (
      <Notice>
        Safeguard settings are unavailable. Active broker protections remain
        authoritative.
      </Notice>
    );
  const p = live.profiles[profile] || {},
    target = config.targets[profile],
    changed = fields.some(([key]) => record.saved[key] !== record.active[key]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (await act(`/safeguards/${profile}`, { ...draft, revision })) {
      setDirty(false);
      setReview(false);
      setFeedback("Saved. Active limits are unchanged.");
    }
  };
  const apply = async (event: FormEvent) => {
    event.preventDefault();
    if (
      await act(`/safeguards/${profile}/apply`, {
        name,
        confirmed,
        revision: reviewRevision,
      })
    ) {
      setReview(false);
      setName("");
      setConfirmed(false);
      setFeedback(
        "Applied. Entries remain paused; the loss baseline and any latched lock are unchanged.",
      );
    }
  };
  return (
    <section>
      <div className="context-bar">
        <span>{target.name}</span>
        <span>
          {dirty
            ? "Unsaved changes"
            : changed
              ? "Saved changes pending"
              : "Saved limits are active"}
        </span>
      </div>
      <div className="execution-layout">
        <form className="run-panel" onSubmit={save}>
          <h2>Account safeguards</h2>
          {fields.map(([key, label]) => (
            <Field key={key} label={label}>
              {key === "max_contracts" ? (
                <select
                  value={draft[key] ?? ""}
                  disabled={busy}
                  onChange={(e) => {
                    setDraft({ ...draft, [key]: Number(e.target.value) });
                    setDirty(true);
                    setReview(false);
                  }}
                >
                  {[1, 2, 3, 4].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type="number"
                  min="0.01"
                  max="1000000"
                  step="0.01"
                  required
                  value={draft[key] ?? ""}
                  disabled={busy}
                  onChange={(e) => {
                    setDraft({
                      ...draft,
                      [key]:
                        e.target.value === "" ? "" : Number(e.target.value),
                    });
                    setDirty(true);
                    setReview(false);
                  }}
                />
              )}
            </Field>
          ))}
          <button
            className="primary"
            disabled={busy || !dirty || config.restart_required}
          >
            <Save size={16} />
            Save safeguards
          </button>
          {feedback && <p role="status">{feedback}</p>}
        </form>
        <div>
          <h2>Active limits</h2>
          <Table
            heads={["Safeguard", "Active", "Saved"]}
            rows={fields.map(([key, label]) => [
              label,
              key === "max_contracts"
                ? record.active[key]
                : money(record.active[key]),
              key === "max_contracts"
                ? record.saved[key]
                : money(record.saved[key]),
            ])}
          />
          <div className="minor-metrics">
            <Metric
              label="Account loss since baseline"
              value={p.gate?.loss != null ? money(p.gate.loss) : "Not verified"}
            />
            <Metric
              label="Loss lock"
              value={
                p.gate?.locked === true
                  ? "Locked"
                  : p.gate?.locked === false
                    ? "Not locked"
                    : "Not verified"
              }
            />
          </div>
          <Notice>
            Applying requires paused entries and a verified-flat account. It
            does not reset losses, unlock a latched lock, change existing
            positions, or start trading.
          </Notice>
          <p className="footnote">
            The loss lock is cumulative, not per trade, and applies only to the
            selected account, not follower totals. Planned risk is an estimate;
            gaps, slippage and costs can exceed it. Contract sizes must remain
            within the supported 1–4 range.
          </p>
          <button
            disabled={
              busy ||
              dirty ||
              !changed ||
              p.settings?.enabled ||
              config.restart_required
            }
            onClick={() => {
              setReview(true);
              setReviewRevision(record.revision);
              setName("");
              setConfirmed(false);
            }}
          >
            <ShieldCheck size={16} />
            Review and apply
          </button>
          {p.settings?.enabled && changed && (
            <p role="status">Pause entries before applying saved safeguards.</p>
          )}
          {review && (
            <form onSubmit={apply}>
              <h3>Confirm {profile} safeguards</h3>
              <Field label={`Type the exact account name: ${target.name}`}>
                <input
                  value={name}
                  required
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Toggle
                label="I approve the saved limits shown above, including any increase in risk."
                value={confirmed}
                onChange={setConfirmed}
              />
              {record.revision !== reviewRevision && (
                <Notice danger>
                  Safeguards changed after this review. Cancel and review the
                  saved values again.
                </Notice>
              )}
              <button
                className="primary"
                disabled={
                  busy ||
                  !confirmed ||
                  name !== target.name ||
                  p.settings?.enabled ||
                  record.revision !== reviewRevision
                }
              >
                <ShieldCheck size={16} />
                Apply safeguards
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => setReview(false)}
              >
                Cancel
              </button>
            </form>
          )}
        </div>
      </div>
    </section>
  );
}
