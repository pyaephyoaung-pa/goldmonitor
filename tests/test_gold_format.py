from gold_format import fmt, gold_breakdown, BAHT_WEIGHT_GRAMS


def test_fmt_rounds_and_groups():
    assert fmt(12345.6) == "฿12,346"
    assert fmt(0) == "฿0"
    assert fmt(1000000) == "฿1,000,000"


def test_gold_breakdown_pure_baht_weight():
    gb = gold_breakdown(1000.0)
    assert gb["gram_9999"] == 1000.0
    assert gb["baht_9999"] == round(1000.0 * BAHT_WEIGHT_GRAMS, 2)


def test_gold_breakdown_9650_is_lower_than_pure():
    gb = gold_breakdown(1000.0)
    assert gb["gram_9650"] < gb["gram_9999"]
    # 96.5/99.99 ratio
    assert abs(gb["gram_9650"] - 1000.0 * (96.50 / 99.99)) < 0.01
    assert gb["baht_9650"] == round(gb["gram_9650"] * BAHT_WEIGHT_GRAMS, 2)
