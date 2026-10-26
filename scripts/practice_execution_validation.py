"""Explicit read-only broker validation. Imports and test discovery perform no requests."""
import argparse
import json
from goxtrade.diagnostics.practice_validation import collect, write_evidence
from goxtrade.paths import DATA_DIR


def main(argv=None):
    parser = argparse.ArgumentParser(description="Practice preflight only; no order submission, arming, closes or risk resets.")
    parser.add_argument("--request-order", action="store_true", help="Check readiness for a future approved test; never submits an order")
    parser.add_argument("--output", default=str(DATA_DIR/"verification"/"practice-execution-readonly.json"))
    args = parser.parse_args(argv)
    report = collect()
    write_evidence(report, args.output)
    print(json.dumps(report, indent=2))
    if args.request_order:
        print("BLOCKED: no order transport is enabled by this validation command. Independent Practice category, verified bracket mode, and specific entry/close approvals are required.")
        return 2
    return 0 if report["outcome"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
