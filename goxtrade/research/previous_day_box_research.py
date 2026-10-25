"""Explicit, reproducible parameter comparisons. No tuning on future test folds."""
from dataclasses import replace
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.research.backtest import run_backtest, chronological_splits as walk_forward


def compare_variations(minutes,symbol,contract_id,simulation,config=None,walk=False):
    base = PreviousDayBoxConfig.from_dict(config)
    variants = [("Wick",dict(confirmation="wick")),("Sweep",dict(confirmation="sweep")),
                ("Structure",dict(confirmation="structure")),("Combined OR",dict(confirmation="combined",combined_logic="OR")),
                ("Midpoint",dict(target_method="midpoint")),("Opposite zone",dict(target_method="opposite_zone")),
                ("Opposite boundary",dict(target_method="opposite_boundary")),("RR 1:2",dict(target_method="rr",reward_risk=2.)),
                ("20/80 zones",dict(buy_percent=20.,sell_percent=80.)),("30/70 zones",dict(buy_percent=30.,sell_percent=70.)),
                ("RTH",dict(session="rth"))]
    output = []
    for name,values in variants:
        selected = replace(base,**values).validate()
        result = run_backtest(minutes,symbol,contract_id,"previous_day_box",selected,simulation)
        if walk: result["walk_forward"] = walk_forward(minutes,symbol,contract_id,"previous_day_box",selected,simulation)
        output.append(dict(name=name,result=result))
    return output
