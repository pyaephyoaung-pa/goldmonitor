"""
Gold Price Prediction Engine
- Technical indicators: RSI, SMA, EMA, MACD, Bollinger Bands, Momentum
- ML model: GradientBoosting classifier for 4h/12h/24h direction
"""

import numpy as np
from datetime import datetime, timedelta
import json
import pickle
import base64

# ── Technical Indicators ────────────────────────────────────────

def calc_rsi(prices: list, period: int = 14) -> float | None:
    """Calculate RSI (Relative Strength Index)."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-period:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0.0001
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def calc_sma(prices: list, period: int) -> float | None:
    """Simple Moving Average."""
    if len(prices) < period:
        return None
    return round(sum(prices[-period:]) / period, 2)


def calc_ema(prices: list, period: int) -> float | None:
    """Exponential Moving Average."""
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return round(ema, 2)


def calc_macd(prices: list) -> dict | None:
    """MACD (12, 26, 9)."""
    if len(prices) < 26:
        return None
    ema12 = calc_ema(prices, 12)
    ema26 = calc_ema(prices, 26)
    if ema12 is None or ema26 is None:
        return None
    macd_line = round(ema12 - ema26, 2)
    # Signal line (9-period EMA of MACD) — approximate
    # Calculate MACD for recent points
    macd_values = []
    for i in range(26, len(prices) + 1):
        sub = prices[:i]
        e12 = calc_ema(sub, 12)
        e26 = calc_ema(sub, 26)
        if e12 and e26:
            macd_values.append(e12 - e26)
    signal = calc_ema(macd_values, 9) if len(macd_values) >= 9 else macd_line
    histogram = round(macd_line - (signal or 0), 2)
    return {"macd": macd_line, "signal": round(signal or 0, 2), "histogram": histogram}


def calc_bollinger(prices: list, period: int = 20, std_dev: float = 2.0) -> dict | None:
    """Bollinger Bands."""
    if len(prices) < period:
        return None
    recent = prices[-period:]
    sma = sum(recent) / period
    variance = sum((p - sma) ** 2 for p in recent) / period
    std = variance ** 0.5
    return {
        "upper": round(sma + std_dev * std, 2),
        "middle": round(sma, 2),
        "lower": round(sma - std_dev * std, 2),
        "position": round((prices[-1] - (sma - std_dev * std)) / (2 * std_dev * std) * 100, 1) if std > 0 else 50,
    }


def calc_momentum(prices: list, period: int = 10) -> float | None:
    """Rate of change (%)."""
    if len(prices) < period + 1:
        return None
    return round(((prices[-1] - prices[-period - 1]) / prices[-period - 1]) * 100, 3)


def calc_volatility(prices: list, period: int = 20) -> float | None:
    """Standard deviation as % of mean (coefficient of variation)."""
    if len(prices) < period:
        return None
    recent = prices[-period:]
    mean = sum(recent) / len(recent)
    if mean == 0:
        return None
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    return round((variance ** 0.5 / mean) * 100, 4)


def calc_support_resistance(prices: list, lookback: int = 48) -> dict:
    """Find approximate support and resistance levels."""
    if len(prices) < lookback:
        lookback = len(prices)
    recent = prices[-lookback:]
    sorted_prices = sorted(recent)
    n = len(sorted_prices)
    return {
        "support_1": round(sorted_prices[int(n * 0.10)], 2),
        "support_2": round(sorted_prices[int(n * 0.05)], 2),
        "resistance_1": round(sorted_prices[int(n * 0.90)], 2),
        "resistance_2": round(sorted_prices[int(n * 0.95)], 2),
    }


# ── Full Technical Analysis ─────────────────────────────────────

def analyze(history: list) -> dict:
    """Run all technical indicators on price history.

    Args:
        history: list of dicts with at least 'thb_gram' field
    Returns:
        dict of all indicator values + interpretation
    """
    if not history or len(history) < 5:
        return {"error": "Not enough data (need at least 5 data points)"}

    prices = [h["thb_gram"] for h in history]
    current = prices[-1]

    result = {"current_price": current, "data_points": len(prices)}

    # RSI
    rsi = calc_rsi(prices)
    result["rsi"] = rsi
    if rsi is not None:
        if rsi < 30:
            result["rsi_signal"] = "OVERSOLD — buy opportunity"
        elif rsi > 70:
            result["rsi_signal"] = "OVERBOUGHT — consider waiting"
        else:
            result["rsi_signal"] = "NEUTRAL"

    # Moving Averages
    sma5 = calc_sma(prices, 5)
    sma20 = calc_sma(prices, 20)
    ema12 = calc_ema(prices, 12)
    result["sma5"] = sma5
    result["sma20"] = sma20
    result["ema12"] = ema12

    if sma5 and sma20:
        if sma5 > sma20:
            result["ma_signal"] = "BULLISH — short-term above long-term"
        else:
            result["ma_signal"] = "BEARISH — short-term below long-term"
        result["ma_crossover_pct"] = round(((sma5 - sma20) / sma20) * 100, 3)

    # Price vs SMA
    if sma20:
        result["price_vs_sma20"] = round(((current - sma20) / sma20) * 100, 3)

    # MACD
    macd = calc_macd(prices)
    result["macd"] = macd
    if macd:
        if macd["histogram"] > 0:
            result["macd_signal"] = "BULLISH momentum"
        else:
            result["macd_signal"] = "BEARISH momentum"

    # Bollinger Bands
    bb = calc_bollinger(prices)
    result["bollinger"] = bb
    if bb:
        if bb["position"] < 10:
            result["bb_signal"] = "NEAR LOWER BAND — potential bounce/buy"
        elif bb["position"] > 90:
            result["bb_signal"] = "NEAR UPPER BAND — potential pullback"
        else:
            result["bb_signal"] = "WITHIN BANDS"

    # Momentum
    mom = calc_momentum(prices)
    result["momentum"] = mom
    if mom is not None:
        if mom < -0.5:
            result["momentum_signal"] = "DECLINING"
        elif mom > 0.5:
            result["momentum_signal"] = "RISING"
        else:
            result["momentum_signal"] = "FLAT"

    # Volatility
    vol = calc_volatility(prices)
    result["volatility"] = vol

    # Support / Resistance
    sr = calc_support_resistance(prices)
    result["support_resistance"] = sr

    # ── Overall Score (weighted composite) ──────────────────────
    score = 0
    factors = 0

    if rsi is not None:
        if rsi < 30: score += 2
        elif rsi < 40: score += 1
        elif rsi > 70: score -= 2
        elif rsi > 60: score -= 1
        factors += 1

    if sma5 and sma20:
        if sma5 > sma20: score -= 0.5  # price already up, less attractive
        else: score += 1  # dipping below average
        factors += 1

    if macd and macd["histogram"] < 0:
        score += 0.5
    elif macd:
        score -= 0.5
    if macd:
        factors += 1

    if bb:
        if bb["position"] < 20: score += 1.5
        elif bb["position"] > 80: score -= 1
        factors += 1

    if mom is not None:
        if mom < -1: score += 1
        elif mom > 1: score -= 0.5
        factors += 1

    if factors > 0:
        normalized = round(score / factors, 2)
        result["buy_score"] = normalized
        if normalized > 1:
            result["overall_signal"] = "STRONG BUY"
        elif normalized > 0.3:
            result["overall_signal"] = "BUY"
        elif normalized > -0.3:
            result["overall_signal"] = "HOLD"
        elif normalized > -1:
            result["overall_signal"] = "WAIT"
        else:
            result["overall_signal"] = "OVERBOUGHT"

    return result


# ── ML Prediction Engine ────────────────────────────────────────

def _extract_features(history: list, idx: int) -> list | None:
    """Extract feature vector for a single data point.
    Requires at least 26 prior points for MACD.
    """
    if idx < 26:
        return None

    prices = [h["thb_gram"] for h in history[:idx + 1]]
    entry = history[idx]

    rsi = calc_rsi(prices, 14)
    sma5 = calc_sma(prices, 5)
    sma20 = calc_sma(prices, 20)
    ema12 = calc_ema(prices, 12)
    macd = calc_macd(prices)
    bb = calc_bollinger(prices, 20)
    mom = calc_momentum(prices, 10)
    vol = calc_volatility(prices, 20)

    if any(v is None for v in [rsi, sma5, sma20, ema12, macd, bb, mom, vol]):
        return None

    current = prices[-1]
    features = [
        rsi,
        (current - sma5) / sma5 * 100,      # price vs SMA5
        (current - sma20) / sma20 * 100,     # price vs SMA20
        (sma5 - sma20) / sma20 * 100,        # SMA crossover
        macd["macd"],
        macd["histogram"],
        bb["position"],
        mom,
        vol,
        entry.get("hour", 12),
        entry.get("weekday", 0),
        # Price change features
        (prices[-1] - prices[-2]) / prices[-2] * 100 if len(prices) >= 2 else 0,
        (prices[-1] - prices[-4]) / prices[-4] * 100 if len(prices) >= 4 else 0,
    ]
    return features


def _build_labels(history: list, idx: int, horizon: int) -> int | None:
    """Label: 1 if price goes up within `horizon` steps, 0 if down."""
    if idx + horizon >= len(history):
        return None
    future_prices = [h["thb_gram"] for h in history[idx + 1:idx + horizon + 1]]
    current = history[idx]["thb_gram"]
    max_future = max(future_prices)
    min_future = min(future_prices)
    # If max gain > max loss, label as UP
    return 1 if (max_future - current) > (current - min_future) else 0


def train_model(history: list) -> dict | None:
    """Train gradient boosting models for 4h, 12h, 24h prediction.

    Returns serialized models as base64 strings, or None if not enough data.
    """
    try:
        from sklearn.ensemble import GradientBoostingClassifier
    except ImportError:
        print("[predictor] scikit-learn not available — skipping ML training")
        return None

    if len(history) < 100:
        print(f"[predictor] Need 100+ data points for training, have {len(history)}")
        return None

    models = {}
    horizons = {"4h": 4, "12h": 12, "24h": 24}

    def _make_model():
        return GradientBoostingClassifier(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            random_state=42,
        )

    for name, horizon in horizons.items():
        # Build samples in chronological order (do NOT shuffle — time series).
        X, y = [], []
        for i in range(26, len(history) - horizon):
            features = _extract_features(history, i)
            label = _build_labels(history, i, horizon)
            if features is not None and label is not None:
                X.append(features)
                y.append(label)

        if len(X) < 60:
            print(f"[predictor] Not enough labeled data for {name}: {len(X)} samples")
            continue

        X_arr = np.array(X)
        y_arr = np.array(y)

        # ── Honest evaluation: chronological hold-out ────────────────
        # The previous version reported *training* accuracy, which on a
        # near-random-walk price series just measures overfitting. We instead
        # train on the first 80% and score on the most recent 20% the model has
        # never seen, then compare against a majority-class baseline so we can
        # tell whether the model has any real edge over a coin flip.
        split = int(len(X_arr) * 0.8)
        X_tr, X_te = X_arr[:split], X_arr[split:]
        y_tr, y_te = y_arr[:split], y_arr[split:]

        if len(X_te) < 20:
            print(f"[predictor] {name}: too few hold-out samples ({len(X_te)}) — skipping")
            continue

        eval_model = _make_model()
        eval_model.fit(X_tr, y_tr)
        oos_acc = round(eval_model.score(X_te, y_te) * 100, 1)
        train_acc = round(eval_model.score(X_tr, y_tr) * 100, 1)

        # Majority-class baseline measured on the same hold-out window.
        ones = int(y_te.sum())
        n_te = len(y_te)
        baseline_acc = round(max(ones, n_te - ones) / n_te * 100, 1)

        # "Edge" = beats the naive baseline by a margin (not just noise).
        has_edge = oos_acc >= baseline_acc + 2.0

        print(
            f"[predictor] {name}: OOS={oos_acc}% baseline={baseline_acc}% "
            f"train={train_acc}% edge={has_edge} ({len(X)} samples, {n_te} test)"
        )

        # Deploy a model trained on ALL data; the metrics above describe its
        # expected real-world skill.
        model = _make_model()
        model.fit(X_arr, y_arr)

        model_bytes = pickle.dumps(model)
        models[name] = {
            "model_b64": base64.b64encode(model_bytes).decode("utf-8"),
            "accuracy": oos_acc,          # back-compat: now the honest OOS number
            "oos_accuracy": oos_acc,
            "baseline_accuracy": baseline_acc,
            "train_accuracy": train_acc,
            "has_edge": has_edge,
            "samples": len(X),
            "test_samples": n_te,
        }

    if not models:
        return None

    return {
        "models": models,
        "last_trained": datetime.now().isoformat(),
        "total_history": len(history),
        "feature_names": [
            "rsi", "price_vs_sma5", "price_vs_sma20", "sma_crossover",
            "macd", "macd_histogram", "bb_position", "momentum",
            "volatility", "hour", "weekday", "change_1h", "change_4h",
        ],
    }


def predict(history: list, model_data: dict) -> dict:
    """Make predictions using trained models + technical analysis.

    Returns prediction for each horizon with confidence.
    """
    result = {}
    ta = analyze(history)
    result["technical_analysis"] = ta

    # Include USD price from latest history entry
    if history:
        result["usd_oz"] = history[-1].get("usd_oz")

    # Technical-only prediction (always available)
    # buy_score > 0 = oversold/dipping = BUY opportunity
    # buy_score < 0 = overbought/rising = WAIT
    score = ta.get("buy_score", 0)
    if score > 1:
        result["ta_outlook"] = "🟢 STRONG BUY — ဈေး oversold ဖြစ်နေ၊ ဝယ်ရန် အကောင်းဆုံးအချိန်"
    elif score > 0.3:
        result["ta_outlook"] = "🟡 BUY — ဈေးကျနေ၊ ဝယ်ရန် စဉ်းစားပါ"
    elif score > -0.3:
        result["ta_outlook"] = "⚪ HOLD — ဈေးတည်ငြိမ်နေ၊ စောင့်ကြည့်ပါ"
    elif score > -1:
        result["ta_outlook"] = "🟠 WAIT — ဈေးတက်နေ၊ ဝယ်ဖို့ မသင့်သေး"
    else:
        result["ta_outlook"] = "🔴 OVERBOUGHT — ဈေးအလွန်မြင့်နေ၊ မဝယ်သင့်"

    # ML predictions (if models exist)
    models_dict = model_data.get("models", {})
    if not models_dict or len(history) < 27:
        result["ml_available"] = False
        if len(history) >= 100:
            result["ml_note"] = f"Data {len(history)} ခု ရှိပြီ — 3am BKK တွင် auto-train ဖြစ်ပါမည်"
        else:
            result["ml_note"] = f"Data {len(history)}/100 — {100 - len(history)} ခု ထပ်လိုပါသေးသည်"
        return result

    try:
        import pickle
        features = _extract_features(history, len(history) - 1)
        if features is None:
            result["ml_available"] = False
            return result

        X_pred = np.array([features])
        result["ml_available"] = True
        result["predictions"] = {}

        for horizon_name, minfo in models_dict.items():
            try:
                model = pickle.loads(base64.b64decode(minfo["model_b64"]))
                proba = model.predict_proba(X_pred)[0]
                pred_class = model.predict(X_pred)[0]
                confidence = round(max(proba) * 100, 1)

                direction = "UP" if pred_class == 1 else "DOWN"
                result["predictions"][horizon_name] = {
                    "direction": direction,
                    "confidence": confidence,
                    "model_accuracy": minfo.get("accuracy"),
                    "oos_accuracy": minfo.get("oos_accuracy", minfo.get("accuracy")),
                    "baseline_accuracy": minfo.get("baseline_accuracy"),
                    "has_edge": minfo.get("has_edge", False),
                    "training_samples": minfo.get("samples"),
                }
            except Exception as e:
                result["predictions"][horizon_name] = {"error": str(e)}

    except ImportError:
        result["ml_available"] = False
        result["ml_note"] = "scikit-learn not available"

    # ── Combined Signal ─────────────────────────────────────────
    if result.get("predictions"):
        directional = [
            p for p in result["predictions"].values()
            if isinstance(p, dict) and "direction" in p
        ]
        # Only trust horizons that actually beat the baseline out-of-sample.
        edged = [p for p in directional if p.get("has_edge")]
        result["ml_has_edge"] = bool(edged)

        if not edged:
            # Honesty: none of the models show real predictive skill. Don't
            # dress up coin-flips as a forecast.
            result["combined_outlook"] = (
                "⚠️ ML models show no historical edge over a coin-flip — "
                "treat ML as noise; rely on the TA signal below"
            )
        else:
            up_votes = sum(1 for p in edged if p.get("direction") == "UP")
            total = len(edged)
            if up_votes > total / 2:
                result["combined_outlook"] = "ML models (with edge) lean BULLISH"
            elif up_votes < total / 2:
                result["combined_outlook"] = "ML models (with edge) lean BEARISH — consider buying"
            else:
                result["combined_outlook"] = "ML models (with edge) are MIXED"

    return result


# ── Trend Analysis ──────────────────────────────────────────────

def get_trend_summary(history: list) -> dict:
    """Compute multi-timeframe trend summary."""
    if len(history) < 2:
        return {"error": "Not enough data"}

    prices = [h["thb_gram"] for h in history]
    current = prices[-1]

    def pct_change(old, new):
        return round(((new - old) / old) * 100, 3) if old else 0

    result = {"current": current}

    # 1-hour change
    if len(prices) >= 2:
        result["change_1h"] = pct_change(prices[-2], current)

    # 4-hour change
    if len(prices) >= 4:
        result["change_4h"] = pct_change(prices[-4], current)

    # 24-hour change
    if len(prices) >= 24:
        result["change_24h"] = pct_change(prices[-24], current)

    # 7-day change
    if len(prices) >= 168:
        result["change_7d"] = pct_change(prices[-168], current)

    # 30-day change
    if len(prices) >= 720:
        result["change_30d"] = pct_change(prices[-720], current)

    # Consecutive direction
    streak = 0
    direction = None
    for i in range(len(prices) - 1, 0, -1):
        if prices[i] > prices[i - 1]:
            if direction is None:
                direction = "up"
            if direction == "up":
                streak += 1
            else:
                break
        elif prices[i] < prices[i - 1]:
            if direction is None:
                direction = "down"
            if direction == "down":
                streak += 1
            else:
                break
        else:
            break

    result["streak"] = streak
    result["streak_direction"] = direction or "flat"

    # Period high/low
    if len(prices) >= 24:
        p24 = prices[-24:]
        result["high_24h"] = round(max(p24), 2)
        result["low_24h"] = round(min(p24), 2)

    if len(prices) >= 168:
        p7d = prices[-168:]
        result["high_7d"] = round(max(p7d), 2)
        result["low_7d"] = round(min(p7d), 2)

    return result


def format_prediction_message(prediction: dict) -> str:
    """Format prediction results into a Telegram-friendly message."""
    lines = ["🔮 ရွှေဈေး ခန့်မှန်းချက်", "━━━━━━━━━━━━━━━"]

    ta = prediction.get("technical_analysis", {})

    # Current price context
    if ta.get("current_price"):
        usd_line = f" | ${prediction['usd_oz']}/oz" if prediction.get("usd_oz") else ""
        lines.append(f"💰 လက်ရှိဈေး: ฿{ta['current_price']:,.0f}/g{usd_line}")

    # RSI with visual bar
    if ta.get("rsi") is not None:
        rsi = ta["rsi"]
        if rsi < 30:
            rsi_bar = "▓░░░░ Oversold"
        elif rsi < 40:
            rsi_bar = "▓▓░░░ Low"
        elif rsi < 60:
            rsi_bar = "▓▓▓░░ Neutral"
        elif rsi < 70:
            rsi_bar = "▓▓▓▓░ High"
        else:
            rsi_bar = "▓▓▓▓▓ Overbought"
        lines.append(f"📊 RSI: {rsi} [{rsi_bar}]")

    lines.append("━━━━━━━━━━━━━━━")

    # Moving Averages
    if ta.get("sma5") and ta.get("sma20"):
        cross_pct = ta.get("ma_crossover_pct", 0)
        if cross_pct > 0:
            lines.append(f"📈 SMA5 > SMA20: +{cross_pct}% (Bullish)")
        else:
            lines.append(f"📉 SMA5 < SMA20: {cross_pct}% (Bearish)")

    # MACD
    if ta.get("macd"):
        macd = ta["macd"]
        hist_arrow = "📈" if macd["histogram"] > 0 else "📉"
        lines.append(f"{hist_arrow} MACD: {macd['macd']} | Signal: {macd['signal']} | Hist: {macd['histogram']}")

    # Bollinger Bands
    if ta.get("bollinger"):
        bb = ta["bollinger"]
        lines.append(
            f"📏 Bollinger: ↑{bb['upper']:,.0f} ─{bb['middle']:,.0f}─ ↓{bb['lower']:,.0f} "
            f"(Position: {bb['position']}%)"
        )

    # Momentum & Volatility
    parts = []
    if ta.get("momentum") is not None:
        parts.append(f"Momentum: {ta['momentum']:+.3f}%")
    if ta.get("volatility") is not None:
        parts.append(f"Vol: {ta['volatility']:.4f}%")
    if parts:
        lines.append(f"⚡ {' | '.join(parts)}")

    # Support / Resistance
    sr = ta.get("support_resistance")
    if sr:
        lines.append(
            f"🔻 Support: ฿{sr['support_1']:,.0f} / ฿{sr['support_2']:,.0f}\n"
            f"🔺 Resistance: ฿{sr['resistance_1']:,.0f} / ฿{sr['resistance_2']:,.0f}"
        )

    # Overall TA signal
    lines.append("━━━━━━━━━━━━━━━")
    if ta.get("overall_signal"):
        lines.append(f"🎯 Technical Signal: {ta['overall_signal']} (score: {ta.get('buy_score', '?')})")

    # ML Predictions
    if prediction.get("predictions"):
        lines.append("")
        lines.append("🤖 ML Predictions:")
        for horizon, pred in sorted(prediction["predictions"].items()):
            if "direction" in pred:
                arrow = "🟢" if pred["direction"] == "UP" else "🔴"
                conf_bar = "▓" * int(pred["confidence"] / 20) + "░" * (5 - int(pred["confidence"] / 20))
                edge_tag = "✅edge" if pred.get("has_edge") else "⚠️no-edge"
                oos = pred.get("oos_accuracy")
                base = pred.get("baseline_accuracy")
                acc_part = ""
                if oos is not None and base is not None:
                    acc_part = f" | OOS {oos}% vs base {base}% {edge_tag}"
                lines.append(
                    f"  {arrow} {horizon}: {pred['direction']} "
                    f"[{conf_bar}] {pred['confidence']}%{acc_part}"
                )
            elif "error" in pred:
                lines.append(f"  ⚠️ {horizon}: {pred['error']}")

        if prediction.get("ml_has_edge") is False:
            lines.append("  ⚠️ No model beats a coin-flip out-of-sample — ML is noise here.")

    # Final Outlook
    lines.append("━━━━━━━━━━━━━━━")
    if prediction.get("combined_outlook"):
        lines.append(f"💡 {prediction['combined_outlook']}")
    if prediction.get("ta_outlook"):
        lines.append(f"📋 {prediction['ta_outlook']}")

    if not prediction.get("ml_available"):
        note = prediction.get("ml_note", "")
        lines.append(f"ℹ️ ML: {note}")

    return "\n".join(lines)
