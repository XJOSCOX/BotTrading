import { useEffect, useState } from "react";
import {
  Activity,
  BarChart3,
  ChartCandlestick,
  SlidersHorizontal,
  ListFilter,
  ShieldCheck,
  Zap,
  WalletCards,
  KeyRound,
  FlaskConical,
  Menu,
  X,
  Wifi,
  WifiOff,
  Bell,
  ArrowUpRight,
  LoaderCircle,
} from "lucide-react";
import { api, ct, type Json } from "./api";
import { connect, refresh, useLive } from "./store";
import {
  Accounts,
  Charts,
  Connection,
  Controls,
  Dashboard,
  Execution,
  Research,
  Strategies,
  type PageProps,
} from "./pages";
import { Badge, Notice } from "./components";
import { StrategyManager } from "./pages/StrategyManager";
import { TradeManagement } from "./pages/TradeManagement";

const navigation = [
  {
    name: "Dashboard",
    id: "dashboard",
    icon: BarChart3,
    group: "Workspace",
    detail: "Realized performance and execution quality",
    component: Dashboard,
  },
  {
    name: "Charts",
    id: "charts",
    icon: ChartCandlestick,
    group: "Workspace",
    detail: "Price action, volume and momentum",
    component: Charts,
  },
  {
    name: "Strategies",
    id: "strategies",
    icon: Activity,
    group: "Trading",
    detail: "Current setups, evidence and execution decisions",
    component: Strategies,
  },
  {
    name: "Control Center",
    id: "controls",
    icon: SlidersHorizontal,
    group: "Trading",
    detail: "Strategy selection, sizing and re-entry policy",
    component: Controls,
  },
  {
    name: "Execution",
    id: "execution",
    icon: Zap,
    group: "Trading",
    detail: "Account-specific authorization and actual fills",
    component: Execution,
  },
  {
    name: "Strategy Manager",
    id: "manager",
    icon: ListFilter,
    group: "Trading",
    detail: "Shadow decisions and shared portfolio research",
    component: StrategyManager,
  },
  {
    name: "Trade Management",
    id: "trade-management",
    icon: ShieldCheck,
    group: "Trading",
    detail: "Frozen exit policies, software protection and profit giveback",
    component: TradeManagement,
  },
  {
    name: "Research",
    id: "research",
    icon: FlaskConical,
    group: "Trading",
    detail: "Historical simulation, separate from broker results",
    component: Research,
  },
  {
    name: "Accounts",
    id: "accounts",
    icon: WalletCards,
    group: "Settings",
    detail: "Execution identities and guarded account replacement",
    component: Accounts,
  },
  {
    name: "Connection",
    id: "connection",
    icon: KeyRound,
    group: "Settings",
    detail: "Local credentials, market worker and instruments",
    component: Connection,
  },
];

