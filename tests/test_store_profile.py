import pytest

from src.store_profile import profile_from_form, simulator_menus
from src.screen2 import evaluate_profile_candidates


def form(**changes):
    base = {"buz": "8001", "menu_name": "대표 메뉴", "price": 10000,
            "daily_volume": 20, "operating_days": 24, "price_source": "rate",
            "food_cost_rate": .35, "experiment_budget": 300000, "extra_minutes_capacity": 1}
    return {**base, **changes}


def test_rate_requires_rate_value():
    with pytest.raises(ValueError, match="원가율"):
        profile_from_form(form(food_cost_rate=""))


def test_multiple_menu_form_requires_a_menu_name():
    with pytest.raises(ValueError, match="메뉴를 하나"):
        profile_from_form(form(menus=[{"name": ""}]))


def test_recipe_cost_mode_requires_a_recipe_for_every_menu():
    with pytest.raises(ValueError, match="레시피 원가"):
        profile_from_form(form(price_source="actual", food_cost_rate="", menus=[
            {"id": "a", "name": "A", "price": 10000, "daily_volume": 10},
        ]))


def test_multiple_menus_use_recipe_purchase_prices_for_food_cost():
    profile = profile_from_form(form(menus=[
        {"id": "a", "name": "A", "price": 10000, "daily_volume": 10,
         "ingredients": [{"name": "고기", "quantity": .2, "unit": "kg", "purchase_price": 12000}]},
        {"id": "b", "name": "B", "price": 8000, "daily_volume": 5,
         "ingredients": [{"name": "면", "quantity": 1, "unit": "개", "purchase_price": 800}]},
    ]))
    menus = simulator_menus(profile)
    assert [m.name for m in menus] == ["A", "B"]
    assert menus[0].food_cost["base"] == 2400


def test_menu_volume_can_be_unknown_and_recipe_range_is_not_forced_to_twenty_percent():
    profile = profile_from_form(form(menus=[
        {"id": "a", "name": "A", "price": 10000, "daily_volume": "", "cost_source": "recipe",
         "ingredients": [{"name": "고기", "quantity": .2, "unit": "kg", "purchase_price": 12000,
                          "purchase_price_low": 11000, "purchase_price_high": 15000}]},
    ]))
    menu = simulator_menus(profile)[0]
    assert menu.daily_volume is None
    assert menu.food_cost == {"low": 2200, "base": 2400, "high": 3000}


def test_public_price_selection_overrides_manual_price_and_marks_provenance(monkeypatch):
    monkeypatch.setattr("src.store_profile.public_price_range", lambda ingredient_id: {
        "low": 2000, "base": 3000, "high": 4000, "unit": "kg", "name": "쌀",
    })
    profile = profile_from_form(form(menus=[
        {"id": "a", "name": "A", "price": 10000, "daily_volume": 10, "cost_source": "recipe",
         "ingredients": [{"name": "쌀", "quantity": .1, "unit": "kg", "purchase_price": 9999,
                          "public_price_id": "rice"}]},
    ]))
    menu = simulator_menus(profile)[0]
    assert menu.food_cost == {"low": 200, "base": 300, "high": 400}
    assert menu.tags["food_cost.base"] == "추정값"


def test_public_price_mode_requires_an_explicit_item():
    with pytest.raises(ValueError, match="공개가격 품목을 선택"):
        profile_from_form(form(menus=[
            {"id": "a", "name": "A", "price": 10000, "daily_volume": 10, "cost_source": "recipe",
             "ingredients": [{"name": "쌀", "quantity": .1, "unit": "kg", "purchase_price": 3000,
                              "price_mode": "public", "public_price_id": ""}]},
        ]))


def test_each_menu_can_use_its_own_cost_source():
    profile = profile_from_form(form(price_source="unknown", food_cost_rate="", menus=[
        {"id": "a", "name": "A", "price": 10000, "daily_volume": 10,
         "cost_source": "rate", "food_cost_rate": .4},
        {"id": "b", "name": "B", "price": 8000, "daily_volume": 5,
         "cost_source": "unknown"},
    ]))
    menus = simulator_menus(profile)
    assert [menu.food_cost["base"] for menu in menus] == [4000, 2800]


def test_profile_candidate_calculation_uses_all_saved_menus_and_one_target():
    profile = profile_from_form(form(menus=[
        {"id": "a", "name": "A", "price": 10000, "daily_volume": 10},
        {"id": "b", "name": "B", "price": 8000, "daily_volume": 5},
    ]))
    result = evaluate_profile_candidates(profile, "b")
    assert len(result["results"]) == 12  # 4 alternatives x 3 cost ranges
    assert {row["target_menu"] for row in result["results"]} == {"b"}
    assert {menu["id"] for menu in result["store"]["menus"]} == {"a", "b"}
