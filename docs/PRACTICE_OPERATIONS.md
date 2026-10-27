# Practice Operations

This runbook covers execution reliability, not strategy profitability. Production
Practice is an explicitly authorized Practice-only session, with Leader disabled.
It does not enable copier accounts, broker partial exits or broker stop amendments.

## Before Starting

- Verify the configured Practice account and provider Auto OCO mode. Broker-side
  original stop protection remains necessary even when software manages exits.
- Review saved strategies, per-symbol quantities, intervals, cooldown and active
  Safeguards. Save and Apply remain separate; no deployment changes these values.
- Check Diagnostics > Practice operations. Its heartbeat, source-build, broker
  reconciliation, ownership/protection and cumulative-loss checks must pass.
- Review strategy/data and calendar evidence too. A healthy execution worker does
  not create a signal or override stale quotes, missing candles or calendar gates.
- Practice operations also checks reviewed calendar validity and fresh trade
  timestamps for each selected micro contract while entries and the market are
  open. Review coverage before expiry; it is never automatically extended.
- Keep the computer awake and connected. Browser closure does not stop workers;
  computer shutdown stops software exits. Original broker stops are independent.

## Supervision And Recovery

The Practice feed/monitor/executor now use coalesced post-commit notifications;
periodic watchdogs remain active when no events arrive. Broker reconciliation
retains a two-second minimum cycle-start interval, and error backoff cannot be
interrupted by market events. Manual pause, unknown outcomes and all preflight
checks still win. See [Event-Driven Practice](EVENT_DRIVEN_PRACTICE.md).

Windows process-inspection failures are unknown, not proof of a stopped worker.
Passive status reads never delete PID registrations. Unknown state blocks new
launch/stop actions. Lifecycle commands are serialized; the market worker also
holds an OS lifetime lock so a missing registration cannot create a second loop.
Shutdown verifies worker identity, termination success and process exit before
removing registration. Failed or unconfirmed shutdown retains the registration.

Worker heartbeats include their startup source fingerprint. New entry authorization
and Safeguards Apply reject an older build even if its heartbeat is fresh. An
upgrade does not kill an open trade: pause new entries, verify broker flat and no
unresolved jobs, then restart workers. Resuming requires the existing account
authorization workflow; a generic worker start does not arm either account.

Temporary network/API errors reconnect through the existing executor and preserve
manual Run/Pause intent. Unknown submission/close outcomes are persisted and are
not blindly resent. Identity mismatch, unowned exposure, partial/mismatched fills,
or ambiguous protection require operator review; do not clear their records or
start another session to bypass them. Use the broker to inspect the actual state.

## Operational Acceptance

1. Run the complete isolated regression suite and build the production interface.
2. Check both profiles' saved settings and Safeguards against the pre-rollout
   snapshot; loss baselines and Leader-disabled state must be preserved.
3. Verify the Practice position's actual fill, quantity and linked broker stop.
4. If a deployment close is explicitly authorized, close only the proven bot-owned
   Practice position once. Observe broker flat state, orphan-stop removal, exit
   fills and fees. Never infer a successful close from an HTTP acknowledgement.
5. Restart only after flat verification, then confirm current source fingerprints,
   fresh broker reconciliation and market data, and unchanged saved configuration.
6. Perform a sustained supervised Practice run over session boundaries and provider
   reconnects before treating the deployment as suitable for unattended operation.

Diagnostics is passive evidence, not a certification badge. It cannot test a future
provider outage, guarantee a fill price, reset a loss lock or authorize an order.
Regression tests simulate outages, uncertain outcomes and restarts without causing
real broker failures. Do not deliberately crash exit management with an open trade.

## Unsent Practice Entry Retries

A rejected preflight may be reconsidered only when its durable job record proves
`submission_status=NOT_SENT`, belongs to Practice and has no broker order or fill.
Every attempt reruns the normal signal, freshness, account, schedule and risk checks.
The same alert/event is claimed atomically; retry attempts remain in job history.
Before calling the broker, the worker durably switches to `SENDING`. Submitted,
broker-rejected, uncertain, filled and closed jobs cannot automatically retry.
Older records without this proof are not replayed, and expired signals stay expired.
Leader behavior, saved settings and Safeguards are unchanged by this mechanism.

## Verified Rollout

The latest acceptance record is [Practice Production Acceptance](PRACTICE_PRODUCTION_ACCEPTANCE.md).
The historical rollout below describes its own earlier configuration and tests.

The 2026-10-26 Practice rollout passed 653 isolated regression tests, the production
frontend build and responsive browser checks. The existing bot-owned Practice
position's fill and linked broker stop were verified before an operator-approved
controlled close. Broker flat state, orphan-order removal and the actual exit fill
were verified before worker restart. Both worker source fingerprints matched the
installed build afterward; fresh quotes and passive Practice checks passed.

The original Practice authorization/session and saved settings were restored
exactly. Raw saved/active Safeguards records and revisions, loss baselines and
Leader-disabled settings were compared before and after rollout and preserved.
The running market worker's lifetime lock was also verified to reject a second
instance. No new entry was forced for this rollout. Multi-session unattended soak
and real provider-outage behavior remain ongoing operational validation, not a
claim established by the regression suite or this single controlled close.
