import goldapi


def test_spot_falls_back_to_secondary(monkeypatch):
    monkeypatch.setattr(goldapi, "_spot_from_twelve_data",
                        lambda: (_ for _ in ()).throw(RuntimeError("rate limit")))
    monkeypatch.setattr(goldapi, "_spot_from_gold_api", lambda: 2345.6)
    # rebuild the source tuple so it points at the patched callables
    monkeypatch.setattr(goldapi, "_SPOT_SOURCES",
                        (("twelve_data", goldapi._spot_from_twelve_data),
                         ("gold-api.com", goldapi._spot_from_gold_api)))
    assert goldapi.fetch_spot_usd() == 2345.6


def test_spot_returns_none_when_all_fail(monkeypatch):
    boom = lambda: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setattr(goldapi, "_SPOT_SOURCES",
                        (("a", boom), ("b", boom)))
    assert goldapi.fetch_spot_usd() is None


def test_fx_falls_back(monkeypatch):
    monkeypatch.setattr(goldapi, "_FX_SOURCES",
                        (("primary", lambda: (_ for _ in ()).throw(RuntimeError())),
                         ("fallback", lambda: 34.5)))
    assert goldapi.fetch_thb_rate() == 34.5


def test_get_gold_price_computes_thb_gram(monkeypatch):
    monkeypatch.setattr(goldapi, "fetch_spot_usd", lambda: 2000.0)
    monkeypatch.setattr(goldapi, "fetch_thb_rate", lambda: 31.1035)
    thb_gram, usd_oz, rate = goldapi.get_gold_price()
    # 2000 * 31.1035 / 31.1035 == 2000 per oz -> per gram = 2000/31.1035... wait
    # thb_gram = usd_oz * rate / 31.1035 = 2000 * 31.1035 / 31.1035 = 2000
    assert usd_oz == 2000.0
    assert rate == 31.1
    assert thb_gram == 2000.0


def test_get_gold_price_none_on_failure(monkeypatch):
    monkeypatch.setattr(goldapi, "fetch_spot_usd", lambda: None)
    monkeypatch.setattr(goldapi, "fetch_thb_rate", lambda: None)
    # avoid real sleeps during retries
    monkeypatch.setattr(goldapi.time, "sleep", lambda *_: None)
    assert goldapi.get_gold_price(retries=1) == (None, None, None)
