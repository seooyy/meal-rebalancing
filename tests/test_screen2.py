import pytest

from src.screen2 import evaluate_inputs


@pytest.mark.parametrize("buz", ["8001", "8006"])
def test_each_demo_has_three_menus_three_alternatives_three_ranges(buz):
    result = evaluate_inputs({"buz": buz})
    assert len(result["store"]["menus"]) == 3
    assert len(result["results"]) == 9
    assert {row["cost_level"] for row in result["results"]} == {"low", "base", "high"}
    assert all(row["required_volume"] > 0 for row in result["results"])


def test_owner_inputs_drive_calculation_and_tags():
    result = evaluate_inputs({"rice_set.price": "12000", "rice_set.price.tag": "관측값", "own_store": "yes"})
    assert result["store"]["menus"][0]["price"] == 12000
    assert not result["store"]["is_demo"]
    assert "관측값" in result["results"][0]["tags"]


def test_price_scenario_changes_required_volume_without_changing_baseline():
    base = evaluate_inputs({"pricing": "recipe"}, daily_rows=[])
    changed = evaluate_inputs({"pricing": "recipe", "scenario": "custom", "change.pork": ".5"}, daily_rows=[])
    assert changed["results"][1]["required_volume"] > base["results"][1]["required_volume"]
    assert base["results"][1]["base_store_cm"] == changed["results"][1]["base_store_cm"]
    assert changed["prices"]["food_costs"]["noodle"] == base["prices"]["food_costs"]["noodle"]


def test_missing_volume_and_scenario_mode():
    result = evaluate_inputs({"rice_set.daily_volume": ""})
    assert all(row["required_volume"] is None for row in result["results"])
    with pytest.raises(ValueError, match="레시피"):
        evaluate_inputs({"scenario": "rise", "pricing": "manual"})


def test_nonselected_candidate_changes_are_retained():
    default = evaluate_inputs()
    changed = evaluate_inputs({"visibility.setup_cost": "600000"})
    assert changed["results"][7]["required_volume"] > default["results"][7]["required_volume"]


def test_fourth_candidate_is_available_when_selected():
    result = evaluate_inputs({"option": "ordering"})
    assert len(result["results"]) == 12
    assert result["results"][-1]["alternative_id"] == "ordering"


def test_streamlit_component_imports_without_starting_server():
    from src.screen2 import render_screen2
    assert callable(render_screen2)
