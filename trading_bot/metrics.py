from typing import List, Dict


def compute_trade_metrics(trades: List[Dict], initial_capital: float = 10000.0) -> Dict:
    """Compute simple metrics from trades list.

    Expects `trades` as list of trade dicts produced by the backtester.
    Returns dict with pnl, win_rate, avg_return, max_drawdown.
    """
    # Build pairs (entry, exit)
    pairs = []
    entry = None
    for t in trades:
        if t.get("reason") in ("long_entry", "short_entry", "buy", "sell_short"):
            entry = t
        elif t.get("reason") in ("tp/sl", "opposite_signal", "final_close",):
            if entry is not None:
                pairs.append((entry, t))
                entry = None

    returns = []
    for ent, ex in pairs:
        qty = float(ent.get("qty", 0.0))
        entry_price = float(ent.get("price", 0.0))
        exit_price = float(ex.get("price", 0.0))
        if ent.get("type") in ("buy",):
            pnl = (exit_price - entry_price) * qty
        elif ent.get("type") in ("sell_short",):
            pnl = (entry_price - exit_price) * qty
        else:
            pnl = 0.0
        returns.append(pnl)

    total_pnl = sum(returns)
    win_rate = None
    avg_return = None
    if returns:
        wins = [r for r in returns if r > 0]
        win_rate = len(wins) / len(returns)
        avg_return = sum(returns) / len(returns)

    # simple max drawdown calculation based on cumulative equity
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for r in returns:
        equity += r
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "max_drawdown": max_dd,
        "num_pairs": len(pairs),
    }
