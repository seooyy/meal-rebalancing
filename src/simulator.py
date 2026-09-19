"""Menu contribution calculator. No card data, web framework or network required."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Mapping

NOTICE = "필요 판매량은 달성 조건이며 판매 예측이 아니다"
TAGS = {"관측값", "추정값", "가정값"}
COST_LEVELS = ("low", "base", "high")


def number(value, name="value", *, minimum=None, maximum=None) -> Decimal:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name}: 유한한 숫자를 입력하세요") from None
    if not result.is_finite():
        raise ValueError(f"{name}: 유한한 숫자를 입력하세요")
    if minimum is not None and result < Decimal(str(minimum)):
        raise ValueError(f"{name}: {minimum} 이상이어야 합니다")
    if maximum is not None and result > Decimal(str(maximum)):
        raise ValueError(f"{name}: {maximum} 이하여야 합니다")
    return result


def required_volume(base_cm: float, unit_cm: float, setup_cost: float = 0) -> int | None:
    """ceil((base_cm + setup_cost) / unit_cm), clamped to zero; None if cm <= 0."""
    base = number(base_cm, "base_cm")
    unit = number(unit_cm, "unit_cm")
    setup = number(setup_cost, "setup_cost", minimum=0)
    if unit <= 0:
        return None
    return max(0, int(((base + setup) / unit).to_integral_value(rounding=ROUND_CEILING)))


@dataclass(frozen=True)
class Menu:
    id: str
    name: str
    price: float
    food_cost: Mapping[str, float]
    daily_volume: float | None = None
    packaging: float = 0
    fee_rate: float = 0
    variable_labor: float = 0
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.id or not self.name:
            raise ValueError("메뉴 ID와 이름이 필요합니다")
        for name in ("price", "packaging", "variable_labor"):
            number(getattr(self, name), name, minimum=0)
        number(self.fee_rate, "fee_rate", minimum=0, maximum=1)
        if self.daily_volume is not None:
            number(self.daily_volume, "daily_volume", minimum=0)
        costs = [number(self.food_cost[k], f"food_cost.{k}", minimum=0) for k in COST_LEVELS]
        if costs != sorted(costs):
            raise ValueError("식재료비는 낮음 ≤ 기준 ≤ 높음이어야 합니다")
        if any(t not in TAGS for t in self.tags.values()):
            raise ValueError("입력 태그는 관측값/추정값/가정값 중 하나입니다")

    def unit_cm(self, level="base", *, price=None, food_cost=None) -> Decimal:
        p = number(self.price if price is None else price, "price", minimum=0)
        food = number(self.food_cost[level] if food_cost is None else food_cost, "food_cost", minimum=0)
        return p * (1 - number(self.fee_rate)) - food - number(self.packaging) - number(self.variable_labor)


@dataclass(frozen=True)
class Alternative:
    id: str
    name: str
    kind: str
    target_menu: str
    price_delta: float = 0
    food_cost_delta: float = 0
    application_rate: float = 1
    setup_cost: float = 0
    extra_minutes: float = 0
    extra_labor_cost: float = 0
    cannibalization: Mapping[str, float] = field(default_factory=dict)
    tags: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        for name in ("price_delta", "food_cost_delta"):
            number(getattr(self, name), name)
        for name in ("setup_cost", "extra_minutes", "extra_labor_cost"):
            number(getattr(self, name), name, minimum=0)
        number(self.application_rate, "application_rate", minimum=0, maximum=1)
        for rate in self.cannibalization.values():
            number(rate, "cannibalization", minimum=0, maximum=1)
        if any(t not in TAGS for t in self.tags.values()):
            raise ValueError("대안 태그가 유효하지 않습니다")


def store_contribution(menus: list[Menu], level="base", operating_days=1) -> float | None:
    days = number(operating_days, "operating_days", minimum=1)
    if any(m.daily_volume is None for m in menus):
        return None
    return float(sum((m.unit_cm(level) * number(m.daily_volume) * days for m in menus), Decimal(0)))


def simulate(menus: list[Menu], alternative: Alternative, *, operating_days=24,
             period_weeks=4, scenario_food_costs: Mapping[str, Mapping[str, float]] | None = None,
             context: Mapping | None = None) -> list[dict]:
    """Three cost-range results. Price scenarios affect AFTER costs, never the baseline.

    Cannibalization is the fraction of each other menu's baseline volume lost over
    the evaluation period, not a per-new-sale coefficient. Extra target labor is
    per affected serving. Unknown volumes produce a target-only index comparison.
    """
    days = number(operating_days, "operating_days", minimum=1)
    weeks = number(period_weeks, "period_weeks", minimum=1)
    if days != int(days) or days > weeks * 7:
        raise ValueError("영업일은 평가기간 내의 양의 정수여야 합니다")
    by_id = {m.id: m for m in menus}
    if not menus or len(by_id) != len(menus) or alternative.target_menu not in by_id:
        raise ValueError("중복 없는 메뉴와 유효한 대상 메뉴가 필요합니다")
    if any(k not in by_id or k == alternative.target_menu for k in alternative.cannibalization):
        raise ValueError("잠식률은 다른 메뉴 ID로 지정하세요")
    scenario_food_costs = scenario_food_costs or {}
    if set(scenario_food_costs) - set(by_id):
        raise ValueError("가격 시나리오에 알 수 없는 메뉴가 있습니다")
    target = by_id[alternative.target_menu]
    actual = all(m.daily_volume is not None for m in menus)
    rate = number(alternative.application_rate)
    rows = []
    for level in COST_LEVELS:
        after = {}
        for m in menus:
            food = scenario_food_costs.get(m.id, m.food_cost)[level]
            after[m.id] = m.unit_cm(level, food_cost=food)
        changed_price = number(target.price) + number(alternative.price_delta)
        changed_food = number(scenario_food_costs.get(target.id, target.food_cost)[level]) + number(alternative.food_cost_delta)
        changed_cm = target.unit_cm(level, price=changed_price, food_cost=changed_food) - number(alternative.extra_labor_cost)
        after[target.id] = after[target.id] * (1 - rate) + changed_cm * rate
        warnings = []
        if not any(alternative.cannibalization.values()):
            warnings.append("잠식 미반영 (기본 0%)")
        if actual:
            base = sum((m.unit_cm(level) * number(m.daily_volume) * days for m in menus), Decimal(0))
            other = sum((after[m.id] * number(m.daily_volume) * days * (1 - number(alternative.cannibalization.get(m.id, 0)))
                         for m in menus if m.id != target.id), Decimal(0))
            original_volume = number(target.daily_volume) * days
            required = required_volume(base - other, after[target.id], alternative.setup_cost)
            same_volume_cm = other + after[target.id] * original_volume
        else:
            original_volume = Decimal(100)
            base = target.unit_cm(level) * original_volume
            other = Decimal(0)
            required = required_volume(base, after[target.id])
            same_volume_cm = None
            warnings.append("판매량 미상: 대상 메뉴 지수 100 기준, 도입비용·잠식·매장 합계 제외")
            if alternative.setup_cost:
                warnings.append("도입비용 포함 결과는 모든 메뉴의 판매량 입력 후 제공")
        increase = (float((number(required) / original_volume - 1) * 100)
                    if required is not None and original_volume > 0 else None)
        if actual and original_volume == 0:
            warnings.append("기존 판매량 0: 필요 증가율을 계산할 수 없습니다")
        provenance = {v for m in menus for v in m.tags.values()} | set(alternative.tags.values())
        if not provenance:
            provenance = {"가정값"}
        rows.append({
            "alternative_id": alternative.id, "alternative": alternative.name,
            "target_menu": target.id, "cost_level": level,
            "unit_cm": float(after[target.id]), "required_volume": required if actual else None,
            "required_index": required if not actual else None, "increase_pct": increase,
            "base_store_cm": float(base) if actual else None,
            "after_store_cm_at_same_volume": float(same_volume_cm) if actual else None,
            "after_store_cm_after_setup": float(same_volume_cm - number(alternative.setup_cost)) if actual else None,
            "required_daily_volume": required / float(days) if actual and required is not None else None,
            "setup_cost": float(alternative.setup_cost), "extra_minutes": float(alternative.extra_minutes),
            "additional_target_minutes": float(number(required) * rate * number(alternative.extra_minutes)) if actual and required is not None else None,
            "operating_days": int(days), "period_weeks": float(weeks),
            "status": "판매량 증가만으로는 목표 달성 불가" if required is None else "달성 조건",
            "tags": sorted(provenance), "warnings": warnings, "notice": NOTICE,
            "context": dict(context or {}),
        })
    return rows


def menu_from_dict(data: Mapping) -> Menu:
    return Menu(**{k: v for k, v in data.items() if k in Menu.__dataclass_fields__})


def alternative_from_dict(data: Mapping) -> Alternative:
    return Alternative(**{k: v for k, v in data.items() if k in Alternative.__dataclass_fields__})


def main():
    import argparse
    import json
    from pathlib import Path
    import yaml
    parser = argparse.ArgumentParser(description=NOTICE)
    parser.add_argument("--store", default="config/demo_store_korean.yaml")
    parser.add_argument("--options", default="config/options.yaml")
    parser.add_argument("--output", help="Optional JSON output")
    args = parser.parse_args()
    store = yaml.safe_load(Path(args.store).read_text(encoding="utf-8"))
    options = yaml.safe_load(Path(args.options).read_text(encoding="utf-8"))["industries"][store["buz"]]
    rows = [r for o in options for r in simulate([menu_from_dict(m) for m in store["menus"]],
            alternative_from_dict(o), operating_days=store["operating_days"], period_weeks=store["period_weeks"])]
    result = json.dumps({"label": "가상 사례" if store.get("is_demo") else "매장 입력", "results": rows}, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result, encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
