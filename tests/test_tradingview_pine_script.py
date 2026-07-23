from __future__ import annotations

import json
import re
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tradingview_playbit_ema.pine"


def _pine_source() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def test_pine_script_defaults_to_anchor_close_touch_mode():
    source = _pine_source()

    assert 'touchEmaSource = input.string("Anchor Close", "Touch EMA"' in source
    assert '"Anchor High", "Anchor Close"' in source
    assert 'anchorEmaLen = input.int(200, "Anchor EMA Length", minval=1)' in source


def test_pine_script_uses_wick_touch_logic():
    source = _pine_source()

    assert "useAnchorBandTouch = touchEmaSource == \"Anchor High\" or touchEmaSource == \"Anchor Close\"" in source
    assert "touchedEma = useAnchorBandTouch ? (low <= anchorBandTop and high >= anchorBandBottom) : (low <= touchEma and high >= touchEma)" in source
    assert "referenceLine = useAnchorBandTouch ? anchorClose : touchEma" in source
    assert "if touchedEma" in source
    assert "if close > referenceLine" in source
    assert "else if close < referenceLine" in source
    assert "bodyTouchEma = math.min(open, close) <= touchEma and math.max(open, close) >= touchEma" not in source


def test_pine_script_does_not_use_rearm_or_distance_gates():
    source = _pine_source()

    assert "Rearm Distance From Touch EMA (%)" not in source
    assert "Max Close Distance To Touch EMA (%)" not in source
    assert "Max EMA Channel Width (%)" not in source
    assert "longTouchArmed" not in source
    assert "shortTouchArmed" not in source


def test_pine_script_supports_anchor_color_modes():
    source = _pine_source()

    assert 'anchorColorMode = input.string("Price Relative", "Anchor Color Mode", options=["Fixed", "Slope", "Price Relative"])' in source
    assert "anchorBull = anchorColorMode == \"Fixed\" ? true : anchorColorMode == \"Slope\" ? anchorSlopeUp : close >= anchorClose" in source
    assert "activeAnchorHighColor = anchorBull ? anchorHighColor : anchorBearHighColor" in source
    assert "activeAnchorCloseColor = anchorBull ? anchorCloseColor : anchorBearCloseColor" in source


def test_pine_script_plots_anchor_band_with_active_colors():
    source = _pine_source()

    assert "pAnchorHigh = plot(showAnchorBand ? anchorHigh : na, color=activeAnchorHighColor, linewidth=anchorLineWidth" in source
    assert "pAnchorClose = plot(showAnchorBand ? anchorClose : na, color=activeAnchorCloseColor, linewidth=anchorLineWidth" in source
    assert "fill(pAnchorHigh, pAnchorClose, color=showAnchorBand ? color.new(activeAnchorCloseColor, anchorFillTransparency) : na, fillgaps=true)" in source


def test_pine_script_long_and_short_alert_payloads_are_valid_json_templates():
    source = _pine_source()
    payloads = re.findall(r"alertcondition\([^\n]+message='([^']+)'\)", source)

    assert len(payloads) == 2

    for payload in payloads:
        rendered = (
            payload.replace("{{ticker}}", "XAUUSD")
            .replace("{{interval}}", "15m")
            .replace("{{timenow}}", "2026-07-21T23:15:00Z")
            .replace("YOUR_TV_WEBHOOK_SECRET", "test-secret")
        )
        decoded = json.loads(rendered)

        assert decoded["secret"] == "test-secret"
        assert decoded["symbol"] == "XAUUSD"
        assert decoded["timeframe"] == "15m"
        assert decoded["strategy_id"] == "pb-ema"
        assert decoded["side"] in {"buy", "sell"}
