"""Shared statistics for explicitly separated result populations."""
import pandas as pd


def statistics(trades, starting_balance=0., duration_seconds=None, equity=None):
    ordered = sorted(trades, key=lambda row: row.get("exit_time", row.get("time", "")))
    values = [float(row["net"]) for row in ordered]
    wins, losses = [value for value in values if value > 0], [value for value in values if value < 0]
    gross_profit = sum(max(float(row.get("gross", row["net"])), 0) for row in ordered)
    gross_loss = -sum(min(float(row.get("gross", row["net"])), 0) for row in ordered)
    balance = peak = float(starting_balance)
    drawdown = 0.
    consecutive = longest = 0
    for value in values:
        balance += value
        peak = max(peak, balance)
        drawdown = max(drawdown, peak-balance)
        consecutive = consecutive+1 if value < 0 else 0
        longest = max(longest, consecutive)
    if equity:
        peak = starting_balance
        for value in equity:
            peak = max(peak, value)
            drawdown = max(drawdown, peak-value)
    held = [float(row.get("holding_seconds", 0)) for row in ordered]
    multiples = [float(row["r_multiple"]) for row in ordered if row.get("r_multiple") is not None]
    return dict(trades=len(values), wins=len(wins), losses=len(losses), breakeven=len(values)-len(wins)-len(losses),
                win_rate=100*len(wins)/len(values) if values else None,
                gross_profit=gross_profit, gross_loss=gross_loss, gross=gross_profit-gross_loss,
                net=sum(values), profit_factor=sum(wins)/abs(sum(losses)) if losses else None,
                average_win=sum(wins)/len(wins) if wins else None,
                average_loss=sum(losses)/len(losses) if losses else None,
                expectancy=sum(values)/len(values) if values else None, max_drawdown=drawdown,
                largest_win=max(wins) if wins else None, largest_loss=min(losses) if losses else None,
                average_reward_risk=sum(multiples)/len(multiples) if multiples else None,
                max_consecutive_losses=longest, average_holding_seconds=sum(held)/len(held) if held else None,
                exposure_seconds=sum(held), exposure_percent=100*sum(held)/duration_seconds if duration_seconds else None,
                commissions=sum(float(row.get("costs", 0)) for row in ordered),
                estimated_slippage=sum(float(row.get("slippage_cost", 0)) for row in ordered))


def breakdown(trades, key):
    groups = {}
    for row in trades:
        value = pd.Timestamp(row["exit_time"]).strftime("%Y-%m") if key == "month" else str(row.get(key, "Unknown"))
        groups.setdefault(value, []).append(row)
    return {value: statistics(rows) for value, rows in groups.items()}
