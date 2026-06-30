def position_size_by_risk(
    capital: float,
    risk_per_trade: float,
    entry_price: float,
    stop_distance: float,
) -> float:
    """Calculate quantity to buy given capital risked and stop distance.

    - `risk_per_trade` is fraction of capital to risk (e.g. 0.01 for 1%).
    - `stop_distance` is absolute price distance between entry and stop.

    Returns quantity (in base asset units). If stop_distance is zero or invalid, returns 0.
    """
    if capital <= 0 or risk_per_trade <= 0:
        return 0.0
    if stop_distance <= 0 or entry_price <= 0:
        return 0.0

    risk_usd = capital * float(risk_per_trade)
    # quantity * stop_distance = risk_usd -> quantity = risk_usd / stop_distance
    qty = risk_usd / float(stop_distance)
    if qty <= 0:
        return 0.0
    return qty
