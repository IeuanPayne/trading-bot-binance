from trading_bot import __version__
from trading_bot.bot import run_backtest


def test_package_imports_version():
    assert __version__ == "0.1"


def test_run_backtest_callable():
    assert callable(run_backtest)
