from __future__ import annotations

import requests
from loguru import logger

from .config import (
    ALERT_PHONE_FROM,
    ALERT_PHONE_TO,
    ALERT_SMS_PROVIDER,
    ALERTS_ENABLED,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
)


def send_alert(message: str, level: str = "ERROR") -> bool:
    """Send an operator alert.

    Returns True when an alert is dispatched successfully; False otherwise.
    """
    if not ALERTS_ENABLED:
        return False

    provider = ALERT_SMS_PROVIDER.lower().strip()
    if provider == "twilio":
        return _send_twilio_sms(message, level)

    logger.warning("Alerting is enabled but provider '{}' is unsupported.", ALERT_SMS_PROVIDER)
    return False


def _send_twilio_sms(message: str, level: str) -> bool:
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.warning("Twilio alerting is enabled but credentials are missing.")
        return False
    if not ALERT_PHONE_TO or not ALERT_PHONE_FROM:
        logger.warning("Twilio alerting is enabled but ALERT_PHONE_TO/ALERT_PHONE_FROM are missing.")
        return False

    body = f"[TRADING-BOT {level}] {message}"
    endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    payload = {
        "To": ALERT_PHONE_TO,
        "From": ALERT_PHONE_FROM,
        "Body": body,
    }

    try:
        response = requests.post(
            endpoint,
            data=payload,
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as exc:  # pragma: no cover - network/provider failures are runtime concerns
        logger.error("Failed to send Twilio SMS alert: {}", exc)
        return False
