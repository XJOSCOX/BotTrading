"""Read every tracked source/config/doc and print a reproducible static audit inventory.

No imports of application modules, credentials, network calls or file writes.
This is static evidence, not a claim of line/branch coverage or a security proof.
"""
import ast
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVIEW = {"goxtrade/execution/practice_executor.py", "goxtrade/strategies/adaptive_exit.py", "goxtrade/strategies/stop_policy.py",
          "goxtrade/bot/signal_lifecycle.py", "goxtrade/execution/executed_results.py", "goxtrade/research/backtest.py",
          "goxtrade/research/forward_paper.py", "goxtrade/research/portfolio_backtest.py", "goxtrade/research/portfolio_forward_paper.py",
          "goxtrade/execution/strategy_manager.py", "goxtrade/execution/portfolio_risk.py", "goxtrade/execution/signal_reservations.py",
          "goxtrade/execution/manager_service.py", "goxtrade/execution/trade_candidate.py", "goxtrade/api/app.py",
          "goxtrade/execution/profit_policy.py", "goxtrade/execution/trade_manager.py", "goxtrade/execution/partial_exits.py",
          "goxtrade/execution/trade_analytics.py", "goxtrade/execution/position_protection.py", "goxtrade/execution/profit_service.py",
          "goxtrade/research/managed_positions.py", "goxtrade/research/exit_policy_comparison.py"}
PHASE7_REVIEW = {"goxtrade/api/app.py", "goxtrade/api/state.py", "goxtrade/config/execution_identity.py",
                "goxtrade/execution/practice_executor.py", "goxtrade/execution/projectx_client.py",
                "goxtrade/execution/strategy_manager.py", "goxtrade/execution/portfolio_risk.py",
                "goxtrade/execution/signal_reservations.py", "goxtrade/execution/position_protection.py",
                "goxtrade/execution/leader_execution.py", "goxtrade/execution/leader_worker.py",
                "goxtrade/execution/trade_manager.py", "goxtrade/execution/profit_policy.py",
                "goxtrade/execution/trade_analytics.py", "goxtrade/research/portfolio_backtest.py",
                "goxtrade/research/portfolio_forward_paper.py", "goxtrade/research/managed_positions.py",
                "goxtrade/replay/replay_session.py", "goxtrade/replay/replay_store.py",
                "goxtrade/replay/replay_engine.py", "goxtrade/diagnostics/projectx_diagnostics.py",
                "goxtrade/runtime/run_live_market.py", "goxtrade/runtime/native_app.py",
                "goxtrade/runtime/manager_paper_worker.py", "web/src/store.ts"}


def module(name):
    return name.removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def inspect_files():
    names = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    # Include the current milestone's untracked sources without reading ignored local secrets/data.
    names += subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    rows, references = [], {}
    for name in sorted(set(names)):
        path = ROOT/name
        if path.suffix.lower() not in (".py", ".tsx", ".ts", ".js", ".html", ".css", ".json", ".cmd", ".ps1", ".toml", ".md", ".txt") and path.name not in (".gitignore", ".gitattributes", ".env.example"):
            continue
        if name in ("docs/FULL_SYSTEM_AUDIT.md",) or path.name in ("package-lock.json",):
            # Dependency lock is still read, but not enumerated as application behavior.
            if path.exists():
                path.read_text(encoding="utf-8-sig")
            continue
        source = path.read_text(encoding="utf-8-sig")
        imports, tests, responsibilities = [], 0, ""
        if path.suffix == ".py":
            tree = ast.parse(source)
            doc = ast.get_docstring(tree)
            responsibilities = doc.splitlines()[0] if doc else ", ".join(node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("goxtrade"):
                    imports.append(node.module)
                    imports.extend(node.module+"."+alias.name for alias in node.names)
                if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                    tests += 1
            if name.startswith("tests/"):
                references[name] = set(imports)
        elif path.suffix in (".cmd", ".ps1"):
            responsibilities = "Manual process launcher; no auto-start installation inferred"
        elif path.suffix == ".md":
            responsibilities = next((line.lstrip("# ") for line in source.splitlines() if line.startswith("#")), "Operations/reference text")
        elif path.suffix == ".json":
            import json
            json.loads(source)
            responsibilities = "Structured package/config manifest; not account authorization"
        else:
            responsibilities = "Presentation/build/config surface; runtime behavior requires integration/browser tests"
        rows.append(dict(name=name, lines=len(source.splitlines()), responsibility=responsibilities[:120], imports=imports, tests=tests))
    return rows, references


def inventory():
    rows, references = inspect_files()
    print("## Reproducible Per-File Inventory\n")
    print("Every listed tracked/unignored application file was read. Python was parsed with AST; JSON was parsed structurally. Imports below identify integration points, not tested guarantees. Package initializers and tests are included. Ignored local identities, API keys, databases, logs, dependency/vendor directories and generated builds were not published. The dependency lock was read separately.\n")
    print("| File | Responsibility / integration | Review / protection evidence | Test evidence |")
    print("|---|---|---|---|")
    for row in rows:
        name = row["name"]
        tests = [path.removeprefix("tests/") for path, imports in references.items() if module(name) in imports]
        evidence = ("Phase 7 targeted semantic review + static parsing" if name in PHASE7_REVIEW else
                    "Prior-milestone critical review; Phase 7 static re-inventory" if name in PRIOR_REVIEW else
                    "Static inventory; no additional defect asserted")
        if name.endswith("practice_smoke_test.py"):
            evidence = "DANGEROUS IF RUN: explicit Practice orders; not invoked"
        if name.startswith("tests/"):
            evidence = f"{row['tests']} test methods declared; browser scripts may have zero methods"
        integration = ", ".join(dict.fromkeys(value for value in row["imports"] if value.count(".") > 1))[:100]
        detail = (row["responsibility"] or "Package namespace")+("; uses "+integration if integration else "")
        coverage = ", ".join(tests[:3])+(f" (+{len(tests)-3} more direct-import test modules)" if len(tests)>3 else "") if tests else "No direct-import mapping; see regression/browser suites, not a coverage guarantee"
        print(f"| `{name}` | {detail.replace('|','/')} | {evidence} | {coverage} |")
    print(f"\nInventory: {len(rows)} files, {sum(row['lines'] for row in rows)} source/config/doc lines. Reproduce with `python -m scripts.audit_system`. This inventory is not measured line/branch coverage.\n")


if __name__ == "__main__":
    inventory()
