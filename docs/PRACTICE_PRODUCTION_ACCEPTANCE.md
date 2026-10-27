# Practice Production Acceptance

Date: 2026-10-26, America/Chicago.

## Release Scope

Practice-only operation using the existing authorized session and operator-saved
configuration. Leader remains disabled. This acceptance concerns execution and
operational safety, not strategy profitability or guaranteed future availability.
It supersedes the earlier one-MNQ test snapshot in PRACTICE_RELEASE_AUDIT.md;
that document remains a historical record rather than the current configuration.

## Changes

- Reloaded the market/Practice worker and Leader worker (entries disabled) only after
  pausing new entries, verifying both broker accounts flat and confirming no
  unresolved executor jobs. Startup fingerprints now match installed source.
- Restored the exact previously enabled Practice settings and existing session,
  not a fresh authorization with reset balance, baseline, cursor or limits.
- Passive operations checks now include reviewed calendar coverage and actual
  selected micro-contract trade timestamps. A fresh heartbeat alone cannot
  establish either. Calendar evidence warns when review is due within 24 hours.
- Watch-only history is separate from broker-confirmed trades. Its strategy
  wins/losses and dollar estimates use observed signal exits and one micro per
  signal, gross before fees/slippage. Open, cleared, incomplete and broker-derived
  exits are not scored as hypothetical wins/losses. Execution-owned alerts stay
  excluded even when older jobs fall outside the recent-order display limit.
- Alert rejection notes read profile-specific recorded decisions, independent
  of the bounded general event feed. Missing evidence is identified, not guessed.
- Removed the dashboard's 3D renderer, controls and dependencies. The existing
  flat realized-equity chart, statistics and filters remain.

## Preserved Configuration

Before/after comparisons cover both accounts' complete execution settings,
strategy/instrument selections, per-symbol sizing, frozen session policy,
manager/profit policies, strategy parameters and raw saved/active Safeguards
records including revisions. Existing loss baselines remain unchanged.
Credential/configuration file hashes were also compared without publishing
their contents. No test order, risk-limit increase, loss reset or Leader entry
was requested by the release procedure.

The only local operational metadata update is the separately reviewed calendar;
it does not change sizing, strategies, account identity or risk preferences.

## Calendar Coverage

Reviewed coverage ends **2026-11-02 at 16:00 America/Chicago (CST)**, within the
existing seven-day review limit. Daily breaks, the weekend and November 1 DST
transition are represented explicitly. The existing earlier Topstep entry cutoff
and scheduled flatten remain authoritative; calendar coverage cannot extend them.
No automatic calendar extension or holiday inference was introduced.

Sources reviewed on October 26:
[CME 2026 Globex holiday schedule](https://www.cmegroup.com/trading-hours.html)
and [CME Micro E-mini FAQ, trading hours](https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html).
The official holiday schedule has no holiday in the covered interval. The local
calendar remains ignored operational data, not a permanently valid shipped file.

## Verification

- Full isolated regression: **667 tests passed**, zero failures/errors and zero
  unmocked HTTP attempts. This includes entry/exit, partial/unknown outcomes,
  duplicate prevention, ownership/protection, risk limits, cooldowns, schedules,
  reconnect classification, stale worker identity and settings persistence.
- Production TypeScript/Vite build and Python compilation passed. Dependency
  consistency passed; production npm audit reported zero vulnerabilities at
  verification time. This is not a full security certification.
- Native controls browser checks use a disposable database and mocked broker,
  testing both profiles, strategy/symbol switches, sizes, cooldown, save errors,
  reconnect drafts and reload persistence without production configuration writes.
- Full-app browser checks passed across desktop/mobile, including navigation,
  live updates, chart pixels, persistent zoom, pane resizing and authorization
  dialog behavior, with no submitted orders.
- Watch-history browser fixtures verify profile isolation, hypothetical dollar
  arithmetic and exclusion from actual profit. Flat dashboard checks cover five
  screen sizes, negative/empty equity and absence of WebGL assets.
- After reload, passive operations checks passed with the original Practice Run
  intent restored, fresh broker reconciliation, selected-contract data and Leader
  disabled. No market entry was forced to manufacture acceptance evidence.
- Bounded live observation: 13 samples over 120.3 seconds, with saved settings
  unchanged throughout. Twelve samples passed; one correctly flagged selected
  MYM trade data aged 31.19 seconds against the unchanged 30-second readiness
  threshold. Fresh data restored passing status at the next sample without
  restart or operator intervention. No bot entry occurred during this window.
  This was a transient data wait, not bypassed or reported as continuous success.

Private evidence is retained under ignored `data/verification/`, including the
preservation snapshot, full test log, resumed-state report and bounded live
observation. No credentials or raw account identifiers are included in this report.

## Operating Conditions

Keep the machine awake and connected. Broker original stops remain necessary
because a local process cannot manage software exits while the computer is off.
Use the existing Pause/Start and Safeguards Apply workflows for operator changes;
deployment does not unlock losses or bypass uncertain execution outcomes.

Review the calendar before its expiration. Failed identity, stale data, expired
calendar, missing protection or exhausted limits must continue to block entries.
Use Diagnostics > Practice operations to inspect current evidence.

Bounded live observation and mocked failure tests are not a multi-day live outage
or cross-session soak. Continue supervision during initial operation; neither
future fills nor unattended availability are guaranteed by this release.
