import { useState } from "react";
import { Save, RefreshCw } from "lucide-react";
import { money, type Json } from "../api";
import { Badge, Field, Notice, Table, Toggle } from "../components";
import { type PageProps } from "../pageTypes";
import { Tabs } from "./Tabs";

export function Accounts({ config, act, busy }: PageProps) {
  const [directory, setDirectory] = useState<Json[]>([]),
    [tab, setTab] = useState("Account directory"),
    [profile, setProfile] = useState("leader"),
    [id, setId] = useState(""),
    [name, setName] = useState(""),
    [confirmation, setConfirmation] = useState(false);
  const refresh = async () => {
    const r = await act("/accounts/refresh", {});
    if (r) setDirectory(r.accounts);
  };
  return (
    <>
      <div className="account-grid">
        {Object.entries(config.targets).map(([profile, t]) => {
          const target = t as Json,
            configured = !target.name.startsWith("YOUR_");
          return (
            <article className="account-tile" key={profile}>
              <small>{profile} execution</small>
              <h2>{configured ? target.name : "No account assigned"}</h2>
              <footer>
                <span>
                  {configured
                    ? "ID " + target.id
                    : "Select a verified broker identity"}
                </span>
                <Badge>
                  {config.restart_required
                    ? "Restart required"
                    : configured
                      ? "Configured"
                      : "Not configured"}
                </Badge>
              </footer>
            </article>
          );
        })}
      </div>
      <Tabs
        values={["Account directory", "Replace execution account"]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "Account directory" ? (
        <>
          <div className="section-heading">
            <h2>Trading-enabled accounts</h2>
            <button
              disabled={busy || !config.credentials_present}
              onClick={() => void refresh()}
            >
              <RefreshCw size={16} />
              Refresh accounts
            </button>
          </div>
          {!config.credentials_present && (
            <Notice>
              Add your API credentials on Connection. The directory is retrieved
              only on request.
            </Notice>
          )}
          <Table
            heads={["Account", "ID", "Balance", "Copy label", "Environment"]}
            rows={directory.map((a) => [
              a.name,
              a.id,
              money(a.balance),
              a.copy_role,
              a.simulated ? "Simulated" : "Live",
            ])}
          />
          <p className="footnote">
            Copy labels are local records, not verification of Topstep copier
            configuration.
          </p>
        </>
      ) : (
        <div className="form-layout">
          <form
            className="editor"
            onSubmit={(e) => {
              e.preventDefault();
              void act(`/accounts/${profile}/replace`, {
                account_id: +id,
                name,
                confirmed: confirmation,
              });
            }}
          >
            <h2>New account identity</h2>
            <Field label="Replace execution profile">
              <select
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
              >
                <option value="leader">Leader</option>
                <option value="practice">Practice</option>
              </select>
            </Field>
            <Field label="Numeric broker account ID">
              <input
                type="number"
                min="1"
                required
                value={id}
                onChange={(e) => setId(e.target.value)}
              />
            </Field>
            <Field label="Exact new account name">
              <input
                required
                value={name}
                placeholder="50KTC-... or PRAC-..."
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Toggle
              label="Both profiles are paused, workers are stopped, old/new accounts are flat, and I verified copier configuration."
              value={confirmation}
              onChange={setConfirmation}
            />
            <button
              className="primary"
              disabled={busy || !confirmation || !config.credentials_present}
            >
              <Save size={16} />
              Verify & save replacement
            </button>
          </form>
          <aside className="policy-aside">
            <h2>Account safeguards</h2>
            <ol>
              <li>Pause both profiles and resolve all jobs.</li>
              <li>Stop trading workers on Connection.</li>
              <li>Verify the new ID and exact name.</li>
              <li>Save and restart the interface and workers.</li>
              <li>Review controls before explicitly starting.</li>
            </ol>
            <Notice>
              History and loss locks are retained. Failed or unavailable
              flat-state verification blocks replacement. Funded accounts are
              not enabled here.
            </Notice>
          </aside>
        </div>
      )}
    </>
  );
}
