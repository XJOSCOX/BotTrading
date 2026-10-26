import { useEffect, useRef, useState } from "react";
import {
  Power,
  Play,
  RotateCcw,
  Square,
  RefreshCw,
  X,
  LoaderCircle,
} from "lucide-react";
import { api, type Json } from "./api";
import { refresh } from "./store";
import "./SystemControls.css";

export function SystemControls({ reload }: { reload: () => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Json | null>(null);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const load = async () => setStatus(await api("/services"));
  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal();
    let active = true;
    const poll = () =>
      void api("/services")
        .then((result) => {
          if (active) setStatus(result);
        })
        .catch(() => {
          if (active) setStatus(null);
        });
    poll();
    const timer = setInterval(poll, 5000);
    return () => {
      active = false;
      clearInterval(timer);
      dialog.current?.close();
    };
  }, [open]);
  const run = async (action: string) => {
    if (pending) return;
    setPending(action);
    setError("");
    setMessage("");
    try {
      const result = await api("/services/" + action, {});
      setMessage(result.message);
      setStatus(result.services);
      try {
        await refresh();
        await reload();
      } catch {
        setError(
          "Command completed, but the workspace could not refresh. Verify service status before another action.",
        );
      }
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Service command failed. Verify current status before retrying.",
      );
      try {
        await load();
      } catch {
        setStatus(null);
      }
    } finally {
      setPending("");
    }
  };
  return (
    <>
      <button
        className="icon"
        title="System controls"
        aria-label="System controls"
        onClick={() => setOpen(true)}
      >
        <Power size={18} />
      </button>
      {open && (
        <dialog
          className="modal system-controls"
          ref={dialog}
          aria-labelledby="system-control-title"
          onCancel={(e) => {
            if (pending) e.preventDefault();
            else setOpen(false);
          }}
        >
          <div className="section-heading">
            <h2 id="system-control-title">System controls</h2>
            <button
              className="icon"
              title="Close system controls"
              disabled={!!pending}
              onClick={() => setOpen(false)}
            >
              <X size={18} />
            </button>
          </div>
          <div className="service-state">
            <span>Interface</span>
            <b className="positive">Online</b>
          </div>
          {[
            ["market", "Market feed / Strategies / Practice"],
            ["leader", "Leader execution worker"],
          ].map(([id, label]) => (
            <div className="service-state" key={id}>
              <span>{label}</span>
              <b className={status?.[id]?.running ? "positive" : "muted"}>
                {status?.[id]?.running == null
                  ? "Unknown"
                  : status[id].running
                    ? "Running"
                    : "Stopped"}
              </b>
            </div>
          ))}
          <div className="service-actions">
            <button
              className="primary"
              disabled={!!pending}
              onClick={() => void run("start")}
            >
              <Play size={17} />
              Start all
            </button>
            <button disabled={!!pending} onClick={() => void run("restart")}>
              <RotateCcw size={17} />
              Restart all
            </button>
            <button disabled={!!pending} onClick={() => void run("stop")}>
              <Square size={16} />
              Stop all
            </button>
            <button
              className="icon"
              title="Refresh service status"
              disabled={!!pending}
              onClick={() =>
                void load().catch(() => {
                  setStatus(null);
                  setError("Service status unavailable.");
                })
              }
            >
              <RefreshCw size={17} />
            </button>
          </div>
          {pending && (
            <p className="service-progress" role="status">
              <LoaderCircle size={16} className="spin" />
              {pending === "stop"
                ? "Pausing entries and checking broker exposure"
                : pending === "restart"
                  ? "Checking exposure, then restarting workers"
                  : "Starting workers"}
            </p>
          )}
          {error && (
            <p className="service-error" role="alert">
              {error}
            </p>
          )}
          {message && (
            <p className="positive" role="status">
              {message}
            </p>
          )}
          <p className="footnote">
            Stop and Restart pause both accounts first. Open positions or
            unresolved orders block shutdown so exit monitoring stays active.
            Start requires paused accounts and never authorizes trades. The
            interface stays open.
          </p>
        </dialog>
      )}
    </>
  );
}