export default function App() {
  const live = useLive(),
    [config, setConfig] = useState<Json | null>(null),
    [page, setPage] = useState(location.hash.slice(1) || "dashboard"),
    [mobile, setMobile] = useState(false);
  const [profile, setProfile] = useState(
      localStorage.getItem("gx-profile") || "practice",
    ),
    [busy, setBusy] = useState(false),
    [toast, setToast] = useState<{ text: string; error: boolean } | null>(null),
    [fatal, setFatal] = useState("");
  const reload = async () => setConfig(await api("/config"));
  useEffect(() => {
    const reloadOnConnect = () => {
      void reload().catch((e) => setFatal(String(e)));
    };
    window.addEventListener("gox-connected", reloadOnConnect);
    const cleanup = connect();
    void reload().catch((e) => setFatal(String(e)));
    void refresh().catch((e) => setFatal(String(e)));
    const nav = () => {
      setPage(location.hash.slice(1) || "dashboard");
      setMobile(false);
    };
    window.addEventListener("hashchange", nav);
    return () => {
      cleanup();
      window.removeEventListener("hashchange", nav);
      window.removeEventListener("gox-connected", reloadOnConnect);
    };
  }, []);
  const act: PageProps["act"] = async (path, body, method) => {
    if (busy) return;
    setBusy(true);
    setToast(null);
    try {
      const result = await api(path, body, method);
      setToast({
        text: result.message || "Operation completed.",
        error: false,
      });
      try {
        await refresh();
        await reload();
      } catch {
        setToast({
          text: "The operation succeeded, but the display could not refresh. Reload to verify current state before another action.",
          error: true,
        });
      }
      return result;
    } catch (e) {
      setToast({
        text: e instanceof Error ? e.message : String(e),
        error: true,
      });
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  const current = navigation.find((n) => n.id === page) || navigation[0],
    View = current.component;
  const groups = ["Workspace", "Trading", "Settings"],
    active = live.profiles[profile] || {},
    notifications = live.events.filter((e: Json) => e.unread).length;
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (mobile ? "open" : "")}>
        <a className="brand" href="#dashboard">
          <span className="brand-mark">GX</span>
          <span>
            <strong>GoXTrade</strong>
            <small>Trading workspace</small>
          </span>
        </a>
        <div className="workspace-label">
          <span>Personal workspace</span>
          <Badge>LOCAL</Badge>
        </div>
        <nav aria-label="Main navigation">
          {groups.map((group) => (
            <section key={group}>
              <h2>{group}</h2>
              {navigation
                .filter((n) => n.group === group)
                .map((n) => (
                  <a
                    key={n.id}
                    href={"#" + n.id}
                    onClick={() => setMobile(false)}
                    aria-current={current.id === n.id ? "page" : undefined}
                  >
                    <n.icon size={17} />
                    {n.name}
                  </a>
                ))}
            </section>
          ))}
        </nav>
        <footer>
          <span className={"status-dot " + (live.connected ? "online" : "")} />
          <div>
            <b>
              {live.connected
                ? "Local API connected"
                : "Local API reconnecting"}
            </b>
            <small>Chicago time (CT)</small>
          </div>
        </footer>
      </aside>
      {mobile && (
        <button
          className="nav-overlay"
          aria-label="Close navigation"
          onClick={() => setMobile(false)}
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <div>
            <button
              className="icon mobile-menu"
              title="Open navigation"
              onClick={() => setMobile(true)}
            >
              <Menu size={20} />
            </button>
            <span className="breadcrumb">
              Workspace <span>/</span> {current.name}
            </span>
          </div>
          <div className="topbar-right">
            <span className="live-clock">
              {live.session?.time ? ct(live.session.time) : "Chicago / CT"}
            </span>
            <span
              className={
                "connection-status " + (live.connected ? "" : "negative")
              }
            >
              {live.connected ? <Wifi size={14} /> : <WifiOff size={14} />}
              <span>{live.connected ? "Live interface" : "Reconnecting"}</span>
            </span>
            <a
              className="icon notification"
              title="Notifications"
              href="#strategies"
            >
              <Bell size={17} />
              {notifications > 0 && <i>{notifications}</i>}
            </a>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">{current.group}</div>
              <h1>{current.name}</h1>
              <p>{current.detail}</p>
            </div>
            <div className="profile-select">
              <span>Account view</span>
              <select
                aria-label="Account view"
                disabled={busy}
                value={profile}
                onChange={(e) => {
                  setProfile(e.target.value);
                  localStorage.setItem("gx-profile", e.target.value);
                }}
              >
                <option value="practice">Practice</option>
                <option value="leader">Leader</option>
              </select>
              <Badge tone={active.settings?.enabled ? "positive" : ""}>
                {active.settings?.enabled ? "Running" : "Paused"}
              </Badge>
            </div>
          </div>
          {fatal && (
            <Notice danger>
              {fatal}
              <button
                onClick={() => {
                  setFatal("");
                  void reload().catch((e) => setFatal(String(e)));
                }}
              >
                Retry connection
              </button>
            </Notice>
          )}
          {config?.restart_required && (
            <Notice danger>
              Account identity changed. Restart the interface and trading
              workers before enabling new entries.
            </Notice>
          )}
          {config ? (
            <View
              live={live}
              config={config}
              profile={profile}
              act={act}
              busy={busy}
            />
          ) : (
            <div className="loading">
              <LoaderCircle size={25} className="spin" />
              <span>Loading local workspace</span>
            </div>
          )}
          <footer className="page-footer">
            <span>
              Local workspace · Independent trading workers ·{" "}
              {live.session?.name || "Session unavailable"}
            </span>
            <a href="http://127.0.0.1:8502" target="_blank" rel="noreferrer">
              Legacy workspace <ArrowUpRight size={13} />
            </a>
          </footer>
        </main>
      </div>
      {toast && (
        <div className={"toast " + (toast.error ? "error" : "")} role="status">
          <span>{toast.text}</span>
          <button
            className="icon"
            title="Dismiss message"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {busy && (
        <div className="busy-indicator" role="status">
          <LoaderCircle size={15} className="spin" />
          Processing request
        </div>
      )}
    </div>
  );
}
