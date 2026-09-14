"""
Gold Price Prediction Engine
- Technical indicators: RSI, SMA, EMA, MACD, Bollinger Bands, Momentum
- ML model: GradientBoosting classifier for 4h/12h/24h direction
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math

import pytz

import events
import i18n
from gold_format import usd_oz_suffix

# Training is scheduled against Bangkok wall-clock time, so `last_trained` must
# be stamped in the same zone as the date the caller compares it to.
BANGKOK_TZ = pytz.timezone("Asia/Bangkok")

# ── History hygiene ─────────────────────────────────────────────

def priced_points(history: list) -> list:
    """The history entries that actually carry a price.

    Everything downstream indexes h["thb_gram"] directly, so a single
    malformed or partially written row raises KeyError — inside the monitor's
    five-minute loop, that is a red run and a crash alert every five minutes
    until someone hand-edits the Gist. chart_points() and regime.vol_regime()
    already filtered for exactly this; analyze(), get_trend_summary() and
    /history did not. Filter once, here, and let every caller share it.
    """
    return [h for h in history
            if isinstance(h, dict) and h.get("thb_gram") is not None]


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


def _ema_series(prices: list, period: int) -> list:
    """EMA of every prefix of `prices`, from the first full window onward.

    `_ema_series(prices, p)[k]` equals `calc_ema(prices[:p + k], p)` — same
    rounding, one pass instead of one full re-scan per prefix.
    """
    if len(prices) < period:
        return []
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    out = [round(ema, 2)]
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        out.append(round(ema, 2))
    return out


def calc_macd(prices: list) -> dict | None:
    """MACD (12, 26, 9).

    The signal line needs the MACD value at every prefix. Recomputing both EMAs
    from scratch for each of those made this quadratic in len(prices), and it
    sits inside the per-sample feature extraction — so it dominated training
    cost. The prefix EMAs now come from a single incremental pass.
    """
    if len(prices) < 26:
        return None
    s12 = _ema_series(prices, 12)
    s26 = _ema_series(prices, 26)
    if not s12 or not s26:
        return None
    ema12, ema26 = s12[-1], s26[-1]
    macd_line = round(ema12 - ema26, 2)
    # Signal line (9-period EMA of MACD) — approximate
    macd_values = []
    for i in range(26, len(prices) + 1):
        e12, e26 = s12[i - 12], s26[i - 26]
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
    prices = [h["thb_gram"] for h in priced_points(history)]
    if len(prices) < 5:
        return {"error": "Not enough data (need at least 5 data points)"}

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

# Feature-vector order is fixed; see `feature_names` in train_model(). Adding or
# reordering a feature invalidates any model already stored in the Gist, so the
# training metadata records the names alongside the exported models.

EVENT_HOURS_CAP = 168.0  # a week out is "far away" as far as the model cares


def _entry_time(entry: dict):
    """The point's own timestamp, or None if it is unusable."""
    try:
        return datetime.fromisoformat(entry["ts"])
    except (KeyError, ValueError, TypeError):
        return None


def _hours_to_event(entry: dict) -> float:
    t = _entry_time(entry)
    if t is None:
        return EVENT_HOURS_CAP
    return events.hours_to_next(t, cap=EVENT_HOURS_CAP)


def _in_event_window(entry: dict) -> bool:
    t = _entry_time(entry)
    return False if t is None else events.in_event_window(t)


