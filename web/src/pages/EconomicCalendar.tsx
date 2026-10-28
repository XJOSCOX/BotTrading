import { useEffect, useRef, useState, type FormEvent } from "react";
import { RefreshCw, Save, Plus, Trash2, ExternalLink } from "lucide-react";
import { api, ct, type Json } from "../api";
import { Badge, Field, Notice, Table, Toggle } from "../components";
import type { PageProps } from "../pageTypes";

const dayCT = (value: string) => new Intl.DateTimeFormat("en-CA", { timeZone: "America/Chicago", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));

export function EconomicCalendar({ act, busy }: PageProps) {
  const [data, setData] = useState<Json | null>(null), [draft, setDraft] = useState<Json>({}),
    [date, setDate] = useState(dayCT(new Date().toISOString())), [range, setRange] = useState("7"),
    [error, setError] = useState(""), [feedback, setFeedback] = useState(""),
    [manual, setManual] = useState({ title: "", event_at: "", impact: "high", source_url: "" });
  const dirty = useRef(false);
  async function load() {
    try {
      const next = await api("/economic-calendar"); setData(next); setError("");
      if (!dirty.current) setDraft(next.settings);
    } catch { setError("Economic calendar unavailable. Verify source status before relying on event coverage."); }
  }
  useEffect(() => { void load(); const id = window.setInterval(load, 30000); return () => window.clearInterval(id); }, []);
  function change(key: string, value: unknown) { dirty.current = true; setDraft((old: Json) => ({ ...old, [key]: value })); }
  async function save(e: FormEvent) {
    e.preventDefault(); if (await act("/economic-calendar/settings", draft)) {
      dirty.current = false; setFeedback("Event windows saved for Practice. Open-position exits unchanged."); await load();
    }
  }
  async function add(e: FormEvent) {
    e.preventDefault(); if (await act("/economic-calendar/events", manual)) {
      setManual({ title: "", event_at: "", impact: "high", source_url: "" }); await load();
    }
  }
  async function remove(id: string) {
    try { await api("/economic-calendar/events/" + encodeURIComponent(id), undefined, "DELETE"); await load(); }
    catch { setError("Unable to remove manual event."); }
  }
  const end = new Date(date + "T12:00:00Z"); end.setUTCDate(end.getUTCDate() + Number(range));
  const until = end.toISOString().slice(0, 10);
  const events = (data?.events || []).filter((row: Json) => dayCT(row.event_at) >= date && dayCT(row.event_at) < until);
  return <section className="economic-calendar">
    {error && <Notice danger>{error}</Notice>}
    {data?.settings.enabled && !data.runtime_ready ? <Notice danger>Practice worker reload pending. Configured event windows are not verified active; existing-position management remains unchanged.</Notice> : data?.block ? <Notice danger>{data.block}</Notice> : <Notice>{data?.settings.enabled ? "Practice event guard enabled / Outside blocked event windows" : "Practice event guard disabled / Calendar only"}</Notice>}
    <p className="muted">{data?.coverage}</p>
    <div className="economic-calendar-layout">
      <aside>
        <form onSubmit={save}>
          <h2>Practice event windows</h2>
          <Toggle label="Pause new entries around selected events" value={!!draft.enabled} onChange={(value) => change("enabled", value)} />
          <div className="economic-fields">
            {[["before_minutes", "Before release (min)"], ["after_minutes", "After release (min)"], ["critical_before_minutes", "Before FOMC / critical (min)"], ["critical_after_minutes", "After FOMC / critical (min)"]].map(([key, label]) => <Field key={key} label={label}><input type="number" min="0" max="240" required value={draft[key] ?? 0} onChange={(e) => change(key, +e.target.value)} /></Field>)}
          </div>
          <fieldset><legend>Pause by impact</legend>{["critical", "high", "medium", "low"].map((impact) => <Toggle key={impact} label={impact.charAt(0).toUpperCase() + impact.slice(1)} value={(draft.impacts || []).includes(impact)} onChange={(value) => change("impacts", value ? [...(draft.impacts || []), impact] : draft.impacts.filter((i: string) => i !== impact))} />)}</fieldset>
          <Field label="Maximum source age (hours)"><input type="number" min="1" max="168" required value={draft.stale_hours ?? 72} onChange={(e) => change("stale_hours", +e.target.value)} /></Field>
          <button className="primary" disabled={busy || !data}><Save size={16} />Save event windows</button>
          <p role="status" className="muted">{feedback}</p>
        </form>
        <h2>Sources</h2>
        {Object.entries(data?.sources || {}).map(([name, raw]) => { const source = raw as Json; return <div className="economic-source" key={name}><strong>{name.toUpperCase()}</strong><span>{source.updated_at ? ct(source.updated_at) : "Never synchronized"}</span>{source.error && <span className="negative">{source.error}</span>}</div>; })}
        <p className="muted">Impact labels are app classifications, not provider ratings. Source refresh: every 6 hours while the interface service runs. Missing or stale Fed/BEA schedules pause new entries when enabled.</p>
      </aside>
      <div className="economic-agenda">
        <div className="economic-toolbar">
          <Field label="From date (CT)"><input type="date" required value={date} onChange={(e) => setDate(e.target.value || dayCT(new Date().toISOString()))} /></Field>
          <Field label="View"><select value={range} onChange={(e) => setRange(e.target.value)}><option value="1">Day</option><option value="7">Week</option><option value="31">Month</option></select></Field>
          <button type="button" disabled={busy} onClick={async () => { await act("/economic-calendar/refresh", {}); await load(); }}><RefreshCw size={16} />Refresh schedules</button>
        </div>
        <Table heads={["Chicago time", "Event", "Impact", "Entry pause", "Source", ""]} rows={events.map((row: Json) => {
          const critical = row.impact === "critical", before = data?.settings[critical ? "critical_before_minutes" : "before_minutes"] || 0, after = data?.settings[critical ? "critical_after_minutes" : "after_minutes"] || 0;
          return [ct(row.event_at), row.title, <Badge tone={critical || row.impact === "high" ? "warning" : ""}>{row.impact}</Badge>, data?.settings.enabled && data.settings.impacts.includes(row.impact) ? `${before}m before / ${after}m after` : "Monitor only", <a href={row.source_url} target="_blank" rel="noreferrer">{row.source === "manual" ? "Reviewed manual" : row.source.toUpperCase()} <ExternalLink size={12} /></a>, row.source === "manual" ? <button title="Remove manual event" aria-label={"Remove " + row.title} disabled={busy} onClick={() => remove(row.id)}><Trash2 size={14} /></button> : null];
        })} empty="No recorded events in this interval. This does not guarantee a news-free session." />
        <details><summary>Add reviewed event</summary><form className="economic-manual" onSubmit={add}>
          <Field label="Event name"><input required maxLength={200} value={manual.title} onChange={(e) => setManual({ ...manual, title: e.target.value })} /></Field>
          <Field label="Release time (Chicago)"><input type="datetime-local" required value={manual.event_at} onChange={(e) => setManual({ ...manual, event_at: e.target.value })} /></Field>
          <Field label="Impact"><select value={manual.impact} onChange={(e) => setManual({ ...manual, impact: e.target.value })}>{["critical", "high", "medium", "low"].map((i) => <option key={i} value={i}>{i}</option>)}</select></Field>
          <Field label="Official schedule reference"><input type="url" required placeholder="https://" value={manual.source_url} onChange={(e) => setManual({ ...manual, source_url: e.target.value })} /></Field>
          <button disabled={busy}><Plus size={16} />Add event</button>
        </form></details>
      </div>
    </div>
  </section>;
}
