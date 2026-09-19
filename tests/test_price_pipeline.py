import json
from datetime import date
from pathlib import Path

import pytest
import requests

from src.collect_price import (AuthenticationError, ENDPOINT, PriceError, collect, normalize,
                               parse_page, read_mapping, request_page)
from src.price_scenario import industry_coverage, price_series, recipe_costs
from src.simulator import Menu


MAPPING = {"ingredient_id": "rice", "name": "쌀", "se_cd": "02", "ctgry_cd": "100", "item_cd": "111",
           "vrty_cd": "01", "grd_cd": "04", "unit": "kg", "unit_sz": "20", "recipe_unit": "kg", "recipe_units_per_package": "20"}


def raw(day="20260101", price="60,000", **kw):
    return {**{k: MAPPING[k] for k in ("se_cd", "ctgry_cd", "item_cd", "vrty_cd", "grd_cd", "unit", "unit_sz")},
            "exmn_ymd": day, "exmn_dd_prc": price, "sgg_cd": "2300", "mrkt_cd": "001", **kw}


def page(items, total=None, code="00"):
    return {"response": {"header": {"resultCode": code}, "body": {"totalCount": len(items) if total is None else total, "items": {"item": items}}}}


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def test_normalization_units_leading_zero_duplicates_and_missing_days():
    rows, audit = normalize([raw(), raw(), raw("20260102", "-"), raw("20260103", unit="개")], [MAPPING], date(2026, 1, 1), date(2026, 1, 4))
    assert rows[0]["unit_price"] == 3000
    assert rows[0]["vrty_cd"] == "01"
    assert audit["duplicates"] == 1
    assert len(audit["rejected"]) == 2
    assert audit["quality"][0]["missing_rate"] == .75


def test_conflicting_duplicate_is_not_silently_averaged():
    with pytest.raises(PriceError):
        normalize([raw(), raw(price="50000")], [MAPPING])


def test_paging_cache_restart_and_no_key_in_files(tmp_path):
    session = Session([Response(page([raw()], 2)), Response(page([raw("20260102")], 2))])
    rows, failures = collect([MAPPING], key="fake-secret", raw_dir=tmp_path, start=date(2026, 1, 1), end=date(2026, 1, 31), session=session, sleep=lambda _: None)
    assert len(rows) == 2 and failures == []
    assert session.calls[1][1]["params"]["pageNo"] == 2
    assert session.calls[0][1]["params"]["numOfRows"] == 1000
    cached, failures = collect([MAPPING], key="fake-secret", raw_dir=tmp_path, start=date(2026, 1, 1), end=date(2026, 1, 31), session=Session([]), sleep=lambda _: None)
    assert cached == rows and failures == []
    assert all("fake-secret" not in p.read_text(encoding="utf-8") for p in tmp_path.rglob("*.json"))


def test_failure_does_not_mark_partition_complete(tmp_path):
    session = Session([Response(page([raw()], 2)), Response(page([], 2))])
    rows, failures = collect([MAPPING], key="key", raw_dir=tmp_path, start=date(2026, 1, 1), end=date(2026, 1, 31), session=session, sleep=lambda _: None)
    assert rows == [] and len(failures) == 1
    assert not list(tmp_path.rglob("complete.json"))
    assert not list(tmp_path.rglob("00002.json"))
    retry = Session([Response(page([raw("20260102")], 2))])
    rows, failures = collect([MAPPING], key="key", raw_dir=tmp_path, start=date(2026, 1, 1), end=date(2026, 1, 31), session=retry, sleep=lambda _: None)
    assert len(rows) == 2 and failures == []
    assert len(retry.calls) == 1


def test_auth_stops_and_error_does_not_include_key(tmp_path):
    session = Session([Response({}, 403)])
    with pytest.raises(AuthenticationError) as exc:
        collect([MAPPING], key="secret-for-test", raw_dir=tmp_path, session=session, sleep=lambda _: None)
    assert "secret-for-test" not in str(exc.value)
    assert len(session.calls) == 1


def test_retry_is_bounded_and_sanitized():
    session = Session([requests.ConnectionError("serviceKey=secret")] * 4)
    with pytest.raises(PriceError) as exc:
        request_page(session, ENDPOINT, "secret", {}, sleep=lambda _: None)
    assert "secret" not in str(exc.value)
    assert len(session.calls) == 4
    session = Session([Response({}, 429), Response(page([]))])
    assert request_page(session, ENDPOINT, "key", {}, sleep=lambda _: None)
    assert len(session.calls) == 2


