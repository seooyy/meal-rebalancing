"""Store-profile validation and recommendation eligibility.

This module deliberately produces *candidates*, not a prediction or a ranked
"best" action.  A candidate must still pass the profit simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


GOALS = {
    "sales": "방문·주문 건수를 늘리고 싶어요",
    "ticket": "객단가를 높이고 싶어요",
    "cost": "원가 부담을 줄이고 싶어요",
    "ordering": "주문 과정·운영 부담을 줄이고 싶어요",
}
PRICE_SOURCES = {
    "unknown": "원가 모름",
    "rate": "대략 원가율",
    "recipe": "레시피·매입단가",
    # 이전 저장 데이터 호환. 새 화면에서는 recipe 하나로만 받는다.
    "actual": "레시피·매입단가",
}


@dataclass(frozen=True)
class RecipeIngredient:
    name: str
    quantity: float
    unit: str
    purchase_price: float


@dataclass(frozen=True)
class StoreMenu:
    id: str
    name: str
    price: float
    daily_volume: float | None
    cost_source: str = "unknown"
    food_cost_rate: float | None = None
    ingredients: tuple[RecipeIngredient, ...] = ()
    packaging: float = 0
    fee_rate: float = 0
    variable_labor: float = 0
    assumed_zero_fields: tuple[str, ...] = ()

    @property
    def recipe_cost(self) -> float | None:
        return sum(i.quantity * i.purchase_price for i in self.ingredients) if self.ingredients else None

    @property
    def unit_food_cost(self) -> float:
        if self.recipe_cost is not None:
            return self.recipe_cost
        return self.price * (self.food_cost_rate if self.food_cost_rate is not None else .35)

    @property
    def unit_contribution(self) -> float:
        return self.price * (1 - self.fee_rate) - self.unit_food_cost - self.packaging - self.variable_labor


@dataclass(frozen=True)
class StoreProfile:
    buz: str
    goal: str
    menu_name: str
    price: float
    daily_volume: float | None
    operating_days: int
    price_source: str
    food_cost_rate: float | None
    experiment_budget: float
    extra_minutes_capacity: float
    menus: tuple[StoreMenu, ...] = ()
    sales_volume_basis: str = "estimate"

    @property
    def has_known_margin(self) -> bool:
        return bool(self.menus) and all(menu.cost_source in {"rate", "recipe", "actual"}
                                        for menu in self.menus)


def _number(value, name, *, minimum=0, maximum=None, allow_blank=False):
    if allow_blank and value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}을(를) 숫자로 입력하세요.") from None
    if number < minimum or (maximum is not None and number > maximum):
        suffix = f"{minimum}~{maximum}" if maximum is not None else f"{minimum} 이상"
        raise ValueError(f"{name}은(는) {suffix}이어야 합니다.")
    return number


def profile_from_form(form: Mapping) -> StoreProfile:
    buz = str(form.get("buz", "8001"))
    if buz not in {"8001", "8006"}:
        raise ValueError("업종을 선택하세요.")
    goal = str(form.get("goal", "sales"))
    if goal not in GOALS:
        raise ValueError("고민을 선택하세요.")
    source = str(form.get("price_source", "unknown"))
    if source not in PRICE_SOURCES:
        raise ValueError("원가 정보 수준을 선택하세요.")
    rate = _number(form.get("food_cost_rate"), "원가율", minimum=0, maximum=1,
                   allow_blank=source in {"unknown", "recipe", "actual"})
    if source == "rate" and rate is None:
        raise ValueError("대략적인 원가율을 입력하세요.")
    name = str(form.get("menu_name", "대표 메뉴")).strip() or "대표 메뉴"
    menus = tuple(_menu_from_data(item, index, default_source=source, default_rate=rate)
                  for index, item in enumerate(form.get("menus", ()))
                  if str(item.get("name", "")).strip())
    if "menus" in form and not menus:
        raise ValueError("메뉴를 하나 이상 입력하세요.")
    if menus:
        first = menus[0]
        name, price, volume = first.name, first.price, first.daily_volume
    else:
        name = str(form.get("menu_name", "대표 메뉴")).strip() or "대표 메뉴"
        price = _number(form.get("price"), "대표 메뉴 판매가", minimum=1)
        volume = _number(form.get("daily_volume"), "하루 판매량", minimum=0, allow_blank=True)
    return StoreProfile(
        buz=buz, goal=goal, menu_name=name,
        price=price, daily_volume=volume,
        operating_days=int(_number(form.get("operating_days", 24), "평가 기간 영업일", minimum=1)),
        price_source=source, food_cost_rate=rate,
        experiment_budget=_number(form.get("experiment_budget", 0), "실험 예산", minimum=0),
        extra_minutes_capacity=_number(form.get("extra_minutes_capacity", 0), "추가 조리 여력", minimum=0), menus=menus,
        sales_volume_basis=(str(form.get("sales_volume_basis", "estimate"))
                            if str(form.get("sales_volume_basis", "estimate")) in {"pos", "estimate"}
                            else "estimate"),
    )


def _menu_from_data(data: Mapping, index: int, *, default_source="unknown", default_rate=None) -> StoreMenu:
    name = str(data.get("name", "")).strip()
    source = str(data.get("cost_source", default_source))
    if source not in PRICE_SOURCES:
        raise ValueError(f"{name} 원가 입력 방식을 선택하세요.")
    rate = _number(data.get("food_cost_rate", default_rate), f"{name} 원가율", minimum=0, maximum=1,
                   allow_blank=source != "rate")
    if source == "rate" and rate is None:
        raise ValueError(f"{name}의 대략 원가율을 입력하세요.")
    ingredients = []
    for raw in data.get("ingredients", ()):
        ingredient_name = str(raw.get("name", "")).strip()
        if not ingredient_name:
            continue
        ingredients.append(RecipeIngredient(
            name=ingredient_name,
            quantity=_number(raw.get("quantity"), f"{name} {ingredient_name} 사용량", minimum=0),
            unit=str(raw.get("unit", "단위")).strip() or "단위",
            purchase_price=_number(raw.get("purchase_price"), f"{name} {ingredient_name} 매입단가", minimum=0),
        ))
    if source in {"recipe", "actual"} and not ingredients:
        raise ValueError(f"{name}은(는) 레시피 원가를 선택했으므로 재료·사용량·매입단가를 입력하세요.")
    optional_fields = {
        "packaging": ("포장비", 0),
        "fee_rate": ("카드·배달 수수료", 0),
        "variable_labor": ("변동 인건비", 0),
    }
    assumed_zero = tuple(label for field, (label, _) in optional_fields.items()
                         if data.get(field) in (None, ""))
    return StoreMenu(
        id=str(data.get("id", f"menu_{index + 1}")), name=name,
        price=_number(data.get("price"), f"{name} 판매가", minimum=1),
        daily_volume=_number(data.get("daily_volume"), f"{name} 하루 판매량", minimum=0),
        cost_source=source, food_cost_rate=rate,
        packaging=_number(data.get("packaging") or 0, f"{name} 포장비", minimum=0),
        fee_rate=_number(data.get("fee_rate") or 0, f"{name} 수수료율", minimum=0, maximum=1),
        variable_labor=_number(data.get("variable_labor") or 0, f"{name} 변동 인건비", minimum=0),
        assumed_zero_fields=assumed_zero,
        ingredients=tuple(ingredients),
    )


def simulator_menus(profile: StoreProfile):
    """Convert a complete store profile to calculation menus without API guesses."""
    from src.simulator import Menu
    entries = profile.menus or (StoreMenu("representative", profile.menu_name, profile.price,
                                           profile.daily_volume),)
    menus = []
    for entry in entries:
        base = entry.recipe_cost
        if base is None:
            base = entry.price * (entry.food_cost_rate if entry.food_cost_rate is not None else .35)
        cost_tag = ("관측값" if entry.recipe_cost is not None else
                    "추정값" if entry.cost_source == "rate" else "가정값")
        menus.append(Menu(id=entry.id, name=entry.name, price=entry.price, daily_volume=entry.daily_volume,
                          packaging=entry.packaging, fee_rate=entry.fee_rate, variable_labor=entry.variable_labor,
                          food_cost={"low": round(base * .8), "base": round(base), "high": round(base * 1.2)},
                          tags={"price": "관측값", "daily_volume": "관측값",
                                "food_cost.low": cost_tag, "food_cost.base": cost_tag,
                                "food_cost.high": cost_tag}))
    return menus


def recommendation_candidates(profile: StoreProfile) -> list[dict]:
    """Return explainable, feasibility-filtered action candidates."""
    candidates: list[dict] = []

    def add(option_id, title, reason, conditions=(), warning=None):
        candidates.append({"option_id": option_id, "title": title, "reason": reason,
                           "conditions": list(conditions), "warning": warning})

    redesign_warning = ("현재 조리 여력으로는 구성 변경의 추가 작업을 감당하기 어렵습니다."
                        if profile.extra_minutes_capacity < .5 else None)
    ordering_warning = ("현재 조리 여력으로는 주문 방식 변경 후의 추가 작업을 감당하기 어렵습니다."
                        if profile.extra_minutes_capacity < .2 else None)

    if profile.goal == "ticket":
        if profile.has_known_margin:
            add("redesign", "구성 조정", "객단가 개선을 위한 구성·옵션 조정안입니다.",
                ["레시피 또는 실제 원가를 확인한 뒤 가격·구성을 바꾸세요."], redesign_warning)
        else:
            add("redesign", "구성 조정(참고 후보)", "객단가 개선 후보이지만 원가 정보가 부족합니다.",
                ["원가율 또는 레시피를 입력한 뒤 손익을 확인하세요."],
                redesign_warning or "참고용 가정값으로만 계산됩니다.")
    elif profile.goal == "cost":
        if profile.has_known_margin:
            add("redesign", "구성 조정", "원가 부담을 줄일 수 있는 후보입니다.",
                ["대체 재료·중량 변경을 레시피에 반영하세요."], redesign_warning)
        else:
            add("redesign", "구성 조정(정보 보완 필요)", "원가를 모르면 절감 효과를 검증할 수 없습니다.",
                ["원가율 또는 레시피를 먼저 입력하세요."],
                redesign_warning or "추천 확정 전 정보 보완이 필요합니다.")
    elif profile.goal == "ordering":
        if profile.experiment_budget >= 80_000:
            add("ordering", "주문 방식 개선", "주문 과정의 마찰을 줄이는 후보입니다.",
                ["도입비와 추가 조리시간을 시뮬레이션에서 확인하세요."], ordering_warning)
        else:
            add("ordering", "주문 방식 개선(예산 확인 필요)", "예상 도입비보다 실험 예산이 낮습니다.",
                ["예산을 늘리거나 작은 범위의 실험으로 시작하세요."],
                ordering_warning or "현재 예산으로는 바로 실행하기 어렵습니다.")
    else:
        if profile.experiment_budget >= 300_000:
            add("visibility", "메뉴 노출 개선", "방문·주문 기회를 넓히는 후보입니다.",
                ["도입비 회수에 필요한 추가 판매량을 확인하세요."])
        else:
            add("visibility", "메뉴 노출 개선(예산 확인 필요)", "노출 개선은 도입비가 드는 후보입니다.",
                ["작게 시험하거나 예산을 확인하세요."], "현재 예산으로는 바로 실행하기 어렵습니다.")
        if profile.has_known_margin:
            add("discount", "조건부 할인", "유입을 시험하는 후보입니다.",
                ["할인 폭과 추가 판매량 조건을 반드시 확인하세요."], "할인은 이익을 보장하지 않습니다.")

    return candidates


def profile_to_simulator_form(profile: StoreProfile, target_menu_id: str) -> dict:
    """Apply only the profile's known facts; leave unknown costs as assumptions."""
    form = {
        "buz": profile.buz,
        "own_store": "yes",
        "period_weeks": 4,
        "operating_days": profile.operating_days,
        f"{target_menu_id}.name": profile.menu_name,
        f"{target_menu_id}.price": profile.price,
        f"{target_menu_id}.daily_volume": "" if profile.daily_volume is None else profile.daily_volume,
    }
    if profile.food_cost_rate is not None:
        base = round(profile.price * profile.food_cost_rate)
        form.update({f"{target_menu_id}.food_cost.low": round(base * .8),
                     f"{target_menu_id}.food_cost.base": base,
                     f"{target_menu_id}.food_cost.high": round(base * 1.2)})
    return form
