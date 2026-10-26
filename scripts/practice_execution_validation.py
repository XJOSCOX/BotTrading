"""Explicit read-only broker validation. Imports and test discovery perform no requests."""
import argparse
import json
import getpass
import sys
import time
from goxtrade.diagnostics.practice_validation import collect, write_evidence, Blocked
from goxtrade.paths import DATA_DIR


def main(argv=None):
    parser = argparse.ArgumentParser(description="Default: read-only Practice preflight. Mutating test modes require exact evidence and fresh interactive order approvals.")
    parser.add_argument("--request-order", action="store_true", help="Check readiness for a future approved test; never submits an order")
    parser.add_argument("--output", default=str(DATA_DIR/"verification"/"practice-execution-readonly.json"))
    parser.add_argument("--mode", choices=("review-account","review-calendar","readiness","propose","submit","status","monitor","close-proposal","emergency-close-proposal","close"))
    parser.add_argument("--account-evidence")
    parser.add_argument("--oco-evidence")
    parser.add_argument("--provider-url", default="https://www.topstepx.com/trade")
    parser.add_argument("--calendar")
    parser.add_argument("--test-id")
    parser.add_argument("--side", choices=("BUY","SELL"))
    parser.add_argument("--stop-ticks", type=int)
    parser.add_argument("--commission-per-side", type=float)
    parser.add_argument("--slippage-ticks", type=int)
    parser.add_argument("--max-risk", type=float)
    parser.add_argument("--seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if args.mode:
        if args.request_order:
            parser.error("--request-order is read-only and cannot be combined with a test mode")
        return controlled(args, parser)
    report = collect()
    write_evidence(report, args.output)
    print(json.dumps(report, indent=2))
    if args.request_order:
        print("BLOCKED: no order transport is enabled by this validation command. Independent Practice category, verified bracket mode, and specific entry/close approvals are required.")
        return 2
    return 0 if report["outcome"] == "READY" else 2


def confirm(summary, phrase):
    # Approval text is read without echo and is never persisted or exported.
    from goxtrade.execution.practice_order_store import TestBlocked
    if not sys.stdin.isatty():
        raise TestBlocked("Use an interactive operator terminal for approval; no --yes/approval-in-arguments bypass exists")
    print(json.dumps(summary,indent=2,default=str))
    print("Inspect every field above. To approve ONLY this action, type: "+phrase)
    return getpass.getpass("Approval (not echoed): ").strip()==phrase


def safe_report(record):
    allowed=("id","state","created_at","reason","order_id","provider_code","acknowledgment_ms","reconciliation_ms",
             "entry_fill","entry_time","entry_fees","slippage_points","slippage_classification","protection","stop_price","position_count","working_order_count",
             "close_intent_at","close_acknowledgment_ms","exit_fill","exit_time","exit_order_id","realized_pnl","fees","flat_confirmed_at")
    result={key:record[key] for key in allowed if key in record}
    result.update(scope="CONTROLLED_PRACTICE_TEST",account="designated_practice",leader_excluded=True)
    if record.get("proposal"):
        result["proposal"]={k:v for k,v in record["proposal"].items() if k not in ("account_id","account_name","identity_key","review_key","calendar_key")}
    return result


def controlled(args, parser):
    from datetime import datetime,timezone
    from goxtrade.execution.practice_order_roundtrip import PracticeRoundTrip
    from goxtrade.execution.practice_test_reviews import review_account,review_calendar,evidence
    from goxtrade.execution.practice_order_store import TestBlocked
    workflow=PracticeRoundTrip()
    def required(*names):
        if any(getattr(args,name) is None for name in names):
            parser.error("Required for this mode: "+", ".join("--"+n.replace("_","-") for n in names))
    try:
        if args.mode=="review-account":
            required("account_evidence","oco_evidence")
            a=evidence(args.account_evidence,args.provider_url)
            o=evidence(args.oco_evidence,args.provider_url)
            workflow.broker.authenticate()
            result=review_account(workflow.store,workflow.broker,a,o,confirm,datetime.now(timezone.utc))
        elif args.mode=="review-calendar":
            required("calendar")
            result=review_calendar(workflow.store,args.calendar,confirm,datetime.now(timezone.utc))
        elif args.mode=="readiness":
            context=workflow.context()
            result=dict(scope="CONTROLLED_PRACTICE_PREFLIGHT",state="READY_FOR_PROPOSAL",profile="practice",
                contract=context["contract"]["id"],quote_time=context["quote_time"],operator_reviews="VERIFIED_PROVIDER_EVIDENCE",
                flat=True,working_orders=0,leader_excluded=True,orders_submitted=0)
        elif args.mode=="propose":
            required("side","stop_ticks","commission_per_side","slippage_ticks","max_risk")
            record=workflow.propose(args.side,args.stop_ticks,args.commission_per_side,args.slippage_ticks,args.max_risk)
            # Exact identity is displayed privately for this explicit operator proposal, never exported by status.
            print(json.dumps(dict(test_id=record["id"],proposal=record["proposal"]),indent=2))
            return 0
        else:
            required("test_id")
            if args.mode=="submit":
                result=safe_report(workflow.submit(args.test_id,confirm))
            elif args.mode in ("close-proposal","emergency-close-proposal"):
                record=workflow.close_proposal(args.test_id,args.mode=="emergency-close-proposal")
                print(json.dumps(dict(test_id=record["id"],close_proposal=record["close_proposal"]),indent=2))
                return 0
            elif args.mode=="close":
                result=safe_report(workflow.close(args.test_id,confirm))
            elif args.mode=="monitor":
                if not 1<=args.seconds<=120:
                    parser.error("Monitor duration must be 1..120 seconds")
                deadline=time.monotonic()+args.seconds
                while time.monotonic()<deadline:
                    result=safe_report(workflow.reconcile(args.test_id))
                    print(json.dumps(result,indent=2),flush=True)
                    if result["state"] in ("COMPLETE","REJECTED","UNSAFE"):
                        return 0 if result["state"]!="UNSAFE" else 2
                    time.sleep(min(1,max(0,deadline-time.monotonic())))
                return 2
            else:
                record=workflow.load(args.test_id)
                result=safe_report(record if record["state"]=="PROPOSED" else workflow.reconcile(args.test_id))
        print(json.dumps(result,indent=2,default=str))
        return 0
    except (TestBlocked,Blocked) as error:
        print("BLOCKED: "+str(error))
        return 2
    except Exception:
        print("BLOCKED: validation unavailable or broker outcome uncertain. Inspect durable status and provider positions; do not retry a submission.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
