import math
import predictor


def _hist(prices):
    return [{"thb_gram": p, "hour": 12, "weekday": 1, "usd_oz": p / 1000} for p in prices]


def test_calc_sma_and_ema_basic():
    prices = [1, 2, 3, 4, 5]
    assert predictor.calc_sma(prices, 5) == 3.0
    assert predictor.calc_sma(prices, 10) is None  # not enough data
    assert predictor.calc_ema(prices, 5) is not None


def test_calc_rsi_all_gains_is_high():
    prices = list(range(1, 30))  # strictly increasing
    rsi = predictor.calc_rsi(prices, 14)
    assert rsi is not None and rsi > 90


def test_calc_rsi_all_losses_is_low():
    prices = list(range(30, 1, -1))  # strictly decreasing
    rsi = predictor.calc_rsi(prices, 14)
    assert rsi is not None and rsi < 10


def test_calc_momentum_direction():
    up = predictor.calc_momentum([100] * 5 + [101, 102, 103, 104, 105, 110], 10)
    assert up is not None and up > 0


def test_trend_summary_change_signs():
    prices = list(range(100, 130))  # rising
    t = predictor.get_trend_summary(_hist(prices))
    assert t["change_1h"] > 0
    assert t["streak_direction"] == "up"
    assert t["streak"] >= 3


def test_analyze_returns_signal_with_enough_data():
    prices = [1000 + math.sin(i / 3) * 5 for i in range(60)]
    res = predictor.analyze(_hist(prices))
    assert "overall_signal" in res
    assert res["rsi"] is not None


def test_analyze_too_little_data():
    res = predictor.analyze(_hist([1, 2, 3]))
    assert "error" in res
