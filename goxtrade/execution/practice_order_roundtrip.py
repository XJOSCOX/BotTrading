"""One explicitly approved MNQ Practice round trip, separate from strategy trading."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import math
import re
import time
import uuid

from goxtrade.config import execution_identity as identity
from goxtrade.diagnostics import practice_validation as preflight
from goxtrade.execution import practice_executor as executor, projectx_client as client
from goxtrade.execution.practice_order_store import TestBlocked, TestStore, digest
from goxtrade.execution.practice_test_reviews import account_review, calendar_review, identity_key
from goxtrade.market.market_session import market_session
from goxtrade.market.trading_schedule import execution_schedule
from goxtrade.strategies.overnight_policy import cooldown_seconds


READ_COLLECTIONS = {**preflight.READ_ENDPOINTS, "/api/Order/search":"orders", "/api/Trade/search":"trades"}
TERMINAL = ("COMPLETE", "REJECTED")


def validate_broker_rows(key, rows):
    require(isinstance(rows,list) and all(isinstance(row,dict) for row in rows),"Malformed broker collection")
    if key not in ("positions","orders","trades"):
        return rows
    for row in rows:
        require(type(row.get("id")) is int and row["id"]>0 and type(row.get("accountId")) is int
                and isinstance(row.get("contractId"),str) and type(row.get("size")) is int and row["size"]>0,
                "Broker exposure/fill identifiers or whole-contract quantity are malformed")
        if key=="positions":
            require(type(row.get("type")) is int and row["type"] in (1,2),"Broker position direction is malformed")
        else:
            require(type(row.get("side")) is int and row["side"] in (0,1),"Broker order/trade side is malformed")
        if key=="orders":
            require(type(row.get("type")) is int and type(row.get("status")) is int,"Broker order type/status is malformed")
            if row.get("fillVolume") is not None:
                require(type(row["fillVolume"]) is int and row["fillVolume"]>=0,"Broker fill volume is malformed")
        if key=="trades":
            require(type(row.get("orderId")) is int and row["orderId"]>0 and type(row.get("voided")) is bool,"Broker trade ownership/voiding status is malformed")
    return rows


class PracticeBroker:
    def __init__(self, store=None, clock=None):
        self.token = None
        self.store = store or TestStore()
        self.clock = clock or (lambda:datetime.now(timezone.utc))

    def authenticate(self):
        broker = preflight.ReadOnlyBroker()
        if not broker.authenticate():
            raise TestBlocked("ProjectX authentication unavailable; no order sent")
        self.token = broker.token

    def read(self, path, payload):
        if path not in READ_COLLECTIONS or not self.token:
            raise TestBlocked("Read-only broker route or authentication invalid")
        try:
            response = client.post(path, payload, token=self.token)
            if not valid_ack(response):
                raise TestBlocked("Broker read rejected or malformed")
            rows = response.get(READ_COLLECTIONS[path])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise TestBlocked("Broker collection unavailable; do not infer flat state")
            if "accountId" in payload and any(row.get("accountId") != payload["accountId"] for row in rows):
                raise TestBlocked("Broker account response mismatch")
            return validate_broker_rows(READ_COLLECTIONS[path],rows)
        except TestBlocked:
            raise
        except Exception:
            raise TestBlocked("Broker read unavailable; reconcile before another action") from None

    def enter(self, payload):
        targets=identity.current_targets()
        require(identity.PROFILE=="practice" and executor.PROFILE=="practice" and self.token,
                "Practice-only authenticated transport required")
        require(payload.get("accountId")==targets["practice"]["id"]!=targets["leader"]["id"]
                and payload.get("type")==2 and type(payload.get("size")) is int and payload["size"]==1,
                "Transport refuses another account, type or quantity")
        stop=payload.get("stopLossBracket")
        require(isinstance(payload.get("contractId"),str) and re.fullmatch(r"CON\.F\.US\.MNQ\.[HMUZ][0-9]{2}",payload["contractId"])
                and type(payload.get("side")) is int and payload["side"] in (0,1)
                and isinstance(stop,dict) and stop.get("type")==4 and type(stop.get("ticks")) is int
                and abs(stop["ticks"])>=6 and (stop["ticks"]<0)==(payload["side"]==0)
                and "takeProfitBracket" not in payload,"Transport requires one protected MNQ market entry, never an unprotected or experimental order")
        tag=payload.get("customTag","")
        require(isinstance(tag,str) and tag.startswith("gx-practice-validation-"),"Missing exact test tag")
        identifier=tag.removeprefix("gx-practice-validation-")
        with self.store.transaction() as conn:
            row=conn.execute("SELECT record FROM practice_order_tests WHERE id=?",(identifier,)).fetchone()
            record=json.loads(row[0]) if row else {}
            require(record.get("state")=="SENDING" and not record.get("wire_started_at") and record.get("payload_digest")==digest(payload),
                    "Entry transmission already attempted or lacks exact durable approval")
            require(self.clock()<stamp(record["proposal"]["expires_at"]),"Entry approval expired before transmission")
            require(record["proposal"]["identity_key"]==identity_key(targets),"Approved identity changed at transport")
            record["wire_started_at"]=datetime.now(timezone.utc).isoformat()
            self.store.save(conn,record)
        return client.post("/api/Order/place", payload, token=self.token)

    def close(self, job):
        require(identity.PROFILE=="practice" and executor.PROFILE=="practice" and self.token,"Practice-only authenticated close required")
        with self.store.transaction() as conn:
            row=conn.execute("SELECT record FROM practice_order_tests WHERE id=?",(job.get("validation_test_id"),)).fetchone()
            record=json.loads(row[0]) if row else {}
            require(record.get("state")=="CLOSE_INTENT" and not record.get("close_wire_started_at"),"Close transmission already attempted or not approved")
            require(self.clock()<stamp(record["close_proposal"]["expires_at"]),"Close approval expired before transmission")
            p=record["proposal"]
            require(p["identity_key"]==identity_key(identity.current_targets()) and job.get("account_id")==p["account_id"]==executor.ACCOUNT_ID
                    and job.get("contract_id")==p["contract_id"] and job.get("quantity")==1,"Close ownership/account mismatch")
            record["close_wire_started_at"]=datetime.now(timezone.utc).isoformat()
            self.store.save(conn,record)
        # Existing exact-account full-close route persists Closing before transmission.
        executor.close_job(job, self.token)


def valid_ack(response):
    return (isinstance(response, dict) and response.get("success") is True
            and type(response.get("errorCode")) is int and response["errorCode"] == 0)


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise TestBlocked("Missing or malformed timestamp") from None


def require(value, message):
    if not value:
        raise TestBlocked(message)


def grid(value):
    return preflight.finite(value) and value > 0 and abs(value/.25-round(value/.25)) < 1e-7


def working_signature(orders):
    require(all(type(order.get("id")) is int for order in orders),"Working order identifiers are incomplete")
    fields=("id","contractId","parentOrderId","type","side","size","stopPrice","status")
    return [{key:order.get(key) for key in fields} for order in sorted(orders,key=lambda row:row["id"])]


class PracticeRoundTrip:
    def __init__(self, store=None, broker=None, clock=None):
        self.store = store or TestStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.broker = broker or PracticeBroker(self.store,self.clock)

    def exact_account(self, record=None):
        require(identity.PROFILE == "practice" and executor.PROFILE == "practice", "Practice process only; Leader is excluded")
        targets = identity.current_targets()
        require(executor.ACCOUNT_ID == targets["practice"]["id"] and executor.ACCOUNT_NAME == targets["practice"]["name"],
                "Account configuration changed; this process cannot submit or close")
        if record:
            require(record["proposal"]["identity_key"] == identity_key(targets), "Approved account identity changed; no account fallback")
        self.broker.authenticate()
        account = preflight.exact_practice(self.broker.read("/api/Account/search", {"onlyActiveAccounts":False}), targets)
        return targets, account

    def context(self, own_test=None):
        now = self.clock()
        targets = identity.current_targets()
        reviewed = account_review(self.store, targets, now)
        calendar = calendar_review(self.store, now)
        targets, account = self.exact_account()
        state = preflight.local_state(targets)
        require(all(p["settings"].get("enabled") is False for p in state["profiles"].values()), "Pause Practice and Leader entries; test never changes permissions")
        jobs = []
        for profile, values in state["profiles"].items():
            for job in values["jobs"]:
                if own_test and profile == "practice" and job.get("validation_test_id") == own_test:
                    continue
                require(job.get("state") in ("Closed", "Rejected"), "Unresolved bot/test job; reconcile before submission")
                if profile == "practice":
                    jobs.append(job)
        gate = state["gate"] or {}
        require(gate.get("account_id") == targets["practice"]["gate_id"] and gate.get("locked") is False
                and preflight.finite(gate.get("baseline")), "Existing $500 loss gate is unavailable or locked; never reset it for a test")
        remaining = 500-max(0,gate["baseline"]-account["balance"])
        require(remaining > 0, "Account loss limit reached")
        settings = state["profiles"]["practice"]["settings"]
        start, limit = settings.get("start_balance"), settings.get("max_run_loss")
        require(preflight.finite(start) and preflight.finite(limit) and limit > 0, "Existing run-loss gate is unavailable")
        remaining = min(remaining, limit-max(0,start-account["balance"]))
        require(remaining > 0 and not settings.get("emergency_close"), "Run-loss or emergency gate blocks a new test")
        policy = state["policy"]
        delay = policy.get("cooldown_minutes",5)
        require(type(delay) is int and 1 <= delay <= 60, "Configured cooldown is invalid")
        delay = cooldown_seconds(delay*60,now)
        last_close = max((stamp(j["closed_confirmed_at"]).timestamp() for j in jobs if j.get("closed_confirmed_at")),default=0)
        require(now.timestamp() >= last_close+delay, "Existing post-trade cooldown has not elapsed")
        schedule = execution_schedule(now)
        require(market_session(now)["is_open"] and schedule["allow_entry"] and not schedule["flatten"], "Market or existing Topstep execution window is closed")
        contract = preflight.active_mnq(self.broker.read("/api/Contract/search", {"searchText":"MNQ","live":False}))
        # Read prices again after authenticated discovery; older reference timestamps never authorize entry.
        state = preflight.local_state(targets)
        quote, trade = state["quote"] or {}, state["trade"] or {}
        now = self.clock()
        for row in (quote,trade):
            require(row.get("contract_id") == contract["id"] and preflight.fresh(row.get("event_time"),now)
                    and preflight.fresh(row.get("received_at"),now), "MNQ quote/trade is stale, future-dated or on another contract")
        bid, ask = quote.get("best_bid"), quote.get("best_ask")
        require(grid(bid) and grid(ask) and 0 < ask-bid <= .5 and grid(trade.get("price")), "MNQ bid/ask spread or tick grid is unacceptable")
        positions = self.broker.read("/api/Position/searchOpen", {"accountId":account["id"]})
        orders = self.broker.read("/api/Order/searchOpen", {"accountId":account["id"]})
        require(not positions and not orders, "Practice account is not flat or has working orders; do not close them automatically")
        return dict(account_id=account["id"],account_name=account["name"],identity_key=identity_key(targets),contract=contract,
                    bid=bid,ask=ask,price=trade["price"],quote_time=quote["event_time"],remaining=remaining,
                    review_key=digest(reviewed),calendar_key=digest(calendar),now=now)

    def propose(self, side, stop_ticks, commission_per_side, slippage_ticks, max_risk):
        require(side in ("BUY","SELL"), "Choose BUY or SELL explicitly; no strategy chooses the test side")
        require(type(stop_ticks) is int and 6 <= stop_ticks <= 10000, "Stop must be at least 6 whole ticks under the documented conservative Topstep bracket minimum")
        require(preflight.finite(commission_per_side) and commission_per_side > 0, "Provide a positive estimated commission per side")
        require(type(slippage_ticks) is int and 0 <= slippage_ticks <= 20, "Provide a bounded whole-tick slippage estimate")
        require(preflight.finite(max_risk) and max_risk > 0, "Provide an explicit planned-risk cap")
        context = self.context()
        planned = stop_ticks*.5+commission_per_side*2+slippage_ticks
        require(planned <= min(max_risk,context["remaining"]), "Planned stop risk plus costs exceeds the approved or existing account/run budget")
        reference = context["ask"] if side == "BUY" else context["bid"]
        identifier = uuid.uuid4().hex
        proposal = dict(profile="practice",account_id=context["account_id"],account_name=context["account_name"],
            identity_key=context["identity_key"],review_key=context["review_key"],calendar_key=context["calendar_key"],
            symbol="MNQ",contract_id=context["contract"]["id"],side=side,quantity=1,type=2,
            reference=reference,bid=context["bid"],ask=context["ask"],quote_time=context["quote_time"],
            stop_ticks=stop_ticks,reference_stop=reference+(-1 if side == "BUY" else 1)*stop_ticks*.25,
            estimated_commission_per_side=commission_per_side,slippage_ticks=slippage_ticks,
            planned_risk_usd=planned,max_risk_usd=max_risk,
            expires_at=(context["now"]+timedelta(seconds=45)).isoformat(),leader_excluded=True,
            price_condition="Current bid/ask must remain within the approved slippage band; spread at most two ticks",
            warning="Market fills and stop fills can exceed estimates. Stop is a fixed tick distance from actual fill, not a guaranteed absolute price.")
        record = dict(id=identifier,state="PROPOSED",proposal=proposal,proposal_digest=digest(proposal),created_at=context["now"].isoformat(),
                      alert_id=-int(identifier[:13],16),tag="gx-practice-validation-"+identifier)
        self.store.create(record)
        return record

    def load(self, identifier):
        record = self.store.read(identifier)
        require(record is not None, "Unknown test identifier; never discover or substitute another account/test")
        require(digest(record["proposal"]) == record["proposal_digest"], "Proposal was modified; authorization invalid")
        return record

    def validate_context(self, record, context):
        p=record["proposal"]
        require(self.clock() < stamp(p["expires_at"]), "Proposal expired; request a new proposal and approval")
        require(context["identity_key"] == p["identity_key"] and context["account_id"] == p["account_id"], "Account changed after proposal")
        require(context["contract"]["id"] == p["contract_id"], "Active contract changed; fresh proposal required")
        require(context["review_key"] == p["review_key"] and context["calendar_key"] == p["calendar_key"], "Evidence/calendar review changed; fresh proposal required")
        band=p["slippage_ticks"]*.25
        require(abs(context["bid"]-p["bid"]) <= band and abs(context["ask"]-p["ask"]) <= band, "Approved price conditions changed; fresh proposal required")
        require(p["planned_risk_usd"] <= min(p["max_risk_usd"],context["remaining"]), "Existing loss budget changed; submission blocked")

    def submit(self, identifier, confirm):
        record=self.load(identifier)
        require(record["state"] == "PROPOSED", "Entry authorization was already consumed; reconcile, never resubmit")
        self.validate_context(record,self.context())
        require(confirm(record["proposal"],"ENTER "+identifier), "Specific entry approval was not given")
        context=self.context()
        self.validate_context(record,context)
        p=record["proposal"]
        payload=executor.build_order(dict(id=record["alert_id"],symbol="NQ=F",signal="LONG" if p["side"]=="BUY" else "SHORT",
            entry=p["reference"],stop=p["reference_stop"]),context["contract"],1)
        require(payload["accountId"]==p["account_id"] and payload["size"]==1 and payload["type"]==2
                and payload["side"]==(0 if p["side"]=="BUY" else 1) and payload.get("stopLossBracket")==dict(type=4,ticks=-p["stop_ticks"] if p["side"]=="BUY" else p["stop_ticks"]), "Existing builder returned an unexpected account, side, quantity or stop")
        payload["customTag"]=record["tag"]
        self.reserve(record,payload)
        try:
            self.validate_context(record,self.context(own_test=identifier))
        except Exception:
            self.store.update(identifier,("INTENT",),state="RECHECK_BLOCKED",reason="Final preflight changed after reservation; no transmission. Reconciliation required.")
            raise TestBlocked("Final preflight changed; intent retained and no order transmitted") from None
        started=time.perf_counter()
        self.store.update(identifier,("INTENT",),state="SENDING")
        try:
            response=self.broker.enter(payload)
            order_id=response.get("orderId") if isinstance(response,dict) and type(response.get("orderId")) is int and response["orderId"]>0 else None
            state="ACKNOWLEDGED" if valid_ack(response) and order_id else "ACK_REJECTED" if isinstance(response,dict) and response.get("success") is False else "SUBMISSION_UNKNOWN"
            code=response.get("errorCode") if isinstance(response,dict) and type(response.get("errorCode")) is int else None
            return self.store.update(identifier,("SENDING",),state=state,order_id=order_id,provider_code=code,
                acknowledged_at=self.clock().isoformat(),acknowledgment_ms=round((time.perf_counter()-started)*1000,2))
        except Exception:
            self.store.update(identifier,("SENDING",),state="SUBMISSION_UNKNOWN",reason="Entry outcome unknown; never retry. Query broker orders and trades.")
            raise TestBlocked("Entry outcome unknown. Durable intent retained; use status/reconciliation, not submit") from None

    def reserve(self, record, payload):
        # The production Intent reserves the account for this explicit test. The
        # existing strategy worker treats Intent as uncertain and never submits it.
        with self.store.transaction() as conn:
            require(identity_key(identity.current_targets())==record["proposal"]["identity_key"],"Account changed before durable intent")
            row=conn.execute("SELECT state FROM practice_order_tests WHERE id=?",(record["id"],)).fetchone()
            require(row and row[0]=="PROPOSED", "Authorization already consumed by another process")
            require(not conn.execute("SELECT 1 FROM practice_order_tests WHERE id<>? AND state NOT IN ('PROPOSED','COMPLETE','REJECTED')",(record["id"],)).fetchone(), "Another test has an unresolved durable intent")
            for profile in ("practice","leader"):
                control=conn.execute(f"SELECT settings FROM {profile}_control WHERE id=1").fetchone()
                require(control and json.loads(control[0]).get("enabled") is False, "Execution permission changed; entry reservation blocked")
                for row in conn.execute(f"SELECT record FROM {profile}_jobs"):
                    require(json.loads(row[0]).get("state") in ("Closed","Rejected"), "Another bot order is unresolved")
            job=dict(alert_id=record["alert_id"],state="Intent",validation_test_id=record["id"],account_id=payload["accountId"],symbol="MNQ",
                     contract_id=payload["contractId"],side=payload["side"],quantity=1,sent_at=time.time(),signal_entry=record["proposal"]["reference"])
            conn.execute("INSERT INTO practice_jobs VALUES (?,?)",(job["alert_id"],json.dumps(job)))
            record.update(state="INTENT",entry_approved_at=self.clock().isoformat(),payload_digest=digest(payload))
            self.store.save(conn,record)

    def history(self, record):
        targets,account=self.exact_account(record)
        p=record["proposal"]
        payload=dict(accountId=account["id"],startTimestamp=record["created_at"],endTimestamp=self.clock().isoformat())
        positions=self.broker.read("/api/Position/searchOpen",{"accountId":account["id"]})
        working=self.broker.read("/api/Order/searchOpen",{"accountId":account["id"]})
        orders=self.broker.read("/api/Order/search",payload)
        trades=self.broker.read("/api/Trade/search",payload)
        for key,rows in (("positions",positions),("orders",working),("orders",orders),("trades",trades)):
            validate_broker_rows(key,rows)
        require(all(t.get("voided") in (True,False) and type(t.get("voided")) is bool for t in trades), "Trade voiding status unavailable")
        return positions,working,orders,[t for t in trades if t["voided"] is False]

    def reconcile(self, identifier):
        record=self.load(identifier)
        require(record["state"]!="PROPOSED", "No entry intent exists; proposal is not a broker trade")
        started=time.perf_counter()
        positions,working,orders,trades=self.history(record)
        p=record["proposal"]; side=0 if p["side"]=="BUY" else 1
        entries=[o for o in orders if o.get("customTag")==record["tag"] and o.get("accountId")==p["account_id"]
                 and o.get("contractId")==p["contract_id"] and o.get("side")==side and o.get("size")==1 and o.get("type")==2]
        require(len(entries)<=1,"Ambiguous broker entry ownership; manual review required")
        changes=dict(reconciled_at=self.clock().isoformat(),reconciliation_ms=round((time.perf_counter()-started)*1000,2),position_count=len(positions),working_order_count=len(working))
        if not entries:
            return self.store.update(identifier,(record["state"],),**changes,reason="Entry order not found by its exact unique tag; no fill or retry inferred")
        entry=entries[0]; order_id=entry.get("id")
        require(type(order_id) is int and (record.get("order_id") is None or order_id==record["order_id"]),"Acknowledgment and discovered order disagree")
        fills=[t for t in trades if t.get("orderId")==order_id]
        if not fills:
            if entry.get("status")==5 and type(entry.get("fillVolume")) is int and entry["fillVolume"]==0 and not positions and not working:
                result=self.store.update(identifier,(record["state"],),**changes,order_id=order_id,state="REJECTED",reason="Broker order explicitly rejected with zero fill and flat/clear state")
                self.release(record,"Rejected",dict(order_id=order_id))
                return result
            return self.store.update(identifier,(record["state"],),**changes,order_id=order_id,reason="No confirmed entry fill; account remains reserved")
        require(len(fills)==1 and type(fills[0].get("size")) is int and fills[0]["size"]==1 and fills[0].get("side")==side and fills[0].get("contractId")==p["contract_id"]
                and grid(fills[0].get("price")) and entry.get("status")==2 and entry.get("fillVolume")==1,
                "Partial, malformed or mismatched entry fill; no automatic close/retry")
        fill=fills[0]
        require(stamp(record["created_at"])<=stamp(fill.get("creationTimestamp"))<=self.clock(),"Entry fill timestamp is inconsistent; reconcile again without resubmitting")
        changes.update(order_id=order_id,entry_fill=fill["price"],entry_time=fill["creationTimestamp"],entry_trade_id=fill.get("id"),
                       entry_fees=fill.get("fees") if preflight.finite(fill.get("fees")) else None,
                       slippage_points=(fill["price"]-p["reference"])*(1 if side==0 else -1))
        changes["slippage_classification"]="ADVERSE" if changes["slippage_points"]>0 else "FAVORABLE" if changes["slippage_points"]<0 else "NONE"
        if positions:
            require(len(positions)==1 and positions[0].get("contractId")==p["contract_id"] and positions[0].get("type")==side+1
                    and positions[0].get("size")==1 and grid(positions[0].get("averagePrice"))
                    and abs(positions[0]["averagePrice"]-fill["price"])<1e-7,"Unowned or partial/mismatched broker position; operator review required")
            job=dict(symbol="MNQ",contract_id=p["contract_id"],order_id=order_id,side=side,quantity=1)
            stops=[o for o in working if type(o.get("size")) is int and type(o.get("side")) is int and executor.protective_order(o,job) and o.get("status")==1]
            expected_stop=fill["price"]+(-1 if side==0 else 1)*p["stop_ticks"]*.25
            protected=len(stops)==1 and abs(stops[0]["stopPrice"]-expected_stop)<1e-7 and len(working)==1
            state="CLOSING" if record.get("close_intent_at") else "PROTECTED" if protected else "UNSAFE"
            changes.update(state=state,protection="CONFIRMED" if protected else "MISSING_OR_UNVERIFIABLE",
                stop_price=stops[0]["stopPrice"] if len(stops)==1 else None,
                reason="Broker stop verified" if protected else "UNSAFE: required owned stop not confirmed. Promptly request an explicitly approved emergency full close or use Topstep directly.")
            return self.store.update(identifier,(record["state"],),**changes)
        exits=[]
        for trade in trades:
            if trade.get("side")!=1-side or trade.get("size")!=1 or trade.get("contractId")!=p["contract_id"] or not grid(trade.get("price")):
                continue
            order=next((o for o in orders if o.get("id")==trade.get("orderId") and o.get("status")==2 and o.get("fillVolume")==1),None)
            stop_exit=order and order.get("parentOrderId")==order_id and order.get("type")==4
            approved_exit=(record.get("close_intent_at") and order and order.get("type")==2
                           and order.get("id") not in record.get("known_order_ids",[])
                           and stamp(trade.get("creationTimestamp"))>=stamp(record["close_intent_at"]))
            if stop_exit or approved_exit:
                require(stamp(fill["creationTimestamp"])<=stamp(trade.get("creationTimestamp"))<=self.clock(),"Exit timestamp is inconsistent; do not infer a completed round trip")
                exits.append(trade)
        if len(exits)!=1 or working:
            changes.update(state="FLAT_RECONCILIATION_PENDING",reason="Flat observed, but unique exit fill or clean order state not verified; do not repeat close or cancel unrelated orders")
            return self.store.update(identifier,(record["state"],),**changes)
        exit=exits[0]
        pnl=exit.get("profitAndLoss")
        changes.update(exit_fill=exit["price"],exit_time=exit["creationTimestamp"],exit_order_id=exit["orderId"],
                       realized_pnl=pnl if preflight.finite(pnl) else None,
                       fees=changes["entry_fees"]+exit["fees"] if changes["entry_fees"] is not None and preflight.finite(exit.get("fees")) else None)
        if not preflight.finite(pnl):
            return self.store.update(identifier,(record["state"],),**changes,state="FLAT_RECONCILIATION_PENDING",reason="Broker realized P&L not reported; no value fabricated")
        changes.update(state="COMPLETE",flat_confirmed_at=self.clock().isoformat(),reason="Actual entry/exit fills, broker flat state and zero residual orders confirmed")
        result=self.store.update(identifier,(record["state"],),**changes)
        self.release(record,"Closed",changes)
        return result

    def close_proposal(self, identifier, emergency=False):
        record=self.reconcile(identifier)
        require(record["state"] in ("PROTECTED","UNSAFE"),"Only a reconciled owned open position can receive a close proposal")
        require(record["state"]=="PROTECTED" or emergency is True,"Protection is unverified: explicitly request emergency close, not a normal test close")
        require(not record.get("close_intent_at"),"A close intent already exists; reconcile instead of retrying")
        positions,working,orders,trades=self.history(record)
        self.owned_position(record,positions)
        require(all(o.get("contractId")==record["proposal"]["contract_id"] for o in working),"Unrelated working orders require operator review")
        proposal=dict(test_id=identifier,account_id=record["proposal"]["account_id"],contract_id=record["proposal"]["contract_id"],quantity=1,
                      direction=record["proposal"]["side"],entry_fill=record["entry_fill"],emergency=emergency,
                      working_order_ids=sorted(o["id"] for o in working),working_orders=working_signature(working),
                      expires_at=(self.clock()+timedelta(seconds=45)).isoformat())
        return self.store.update(identifier,(record["state"],),close_proposal=proposal,close_digest=digest(proposal))

    def close(self, identifier, confirm):
        record=self.load(identifier)
        proposal=record.get("close_proposal")
        require(proposal and digest(proposal)==record.get("close_digest"),"Create and review a separate full-close proposal first")
        require(self.clock()<stamp(proposal["expires_at"]),"Close proposal expired; fresh separate approval required")
        require(not record.get("close_intent_at"),"Close authorization already consumed; never repeat an uncertain close")
        require(confirm(proposal,("EMERGENCY CLOSE " if proposal["emergency"] else "CLOSE ")+identifier),"Separate full-close approval was not given")
        current=self.reconcile(identifier)
        require(current["state"] in ("PROTECTED","UNSAFE") and (current["state"]=="PROTECTED" or proposal["emergency"]),"Position/protection changed; no close transmitted")
        require(self.clock()<stamp(proposal["expires_at"]),"Close approval expired during recheck")
        positions,working,orders,trades=self.history(current)
        self.owned_position(current,positions)
        require(working_signature(working)==proposal["working_orders"],"Working orders changed after close proposal; approve a fresh proposal")
        with self.store.transaction() as conn:
            require(self.clock()<stamp(proposal["expires_at"]),"Close proposal expired before durable intent")
            live=json.loads(conn.execute("SELECT record FROM practice_order_tests WHERE id=?",(identifier,)).fetchone()[0])
            require(not live.get("close_intent_at") and live["state"] in ("PROTECTED","UNSAFE"),"Close already claimed concurrently")
            live.update(state="CLOSE_INTENT",close_intent_at=self.clock().isoformat(),known_order_ids=[o["id"] for o in orders])
            self.store.save(conn,live)
            row=conn.execute("SELECT record FROM practice_jobs WHERE alert_id=?",(live["alert_id"],)).fetchone()
            job=json.loads(row[0]) if row else {}
            require(job.get("validation_test_id")==identifier and job.get("state")=="Intent","Production reservation changed; manual reconciliation required")
        # The legacy worker only sees Intent until this already-approved close;
        # then close_job changes it to Closing, whose existing path never resends.
        job.update(order_id=current["order_id"],fill_price=current["entry_fill"],close_time=time.time(),close_reason="Explicit Practice test full close")
        started=time.perf_counter()
        try:
            self.broker.close(job)
            return self.store.update(identifier,("CLOSE_INTENT",),state="CLOSING",close_acknowledgment_ms=round((time.perf_counter()-started)*1000,2))
        except Exception:
            self.store.update(identifier,("CLOSE_INTENT",),state="CLOSE_UNKNOWN",reason="Full-close outcome unknown; reconcile, never resend")
            raise TestBlocked("Close outcome unknown; durable intent retained. Reconcile or review Topstep, never resend blindly") from None

    def release(self, record, state, changes):
        # Release only our reservation after independent broker evidence is final.
        with self.store.transaction() as conn:
            row=conn.execute("SELECT record FROM practice_jobs WHERE alert_id=?",(record["alert_id"],)).fetchone()
            job=json.loads(row[0]) if row else {}
            require(job.get("validation_test_id")==record["id"],"Reservation ownership lost; manual review required")
            job.update(state=state,fill_price=changes.get("entry_fill"),order_id=changes.get("order_id"),
                       closed_confirmed_at=changes.get("flat_confirmed_at"))
            conn.execute("UPDATE practice_jobs SET record=? WHERE alert_id=?",(json.dumps(job),record["alert_id"]))

    @staticmethod
    def owned_position(record,positions):
        p=record["proposal"]
        require(len(positions)==1 and positions[0].get("accountId")==p["account_id"]
                and positions[0].get("contractId")==p["contract_id"] and type(positions[0].get("size")) is int and positions[0]["size"]==1
                and positions[0].get("type")== (1 if p["side"]=="BUY" else 2)
                and grid(positions[0].get("averagePrice")) and abs(positions[0]["averagePrice"]-record["entry_fill"])<1e-7,
                "Position changed after reconciliation; do not close unrelated/partial exposure")
