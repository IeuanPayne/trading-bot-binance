from typing import Any, List, Dict, Optional, Tuple


def compute_trade_metrics(trades: List[Dict[str, Any]], initial_capital: float = 10000.0) -> Dict[str, Any]:
    """Compute performance metrics from trades list.

    Expects `trades` as list of trade dicts produced by the backtester.
    Returns dict with total_pnl, win_rate, avg_return, max_drawdown, num_pairs.
    
    Args:
        trades: List of trade dicts with 'reason', 'qty', 'price' keys
        initial_capital: Starting capital in base currency
    
    Returns:
        Dictionary with metrics
    """
    # Build pairs (entry, exit)
    pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    entry: Optional[Dict[str, Any]] = None
    for t in trades:
        if t.get("reason") in ("long_entry", "short_entry", "buy", "sell_short"):
            entry = t
        elif t.get("reason") in ("tp/sl", "opposite_signal", "final_close"):
            if entry is not None:
                pairs.append((entry, t))
                entry = None

    returns: List[float] = []
    for ent, ex in pairs:
        qty: float = float(ent.get("qty", 0.0))
        entry_price: float = float(ent.get("price", 0.0))
        exit_price: float = float(ex.get("price", 0.0))
        if ent.get("type") in ("buy",):
            pnl: float = (exit_price - entry_price) * qty
        elif ent.get("type") in ("sell_short",):
            pnl = (entry_price - exit_price) * qty
        else:
            pnl = 0.0
        returns.append(pnl)

    total_pnl: float = sum(returns)
    win_rate: Optional[float] = None
    avg_return: Optional[float] = None
    if returns:
        wins: List[float] = [r for r in returns if r > 0]
        win_rate = len(wins) / len(returns)
        avg_return = sum(returns) / len(returns)

    # Calculate max drawdown based on cumulative equity
    equity: float = initial_capital
    peak: float = equity
    max_dd: float = 0.0
    for r in returns:
        equity += r
        if equity > peak:
            peak = equity
        dd: float = (peak - equity) / peak
        if dd > max_dd:
            max_dd = dd

    return {
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "max_drawdown": max_dd,
        "num_pairs": len(pairs),
    }
