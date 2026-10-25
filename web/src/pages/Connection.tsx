import { useState } from "react";
import { RefreshCw, Play, Pause, Trash2, Plus, KeyRound } from "lucide-react";
import { type Json } from "../api";
import { Badge, Field, Metric, Notice, Table } from "../components";
import { type PageProps, symbols } from "../pageTypes";
import { Tabs } from "./Tabs";

export function Connection({ config, act, busy }: PageProps) {
  const [tab, setTab] = useState("API credentials"),
    [username, setUsername] = useState(""),
    [key, setKey] = useState(""),
    [symbol, setSymbol] = useState(""),
    [contract, setContract] = useState("");
  return (
    <>
      <Tabs
        values={["API credentials", "Market worker", "Instruments"]}
        selected={tab}
        onChange={setTab}
      />
      {tab === "API credentials" ? (
        <div className="form-layout">
          <form
            className="editor"
            onSubmit={async (e) => {
              e.preventDefault();
              const r = await act("/credentials", { username, api_key: key });
              if (r) {
                setKey("");
                setUsername("");
              }
            }}
          >
            <h2>Topstep / ProjectX</h2>
            <Badge>
              {config.credentials_present
                ? "Credentials configured"
                : "No API key configured"}
            </Badge>
            <Field label="TopstepX username">
              <input
                autoComplete="off"
                required
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </Field>
            <Field label="API key">
              <input
                type="password"
                autoComplete="new-password"
                required
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
            </Field>
            <div className="button-row">
              <button className="primary" disabled={busy}>
                <KeyRound size={16} />
                Save credentials
              </button>
              <button
                type="button"
                disabled={busy || !config.credentials_present}
                onClick={() => void act("/connection/test", {})}
              >
                <RefreshCw size={16} />
                Test connection
              </button>
            </div>
          </form>
          <aside className="policy-aside">
            <h2>Local credential storage</h2>
            <p className="muted">
              Existing keys are never returned to the browser. Credentials
              remain in the ignored local .env file.
            </p>
            <Notice>
              Pause and stop trading workers before changing an active login.
              Saving a key does not enable trading.
            </Notice>
            <p className="footnote">
              If provider access is unavailable, contact ProjectX with the error
              and timestamp. Never send the API key or bearer token.
            </p>
          </aside>
        </div>
      ) : tab === "Market worker" ? (
        <>
          <div className="metric-band compact">
            <Metric
              label="Market worker"
              value={config.worker.running ? "Running" : "Stopped"}
            />
            <Metric label="Process ID" value={config.worker.pid || "--"} />
            <Metric
              label="Restart after account replacement"
              value={config.restart_required ? "Required" : "Not required"}
            />
          </div>
          <div className="button-row">
            <button
              disabled={
                busy ||
                !config.credentials_present ||
                config.worker.running ||
                config.restart_required
              }
              onClick={() => void act("/workers/start", {})}
            >
              <Play size={16} />
              Start market worker
            </button>
            <button
              disabled={busy || !config.credentials_present}
              onClick={() => void act("/workers/stop", {})}
            >
              <Pause size={16} />
              Pause & stop trading workers
            </button>
          </div>
          <Notice>
            Worker shutdown requires broker-confirmed flat accounts and no
            unresolved jobs. Interface restart does not stop trading workers.
          </Notice>
        </>
      ) : (
        <>
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              void act("/instruments", { symbol, contract_id: contract });
            }}
          >
            <Field label="Symbol">
              <input
                required
                value={symbol}
                placeholder="NQ=F"
                onChange={(e) => setSymbol(e.target.value)}
              />
            </Field>
            <Field label="Contract ID">
              <input
                value={contract}
                placeholder="CON.F.US.ENQ.Z26"
                onChange={(e) => setContract(e.target.value)}
              />
            </Field>
            <button className="primary" disabled={busy}>
              <Plus size={16} />
              Add instrument
            </button>
          </form>
          <Table
            heads={["Instrument", "Active contract", ""]}
            rows={config.symbols.map((s: Json) => [
              s.symbol,
              s.contract_id || "Not mapped",
              <button
                className="icon"
                title={"Remove " + s.symbol}
                disabled={busy}
                onClick={() =>
                  void act(
                    "/instruments/" + encodeURIComponent(s.symbol),
                    undefined,
                    "DELETE",
                  )
                }
              >
                <Trash2 size={16} />
              </button>,
            ])}
          />
        </>
      )}
    </>
  );
}
