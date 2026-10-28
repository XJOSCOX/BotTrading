# Economic Calendar

Economic Calendar is a scheduled-news overlay for new Practice entries. It does
not flatten positions, change stops, alter sizing/risk budgets, extend signal
expiration, start trading, or change Leader execution. Existing exits keep running.
The overlay is checked by the existing execution schedule, including broker
preflight and the final submission boundary. Historical replay with
`calendar=False` never reads today's event list.

Saved settings select impact levels and minutes before/after releases. Critical
events have independent buffers. Windows include their start and exclude their
end; overlapping active windows use the latest end. Impact ratings are app
classifications, not statements by the publishing agency.

## Coverage

- Fed: official JSON calendar, including dated FOMC meetings, press conferences,
  minutes, speeches and scheduled statistical releases.
- BEA: official release-schedule table with its explicitly declared year.
- Other sources: reviewed manual events with a reference URL and Chicago time.
  CPI, payrolls, PPI, JOLTS, Census, ISM, claims, auctions and earnings are not
  automatically complete. BLS returned HTTP 403 from this machine; do not bypass
  that restriction or imply its feed is synchronized.
- Unscheduled geopolitical/news shocks cannot be guaranteed by a calendar. The
  existing volatility and fresh-price safeguards remain necessary.

Fed/BEA refresh every six hours while the interface service runs, or explicitly
from the calendar page. HTTP never runs inside entry/exit processing. Failed or
empty imports retain the previous source records and its last-success timestamp.
When enabled, missing/stale required Fed/BEA schedules block new entries rather
than implying an empty calendar is safe. The source-age threshold is saved.

Source timestamps use America/New_York and are stored in UTC. The UI displays
America/Chicago with DST conversion. Manual ambiguous/nonexistent local times
are rejected unless an explicit UTC offset is supplied through the API.

## Activation

The page distinguishes saved configuration from a verified, fresh worker build.
Do not reload workers with positions, working orders, or unresolved jobs. Enable
and deploy only under the established fresh broker-flat checks, preserving all
other settings and Run/Pause state. Event settings/events persist in SQLite;
broker trading history and loss baselines are never rewritten.
