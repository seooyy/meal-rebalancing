import pytest

from src.store_profile import (profile_from_form, profile_to_simulator_form,
                               recommendation_candidates, simulator_menus)
from src.screen2 import evaluate_profile_candidates


def form(**changes):
    base = {"buz": "8001", "goal": "sales", "menu_name": "대표 메뉴", "price": 10000,
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


def test_sales_candidates_explain_budget_constraint():
    profile = profile_from_form(form(experiment_budget=0))
    candidate = recommendation_candidates(profile)[0]
    assert candidate["option_id"] == "visibility"
    assert candidate["warning"]


def test_profile_facts_are_mapped_to_simulator_without_inventing_volume():
    profile = profile_from_form(form(daily_volume="", food_cost_rate=.4))
    result = profile_to_simulator_form(profile, "rice_set")
    assert result["rice_set.daily_volume"] == ""
    assert result["rice_set.food_cost.base"] == 4000


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
