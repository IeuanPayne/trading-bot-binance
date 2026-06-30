from trading_bot import alerts


def test_send_alert_returns_false_when_disabled(monkeypatch):
    monkeypatch.setattr("trading_bot.alerts.ALERTS_ENABLED", False)
    assert alerts.send_alert("test") is False


def test_send_alert_returns_false_when_twilio_missing_config(monkeypatch):
    monkeypatch.setattr("trading_bot.alerts.ALERTS_ENABLED", True)
    monkeypatch.setattr("trading_bot.alerts.ALERT_SMS_PROVIDER", "twilio")
    monkeypatch.setattr("trading_bot.alerts.TWILIO_ACCOUNT_SID", None)
    monkeypatch.setattr("trading_bot.alerts.TWILIO_AUTH_TOKEN", None)
    monkeypatch.setattr("trading_bot.alerts.ALERT_PHONE_TO", None)
    monkeypatch.setattr("trading_bot.alerts.ALERT_PHONE_FROM", None)
    assert alerts.send_alert("test") is False


def test_send_alert_posts_to_twilio(monkeypatch):
    monkeypatch.setattr("trading_bot.alerts.ALERTS_ENABLED", True)
    monkeypatch.setattr("trading_bot.alerts.ALERT_SMS_PROVIDER", "twilio")
    monkeypatch.setattr("trading_bot.alerts.TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr("trading_bot.alerts.TWILIO_AUTH_TOKEN", "token")
    monkeypatch.setattr("trading_bot.alerts.ALERT_PHONE_TO", "+15550000001")
    monkeypatch.setattr("trading_bot.alerts.ALERT_PHONE_FROM", "+15550000002")

    called = {"ok": False}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, data, auth, timeout):
        called["ok"] = True
        assert "Accounts/AC123/Messages.json" in url
        assert data["To"] == "+15550000001"
        assert data["From"] == "+15550000002"
        assert auth == ("AC123", "token")
        assert timeout == 10
        return Response()

    monkeypatch.setattr("trading_bot.alerts.requests.post", fake_post)
    assert alerts.send_alert("hello", level="CRITICAL") is True
    assert called["ok"] is True