def _extract_features(history: list, idx: int) -> list | None:
    """Extract feature vector for a single data point.
    Requires at least 26 prior points for MACD.

    Every other feature here is derived from the price series itself, which is
    why the models honestly report no edge on what is close to a random walk.
    The two event-timing features are the only EXOGENOUS information in the
    vector — they are computed from the point's own timestamp, so a historical
    row sees exactly what was knowable at that moment.
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
        _hours_to_event(entry),
        1.0 if _in_event_window(entry) else 0.0,
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


# ── Model serialization (no pickle) ─────────────────────────────
#
# Models used to be stored as base64 pickles in the Gist and loaded with
# pickle.loads(). Unpickling EXECUTES CODE, so anything that could write to
# that Gist could run arbitrary code inside the Actions runner — which holds
# the Telegram bot token and every other secret. The trust boundary was a
# single GitHub token guarding what is only ever a data store.
#
# A GradientBoostingClassifier for binary log-loss is a small amount of
# arithmetic, so we export the trees as plain numbers and score them here:
#
#     raw   = intercept + learning_rate * sum(leaf value of each tree)
#     P(up) = 1 / (1 + exp(-raw))
#
# The export is VERIFIED against sklearn's own predict_proba before it is
# stored (see _export_model), so a future sklearn changing its internals
# fails loudly at training time instead of silently scoring differently in
# production. Inference is now pure stdlib arithmetic — no pickle, no
# scikit-learn, no numpy — so only the training job needs those installed.

MODEL_FORMAT = "gbdt-json-1"

# Match sklearn's exactly: leaves are marked by children_left == TREE_LEAF.
_TREE_LEAF = -1

# Agreement required between our scorer and sklearn's, in probability.
_EXPORT_TOLERANCE = 1e-9


def _export_tree(estimator) -> dict:
    """One fitted DecisionTreeRegressor as JSON-safe arrays."""
    t = estimator.tree_
    return {
        "left": t.children_left.tolist(),
        "right": t.children_right.tolist(),
        "feature": t.feature.tolist(),
        "threshold": t.threshold.tolist(),
        # Gradient boosting overwrites leaf values with its line-search step,
        # so tree_.value IS what estimator.predict() returns.
        "value": t.value.reshape(-1).tolist(),
    }


def _tree_value(tree: dict, features: list) -> float:
    """Walk one exported tree to its leaf. sklearn's rule: <= goes left.

    The node budget is not defensive theatre — this walks data read back from
    a shared store, and a corrupted `left` array would otherwise spin forever
    inside the monitor's five-minute loop.
    """
    left, right = tree["left"], tree["right"]
    node = 0
    for _ in range(len(left)):
        if left[node] == _TREE_LEAF:
            return tree["value"][node]
        node = (left[node] if features[tree["feature"][node]] <= tree["threshold"][node]
                else right[node])
    raise ValueError("exported tree has no reachable leaf")


def _score_bundle(bundle: dict, features: list) -> float:
    """P(price goes UP) from an exported bundle. Pure arithmetic, no imports."""
    raw = bundle["intercept"] + bundle["learning_rate"] * sum(
        _tree_value(t, features) for t in bundle["trees"])
    # exp overflows to inf for |raw| far from zero; the limits are 0 and 1.
    if raw < -700:
        return 0.0
    if raw > 700:
        return 1.0
    return 1.0 / (1.0 + math.exp(-raw))


def _export_model(model, X) -> dict | None:
    """Export `model` as arithmetic, or None if it does not reproduce exactly.

    The intercept is recovered from sklearn's own decision_function rather
    than rebuilt from the class prior, so it stays correct whatever sklearn
    does internally — and the whole export is then replayed against
    predict_proba on the training set before it is trusted.
    """
    trees = [_export_tree(est) for est in model.estimators_[:, 0]]
    lr = float(model.learning_rate)

    first = list(X[0])
    intercept = float(model.decision_function(X[:1])[0]
                      - lr * sum(_tree_value(t, first) for t in trees))
    bundle = {"format": MODEL_FORMAT, "intercept": intercept,
              "learning_rate": lr, "trees": trees}

    expected = model.predict_proba(X)[:, 1]
    worst = max(abs(_score_bundle(bundle, list(row)) - p)
                for row, p in zip(X, expected))
    if worst > _EXPORT_TOLERANCE:
        print(f"[predictor] tree export disagrees with sklearn by {worst:.3g} "
              f"— refusing to store it (sklearn internals may have changed)")
        return None
    return bundle


def ml_available() -> bool:
    """True if the training extras (requirements-ml.txt) can be imported.

    Inference has been pure stdlib since models became plain numbers, so numpy
    and scikit-learn are installed only for the job that TRAINS. This lets a
    caller tell "nothing to train yet" apart from "the training job is missing
    its dependencies" — train_model returns None for both, so without it a
    broken install would just stop updating the models with no error anywhere.
    """
    try:
        import numpy  # noqa: F401
        from sklearn.ensemble import GradientBoostingClassifier  # noqa: F401
    except ImportError:
        return False
    return True


def train_model(history: list) -> dict | None:
    """Train gradient boosting models for 4h, 12h, 24h prediction.

    Returns the models exported as plain numbers (see _export_model), or None
    if there is not enough data — or if an export could not be verified.
    """
    try:
        import numpy as np
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

    # Feature rows do not depend on the horizon — only the LABELS do. Extract
    # each row once here instead of three times inside the horizon loop.
    widest = len(history) - min(horizons.values())
    feature_rows = {i: _extract_features(history, i) for i in range(26, widest)}

    for name, horizon in horizons.items():
        # Build samples in chronological order (do NOT shuffle — time series).
        X, y = [], []
        for i in range(26, len(history) - horizon):
            features = feature_rows.get(i)
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

        # A one-sided stretch of history gives every sample the same label, and
        # sklearn refuses to fit a single class. That is a plain ValueError out
        # of train_model, which in the monitor means a crash alert and a red run
        # at 3am every day until the price series changes shape. Skip the
        # horizon instead — the others may still be trainable.
        if len(set(y_tr.tolist())) < 2:
            print(f"[predictor] {name}: training window is all one class "
                  f"— skipping this horizon")
            continue

        try:
            eval_model = _make_model()
            eval_model.fit(X_tr, y_tr)
            oos_acc = round(eval_model.score(X_te, y_te) * 100, 1)
            train_acc = round(eval_model.score(X_tr, y_tr) * 100, 1)
        except ValueError as e:
            print(f"[predictor] {name}: hold-out fit failed ({e}) — skipping")
            continue

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
        try:
            model = _make_model()
            model.fit(X_arr, y_arr)
        except ValueError as e:
            print(f"[predictor] {name}: final fit failed ({e}) — skipping")
            continue

        bundle = _export_model(model, X_arr)
        if bundle is None:
            continue  # verification failed; better no model than a wrong one

        models[name] = {
            "trees": bundle,
            # Stamped so predict() can refuse a model trained on a different
            # feature vector — adding a feature silently invalidates a stored
            # model, and the resulting error is otherwise opaque.
            "n_features": X_arr.shape[1],
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
        # Bangkok time: the caller's "already trained today?" guard compares
        # this against a BKK date. A naive UTC stamp (what GitHub Actions
        # produces) is a calendar day behind at the 3am BKK training hour, so
        # the guard never matched and every 5-minute tick retrained.
        "last_trained": datetime.now(BANGKOK_TZ).isoformat(),
        "total_history": len(history),
        "feature_names": [
            "rsi", "price_vs_sma5", "price_vs_sma20", "sma_crossover",
            "macd", "macd_histogram", "bb_position", "momentum",
            "volatility", "hour", "weekday",
            "hours_to_event", "in_event_window",
            "change_1h", "change_4h",
        ],
    }


def predict(history: list, model_data: dict, lang: str | None = None) -> dict:
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
        result["ta_outlook"] = i18n.t("ta.strong_buy", lang)
    elif score > 0.3:
        result["ta_outlook"] = i18n.t("ta.buy", lang)
    elif score > -0.3:
        result["ta_outlook"] = i18n.t("ta.hold", lang)
    elif score > -1:
        result["ta_outlook"] = i18n.t("ta.wait", lang)
    else:
        result["ta_outlook"] = i18n.t("ta.overbought", lang)

    # ML predictions (if models exist)
    models_dict = model_data.get("models", {})
    if not models_dict or len(history) < 27:
        result["ml_available"] = False
        if len(history) >= 100:
            result["ml_note"] = i18n.t("predict.ml_ready", lang, n=len(history))
        else:
            result["ml_note"] = i18n.t("predict.ml_collecting", lang,
                                       n=len(history), need=100 - len(history))
        return result

    features = _extract_features(history, len(history) - 1)
    if features is None:
        result["ml_available"] = False
        return result

    features = list(features)
    result["ml_available"] = True
    result["predictions"] = {}

    for horizon_name, minfo in models_dict.items():
        try:
            trained_n = minfo.get("n_features")
            if trained_n is not None and trained_n != len(features):
                result["predictions"][horizon_name] = {
                    "stale": True,
                    "error": (f"trained on {trained_n} features, now "
                              f"{len(features)} — retrains at 3am BKK"),
                }
                continue

            bundle = minfo.get("trees")
            if not bundle:
                # A pre-switchover pickle. Deliberately NOT loaded: unpickling
                # is the code-execution path this format exists to remove.
                # Tonight's 3am retrain replaces it; until then, TA only.
                result["predictions"][horizon_name] = {
                    "stale": True,
                    "error": "stored in the old pickle format — retrains at 3am BKK",
                }
                continue

            proba_up = _score_bundle(bundle, features)
            direction = "UP" if proba_up >= 0.5 else "DOWN"
            result["predictions"][horizon_name] = {
                "direction": direction,
                "confidence": round(max(proba_up, 1.0 - proba_up) * 100, 1),
                "model_accuracy": minfo.get("accuracy"),
                "oos_accuracy": minfo.get("oos_accuracy", minfo.get("accuracy")),
                "baseline_accuracy": minfo.get("baseline_accuracy"),
                "has_edge": minfo.get("has_edge", False),
                "training_samples": minfo.get("samples"),
            }
        except Exception as e:
            result["predictions"][horizon_name] = {"error": str(e)}

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
            result["combined_outlook"] = i18n.t("ta.no_edge", lang)
        else:
            up_votes = sum(1 for p in edged if p.get("direction") == "UP")
            total = len(edged)
            if up_votes > total / 2:
                result["combined_outlook"] = i18n.t("ta.bullish", lang)
            elif up_votes < total / 2:
                result["combined_outlook"] = i18n.t("ta.bearish", lang)
            else:
                result["combined_outlook"] = i18n.t("ta.mixed", lang)

    return result


# ── Prediction Accuracy Tracker ─────────────────────────────────
# Every recorded ML prediction is later scored against what the price actually
# did, giving a LIVE hit-rate — far more meaningful than backtest numbers.

PREDICTION_LOG_CAP = 300  # keep the Gist file bounded


def record_predictions(model_data: dict, prediction: dict, current_price: float,
                       now_iso: str | None = None) -> dict:
    """Append the current ML predictions to model_data["predictions"]."""
    preds = model_data.setdefault("predictions", [])
    if now_iso is None:
        now_iso = datetime.now().astimezone().isoformat()
    for horizon, p in (prediction.get("predictions") or {}).items():
        if "direction" not in p:
            continue
        try:
            hours = int(horizon.rstrip("h"))
        except ValueError:
            continue
        preds.append({
            "ts": now_iso,
            "horizon": horizon,
            "hours": hours,
            "direction": p["direction"],
            "price_at": current_price,
            "confidence": p.get("confidence"),
            "resolved": False,
        })
    model_data["predictions"] = preds[-PREDICTION_LOG_CAP:]
    return model_data


def resolve_predictions(model_data: dict, history: list) -> bool:
    """Score matured predictions against actual prices. Returns True if changed.

    A prediction matures `hours` after it was made; the first history point at
    or after that target decides UP/DOWN. If the nearest data point is too far
    past the target (data gap > 6h), the prediction is voided, not scored.
    """
    preds = model_data.get("predictions", [])
    if not preds or not history:
        return False

    hist = []
    for h in history:
        try:
            if h.get("thb_gram") is None:
                continue
            hist.append((datetime.fromisoformat(h["ts"]), h["thb_gram"]))
        except (KeyError, ValueError, TypeError):
            continue
    if not hist:
        return False

    changed = False
    for p in preds:
        if p.get("resolved"):
            continue
        try:
            t0 = datetime.fromisoformat(p["ts"])
        except (KeyError, ValueError, TypeError):
            p["resolved"] = True
            p["void"] = True
            changed = True
            continue
        target = t0 + timedelta(hours=p.get("hours", 24))
        future = [(t, price) for t, price in hist if t >= target]
        if not future:
            continue  # not matured yet
        t_actual, price_actual = future[0]
        p["resolved"] = True
        changed = True
        if (t_actual - target) > timedelta(hours=6):
            p["void"] = True  # data gap too large to score fairly
            continue
        actual_dir = "UP" if price_actual >= p["price_at"] else "DOWN"
        p["actual"] = actual_dir
        p["actual_price"] = price_actual
        p["correct"] = (actual_dir == p["direction"])
    return changed


def prediction_hit_rates(model_data: dict) -> dict:
    """Live accuracy per horizon: {horizon: {"n", "correct", "hit_pct"}}."""
    out = {}
    for p in model_data.get("predictions", []):
        if not p.get("resolved") or p.get("void") or "correct" not in p:
            continue
        s = out.setdefault(p.get("horizon", "?"), {"n": 0, "correct": 0})
        s["n"] += 1
        s["correct"] += 1 if p["correct"] else 0
    for s in out.values():
        s["hit_pct"] = round(s["correct"] / s["n"] * 100, 1) if s["n"] else None
    return out


# ── Trend Analysis ──────────────────────────────────────────────

def get_trend_summary(history: list) -> dict:
    """Compute multi-timeframe trend summary."""
    prices = [h["thb_gram"] for h in priced_points(history)]
    if len(prices) < 2:
        return {"error": "Not enough data"}

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


def format_prediction_message(prediction: dict, lang: str | None = None) -> str:
    """Format prediction results into a Telegram-friendly message.

    Indicator names (RSI, MACD, Bollinger) stay untranslated on purpose — they
    are read as symbols in every locale.
    """
    lines = [i18n.t("predict.title", lang), "━━━━━━━━━━━━━━━"]

    ta = prediction.get("technical_analysis", {})

    # Current price context
    if ta.get("current_price"):
        lines.append(i18n.t("predict.current", lang,
                            price=ta["current_price"],
                            usd=usd_oz_suffix(prediction.get("usd_oz"))))

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
        lines.append(i18n.t("predict.tech_signal", lang,
                            signal=ta["overall_signal"], score=ta.get("buy_score", "?")))

    # ML Predictions
    if prediction.get("predictions"):
        lines.append("")
        lines.append(i18n.t("predict.ml_header", lang))
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

        if any(p.get("stale") for p in prediction["predictions"].values()
               if isinstance(p, dict)):
            lines.append(i18n.t("predict.models_stale", lang))

        if prediction.get("ml_has_edge") is False:
            lines.append(i18n.t("predict.no_edge_note", lang))

    # Live (real-world) hit-rate from the prediction tracker
    rates = prediction.get("hit_rates") or {}
    scored = {h: s for h, s in rates.items() if s.get("n")}
    if scored:
        parts = [
            f"{h}: {s['hit_pct']}% (n={s['n']})"
            for h, s in sorted(scored.items())
        ]
        lines.append(i18n.t("predict.live_hit_rate", lang, parts=" | ".join(parts)))

    # Final Outlook
    lines.append("━━━━━━━━━━━━━━━")
    if prediction.get("combined_outlook"):
        lines.append(f"💡 {prediction['combined_outlook']}")
    if prediction.get("ta_outlook"):
        lines.append(f"📋 {prediction['ta_outlook']}")

    if not prediction.get("ml_available"):
        lines.append(i18n.t("predict.ml_note", lang,
                            note=prediction.get("ml_note", "")))

    return "\n".join(lines)