def test_endpoint_and_missing_key_fail_before_network(tmp_path):
    with pytest.raises(AuthenticationError):
        collect([MAPPING], key=None, raw_dir=tmp_path, session=Session([]))
    with pytest.raises(PriceError):
        request_page(Session([]), "https://example.com", "key", {})


def test_schema_and_non_success_result():
    with pytest.raises(PriceError):
        parse_page({"unexpected": []})
    with pytest.raises(AuthenticationError):
        parse_page(page([], code="30"))


def daily_prices():
    rows, _ = normalize([raw("20260101", "40000"), raw("20260102", "60000"), raw("20260103", "80000")], [MAPPING])
    return rows


RECIPE = {"buz": "8001", "ingredients": {
    "rice": {"unit": "kg", "assumed_unit_price": {"low": 2000, "base": 3000, "high": 4000}},
    "cheese": {"unit": "kg", "assumed_unit_price": {"low": 8000, "base": 10000, "high": 12000}}},
    "menus": {"a": {"rice": .1}, "b": {"cheese": .1}}}


def test_quantiles_and_local_fallback_are_explicit():
    s = price_series(daily_prices(), MAPPING, region_code="9999", start=date(2026, 1, 1), end=date(2026, 1, 3))
    assert s["base"] == 3000
    assert s["rise"] == 3800
    assert s["fall"] == 2200
    assert s["national_fallback"]
    assert s["missing_rate"] == 0


def test_sparse_series_weekly_without_zero_fill():
    s = price_series(daily_prices(), MAPPING)
    assert s["cadence"] == "weekly"
    assert s["base"] == 3000


def test_local_series_uses_one_market_and_does_not_mix_grade_or_units():
    rows = daily_prices()
    rows += [{**rows[0], "mrkt_cd": "002", "unit_price": 9000},
             {**rows[0], "grd_cd": "05", "unit_price": 99999},
             {**rows[0], "unit_sz": "10", "unit_price": 99999}]
    s = price_series(rows, MAPPING, region_code="2300", start=date(2026, 1, 1), end=date(2026, 1, 3))
    assert s["market_code"] == "001" and s["base"] == 3000
    assert not s["national_fallback"]


def test_actual_price_priority_and_relative_shocks():
    r = recipe_costs(RECIPE, daily_prices(), [MAPPING], scenario="rise", actual_prices={"rice": 6000},
                     start=date(2026, 1, 1), end=date(2026, 1, 3))
    assert r["food_costs"]["a"]["base"] == pytest.approx(760)
    assert r["details"][0]["source"] == "관측값"
    assert r["coverage"][0]["actual_coverage"] == 1
    assert r["coverage"][0]["public_coverage"] == 0
    assert r["food_costs"]["b"]["base"] == 1000  # cheese unsupported: unchanged
    assert "자동 변동 미적용" in r["details"][1]["warning"]


def test_custom_change_only_affects_matching_menu():
    r = recipe_costs(RECIPE, [], [MAPPING], scenario="custom", changes={"rice": .1})
    assert r["food_costs"]["a"]["base"] == pytest.approx(330)
    assert r["food_costs"]["b"]["base"] == 1000
    assert all(c["badge"] == "참고 수준" for c in r["coverage"])


def test_coverage_is_cost_weighted_and_not_number_of_ingredients():
    recipe = {**RECIPE, "menus": {"a": {"rice": .1, "cheese": .1}}}
    r = recipe_costs(recipe, daily_prices(), [MAPPING], start=date(2026, 1, 1), end=date(2026, 1, 3))
    assert r["coverage"][0]["public_coverage"] == pytest.approx(300 / 1300)
    m = Menu("a", "a", 10000, dict.fromkeys(("low", "base", "high"), 1300), None)
    assert industry_coverage(r["coverage"], [m])["public_coverage"] is None


@pytest.mark.parametrize("kwargs", [{"changes": {"rice": -1.1}}, {"actual_prices": {"rice": -1}}, {"changes": {"unknown": .1}}])
def test_bad_price_inputs(kwargs):
    with pytest.raises(ValueError):
        recipe_costs(RECIPE, [], [MAPPING], **kwargs)


def test_real_mapping_codes_match_supplied_workbook():
    import openpyxl
    from src.collect_price import ROOT
    codebook = next(p for p in (ROOT / "data").rglob("*.xlsx") if "API" in str(p) and "API" not in p.name)
    wb = openpyxl.load_workbook(codebook, read_only=True, data_only=True)
    valid = {tuple(str(x) for x in row[:4]) for row in list(wb["등급코드"].values)[1:]}
    wb.close()
    for mapping in read_mapping():
        assert tuple(mapping[k] for k in ("ctgry_cd", "item_cd", "vrty_cd", "grd_cd")) in valid
