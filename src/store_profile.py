"""Store-profile validation and conversion to profit-calculation inputs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


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
    purchase_price_low: float | None = None
    purchase_price_high: float | None = None
    public_price_id: str | None = None


def public_price_options() -> dict[str, str]:
    """Collected public-price choices. Empty means no complete collection exists."""
    from src.collect_price import ROOT, read_mapping

    if not (ROOT / "out/price_daily.csv").exists():
        return {}
    return {row["ingredient_id"]: f'{row["name"]} ({row["recipe_unit"]})'
            for row in read_mapping() if public_price_range(row["ingredient_id"]) is not None}


def public_price_range(ingredient_id: str) -> dict | None:
    """Return strict-series 10th percentile/mean/90th percentile per recipe unit."""
    from src.collect_price import ROOT, read_mapping
    from src.price_scenario import price_series, read_daily

    path = ROOT / "out/price_daily.csv"
    mapping = next((row for row in read_mapping() if row["ingredient_id"] == ingredient_id), None)
    if mapping is None or not path.exists():
        return None
    series = price_series(read_daily(path), mapping)
    if series is None:
        return None
    return {"low": series["fall"], "base": series["base"], "high": series["rise"],
            "unit": mapping["recipe_unit"], "name": mapping["name"], **series}


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

    def recipe_cost_at(self, level: str) -> float | None:
        if not self.ingredients:
            return None
        field = {"low": "purchase_price_low", "base": "purchase_price",
                 "high": "purchase_price_high"}[level]
        return sum(i.quantity * (getattr(i, field) if getattr(i, field) is not None else i.purchase_price)
                   for i in self.ingredients)

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
        buz=buz, menu_name=name,
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
        public_id = str(raw.get("public_price_id") or "").strip() or None
        if raw.get("price_mode") == "public" and not public_id:
            raise ValueError(f"{name} {ingredient_name}에 적용할 공개가격 품목을 선택하세요.")
        public = public_price_range(public_id) if public_id else None
        if public_id and public is None:
            raise ValueError(f"{name} {ingredient_name} 공개가격 자료를 찾을 수 없습니다.")
        purchase = (public["base"] if public else
                    _number(raw.get("purchase_price"), f"{name} {ingredient_name} 매입단가", minimum=0))
        purchase_low = (public["low"] if public else _number(
            raw.get("purchase_price_low"), f"{name} {ingredient_name} 낮은 단가", minimum=0, allow_blank=True))
        purchase_high = (public["high"] if public else _number(
            raw.get("purchase_price_high"), f"{name} {ingredient_name} 높은 단가", minimum=0, allow_blank=True))
        if purchase_low is not None and purchase_low > purchase:
            raise ValueError(f"{name} {ingredient_name} 낮은 단가는 기준 단가 이하여야 합니다.")
        if purchase_high is not None and purchase_high < purchase:
            raise ValueError(f"{name} {ingredient_name} 높은 단가는 기준 단가 이상이어야 합니다.")
        ingredients.append(RecipeIngredient(
            name=ingredient_name,
            quantity=_number(raw.get("quantity"), f"{name} {ingredient_name} 사용량", minimum=0),
            unit=(public["unit"] if public else str(raw.get("unit", "단위")).strip() or "단위"),
            purchase_price=purchase, purchase_price_low=purchase_low, purchase_price_high=purchase_high,
            public_price_id=public_id,
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
        daily_volume=_number(data.get("daily_volume"), f"{name} 하루 판매량", minimum=0, allow_blank=True),
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
            costs = {"low": round(base * .8), "base": round(base), "high": round(base * 1.2)}
        else:
            costs = {level: round(entry.recipe_cost_at(level)) for level in ("low", "base", "high")}
        cost_tag = ("추정값" if any(i.public_price_id for i in entry.ingredients) else
                    "관측값" if entry.recipe_cost is not None else
                    "추정값" if entry.cost_source == "rate" else "가정값")
        menus.append(Menu(id=entry.id, name=entry.name, price=entry.price, daily_volume=entry.daily_volume,
                          packaging=entry.packaging, fee_rate=entry.fee_rate, variable_labor=entry.variable_labor,
                          food_cost=costs,
                          tags={"price": "관측값", "daily_volume": "관측값",
                                "food_cost.low": cost_tag, "food_cost.base": cost_tag,
                                "food_cost.high": cost_tag}))
    return menus
