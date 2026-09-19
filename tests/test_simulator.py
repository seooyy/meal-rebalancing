from dataclasses import replace
from decimal import Decimal

import pytest

from src.simulator import Alternative, Menu, required_volume, simulate, store_contribution


def menu(id="a", price=10000, cost=4000, volume=100):
    return Menu(id, id, price, dict.fromkeys(("low", "base", "high"), cost), volume)


def option(**kw):
    return Alternative("test", "test", "구성 재설계", "a", **kw)


@pytest.mark.parametrize("cm,unit,setup,want", [
    (600000, 6000, 0, 100), (600000, 5000, 0, 120), (600000, 5700, 0, 106),
    (600000, 5999, 0, 101), (600000, 0, 0, None), (600000, -100, 0, None),
    (600000, 6000, 60000, 110), (600000, 0.01, 0, 60000000),
    (0, 10, 0, 0), (-100, 10, 0, 0), (0.3, 0.1, 0, 3),
])
def test_contract_and_decimal_boundaries(cm, unit, setup, want):
    assert required_volume(cm, unit, setup) == want


@pytest.mark.parametrize("args", [(float("nan"), 1), (1, float("inf")), (1, 1, -1), (True, 1)])
def test_bad_scalar_inputs(args):
    with pytest.raises(ValueError):
        required_volume(*args)


def test_manual_store_cannibalization_and_setup():
    # Before: 100*6000 + 50*4000 + 20*3000 = 860000.
    # Other menus after 10%/25% loss: 45*4000 + 15*3000 = 225000.
    # Target after discount: 5000. ceil((860000+60000-225000)/5000)=139.
    menus = [menu(), menu("b", 6000, 2000, 50), menu("c", 4000, 1000, 20)]
    rows = simulate(menus, option(price_delta=-1000, setup_cost=60000, cannibalization={"b": .1, "c": .25}), operating_days=1)
    assert rows[1]["base_store_cm"] == 860000
    assert rows[1]["required_volume"] == 139
    assert rows[1]["after_store_cm_after_setup"] == 665000
    assert store_contribution(menus) == 860000


def test_period_setup_is_charged_once():
    assert simulate([menu()], option(setup_cost=60000), operating_days=1)[1]["required_volume"] == 110
    assert simulate([menu()], option(setup_cost=60000), operating_days=2)[1]["required_volume"] == 210
    with pytest.raises(ValueError):
        simulate([menu()], option(), period_weeks=1, operating_days=8)


def test_application_rate_fee_and_labor():
    m = replace(menu(), fee_rate=.1, packaging=100, variable_labor=100)
    # Base 4800; 50% full price + 50% discounted (3900 - extra labor 100) = 4300.
    row = simulate([m], option(price_delta=-1000, application_rate=.5, extra_labor_cost=100), operating_days=1)[1]
    assert row["unit_cm"] == 4300
    assert row["required_volume"] == 112


def test_price_shock_changes_after_costs_only():
    menus = [menu(), menu("b", 6000, 2000, 50)]
    row = simulate(menus, option(), operating_days=1,
                   scenario_food_costs={"b": dict.fromkeys(("low", "base", "high"), 3000)})[1]
    assert row["base_store_cm"] == 800000
    assert row["required_volume"] == 109  # ceil((800000 - 150000) / 6000)


def test_missing_volume_never_invents_currency_or_setup_allocation():
    row = simulate([menu(volume=None)], option(price_delta=-1000, setup_cost=60000))[1]
    assert row["required_volume"] is None
    assert row["required_index"] == 120
    assert row["increase_pct"] == 20
    assert row["base_store_cm"] is None
    assert row["after_store_cm_after_setup"] is None
    assert any("도입비용 포함" in w for w in row["warnings"])


def test_zero_volume_and_zero_cm():
    rows = simulate([menu(volume=0)], option(), operating_days=1)
    assert rows[1]["required_volume"] == 0
    assert rows[1]["increase_pct"] is None
    row = simulate([menu()], option(price_delta=-6000))[1]
    assert row["required_volume"] is None
    assert "달성 불가" in row["status"]


def test_low_base_high():
    m = replace(menu(), food_cost={"low": 3000, "base": 4000, "high": 5000})
    rows = simulate([m], option(price_delta=-1000), operating_days=1)
    assert [r["required_volume"] for r in rows] == [117, 120, 125]


@pytest.mark.parametrize("changes", [{"price": -1}, {"daily_volume": -1}, {"fee_rate": 1.1},
                                     {"food_cost": {"low": 5, "base": 3, "high": 4}}, {"tags": {"price": "unknown"}}])
def test_invalid_menu(changes):
    with pytest.raises(ValueError):
        replace(menu(), **changes)


@pytest.mark.parametrize("changes", [{"application_rate": 1.1}, {"cannibalization": {"b": -1}},
                                     {"setup_cost": -1}, {"extra_minutes": float("nan")}])
def test_invalid_alternative(changes):
    with pytest.raises(ValueError):
        option(**changes)


def test_bad_ids_and_negative_changed_cost():
    with pytest.raises(ValueError):
        simulate([menu(), menu()], option())
    with pytest.raises(ValueError):
        simulate([menu()], option(food_cost_delta=-5000))
    with pytest.raises(ValueError):
        simulate([menu()], option(cannibalization={"a": .1}))


def test_more_other_contribution_can_eliminate_target_need():
    menus = [menu(), menu("b", 20000, 10000, 100)]
    row = simulate(menus, option(), operating_days=1,
                   scenario_food_costs={"b": dict.fromkeys(("low", "base", "high"), 0)})[1]
    assert row["required_volume"] == 0
