"""Recipe costs from matching public series, actual purchase prices or assumptions."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean

import yaml

from src.collect_price import ROOT, write_csv
from src.simulator import COST_LEVELS, number

SCENARIOS = ("base", "rise", "fall", "custom")


def quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("가격 시계열이 비어 있습니다")
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def read_daily(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["unit_price"] = float(number(row["unit_price"], "unit_price", minimum="0.000001"))
    return rows


def price_series(rows, mapping, *, region_code=None, market_code=None,
                 start=date(2026, 1, 1), end=date(2026, 6, 30)):
    """Strict series identity, one mean per day, fallback only if local series absent.

    Weekly means when >50% of calendar days have no observations; never forward
    fill closed market days. Mixed grades, units, markets aren't silently pooled.
    National fallback explicitly averages matching markets within each date.
    """
    matched = [r for r in rows if r["ingredient_id"] == mapping["ingredient_id"]
               and all(str(r[k]) == str(mapping[k]) for k in ("se_cd", "ctgry_cd", "item_cd", "vrty_cd", "grd_cd", "unit", "recipe_unit"))
               and number(r["unit_sz"]) == number(mapping["unit_sz"])
               and start <= date.fromisoformat(r["date"]) <= end]
    local = [r for r in matched if (not region_code or r["sgg_cd"] == region_code)
             and (not market_code or r["mrkt_cd"] == market_code)]
    fallback = bool((region_code or market_code) and not local and matched)
    selected = matched if fallback else local
    if not selected:
        return None
    # With a region but no market configured, choose one market deterministically
    # by observation coverage, then code. Never stitch different local markets.
    selected_market = market_code
    if region_code and not market_code and not fallback:
        groups = defaultdict(set)
        for row in selected:
            groups[row["mrkt_cd"]].add(row["date"])
        selected_market = sorted(groups, key=lambda k: (-len(groups[k]), k))[0]
        selected = [r for r in selected if r["mrkt_cd"] == selected_market]
    daily = defaultdict(list)
    seen = set()
    for row in selected:
        key = (row["date"], row["sgg_cd"], row["mrkt_cd"])
        if key in seen:
            raise ValueError("가격 시계열에 중복 날짜·시장이 있습니다")
        seen.add(key)
        daily[row["date"]].append(float(number(row["unit_price"], minimum="0.000001")))
    values = [mean(v) for _, v in sorted(daily.items())]
    missing = 1 - len(daily) / ((end - start).days + 1)
    cadence = "daily"
    if missing > 0.5:
        weeks = defaultdict(list)
        for day, prices in daily.items():
            weeks[date.fromisoformat(day).isocalendar()[:2]].append(mean(prices))
        values = [mean(v) for v in weeks.values()]
        cadence = "weekly"
    return {"base": mean(values), "rise": quantile(values, 0.9), "fall": quantile(values, 0.1),
            "observed_days": len(daily), "missing_rate": missing, "cadence": cadence,
            "national_fallback": fallback, "market_code": selected_market if not fallback else None,
            "scope": "전국 동일 규격 시장 일별 평균" if fallback or not region_code else "지역 고정 시장",
            "se_cd": mapping["se_cd"], "unit": mapping["recipe_unit"]}


def recipe_costs(recipe, daily_rows, mappings, *, scenario="base", actual_prices=None,
                 changes=None, region_code=None, market_code=None,
                 start=date(2026, 1, 1), end=date(2026, 6, 30)):
    """Return food-cost ranges and ingredient/coverage audit; actual prices are per recipe unit."""
    if scenario not in SCENARIOS:
        raise ValueError("알 수 없는 가격 시나리오")
    actual_prices = actual_prices or {}
    changes = changes or {}
    ingredients = recipe["ingredients"]
    if (set(actual_prices) | set(changes)) - set(ingredients):
        raise ValueError("레시피에 없는 품목의 매입단가/변동률")
    for key, value in actual_prices.items():
        number(value, f"actual_prices.{key}", minimum=0)
    for key, value in changes.items():
        number(value, f"changes.{key}", minimum=-1)
    map_by_id = {m["ingredient_id"]: m for m in mappings}
    series = {key: price_series(daily_rows, map_by_id[key], region_code=region_code, market_code=market_code,
                               start=start, end=end) if key in map_by_id else None for key in ingredients}
    menu_costs, details, coverage = {}, [], []
    for menu_id, quantities in recipe["menus"].items():
        if set(quantities) - set(ingredients):
            raise ValueError(f"{menu_id}: 정의되지 않은 레시피 재료")
        totals = {level: 0.0 for level in COST_LEVELS}
        public_cost = actual_cost = 0.0
        for key, quantity in quantities.items():
            q = float(number(quantity, f"{menu_id}.{key}", minimum=0))
            ingredient, public = ingredients[key], series[key]
            if key in map_by_id and ingredient["unit"] != map_by_id[key]["recipe_unit"]:
                raise ValueError(f"{key}: 레시피 단위와 가격 매핑 단위 불일치")
            assumptions = ingredient["assumed_unit_price"]
            assumed_values = [float(number(assumptions[level], minimum=0)) for level in COST_LEVELS]
            if assumed_values != sorted(assumed_values):
                raise ValueError(f"{key}: 가정 단가 범위 순서 오류")
            if key in actual_prices:
                unit_prices = dict.fromkeys(COST_LEVELS, float(actual_prices[key]))
                source = "관측값"
            elif public:
                unit_prices = dict.fromkeys(COST_LEVELS, public["base"])
                source = "추정값"
            else:
                unit_prices = dict(zip(COST_LEVELS, assumed_values))
                source = "가정값"
            factor, warning = 1.0, ""
            if scenario in {"rise", "fall"}:
                if public:
                    factor = public[scenario] / public["base"]
                else:
                    warning = "비교 가능한 공개 시계열 없음: 자동 변동 미적용, 사용자 지정 가능"
            elif scenario == "custom":
                factor = 1 + float(changes.get(key, 0))
            line_costs = {level: q * price * factor for level, price in unit_prices.items()}
            for level in COST_LEVELS:
                totals[level] += line_costs[level]
            if source == "추정값":
                public_cost += line_costs["base"]
            if source == "관측값":
                actual_cost += line_costs["base"]
            details.append({"menu_id": menu_id, "ingredient_id": key, "quantity": q, "unit": ingredient["unit"],
                            "source": source, "scenario": scenario, "factor": factor, "base_unit_price": unit_prices["base"],
                            "cost": line_costs["base"], "national_fallback": public["national_fallback"] if public else False,
                            "market_code": public["market_code"] if public else None,
                            "missing_rate": public["missing_rate"] if public else None,
                            "cadence": public["cadence"] if public else None,
                            "se_cd": public["se_cd"] if public else None,
                            "warning": warning})
        menu_costs[menu_id] = totals
        pct = public_cost / totals["base"] if totals["base"] else 0.0
        actual_pct = actual_cost / totals["base"] if totals["base"] else 0.0
        coverage.append({"buz": recipe["buz"], "menu_id": menu_id, "scenario": scenario,
                         "food_cost": totals["base"], "public_cost": public_cost, "actual_cost": actual_cost,
                         "public_coverage": pct, "actual_coverage": actual_pct,
                         "badge": "참고 수준" if pct < 0.7 else "공개 가격 기반 추정"})
    return {"food_costs": menu_costs, "details": details, "coverage": coverage, "scenario": scenario}


def industry_coverage(coverage, menus):
    """Weight recipe cost by baseline sales; no invented weights for missing volume."""
    volumes = {m.id: m.daily_volume for m in menus}
    if any(v is None for v in volumes.values()):
        return {"public_coverage": None, "actual_coverage": None, "basis": "판매량 입력 후 업종 원가 비중 계산"}
    total = sum(c["food_cost"] * volumes[c["menu_id"]] for c in coverage)
    return {"public_coverage": sum(c["public_cost"] * volumes[c["menu_id"]] for c in coverage) / total if total else 0,
            "actual_coverage": sum(c["actual_cost"] * volumes[c["menu_id"]] for c in coverage) / total if total else 0,
            "basis": "기존 메뉴 판매량 가중, 식재료비 기준"}


def main():
    from src.collect_price import read_mapping
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", type=Path, default=ROOT / "out/price_daily.csv")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "out")
    parser.add_argument("--allow-assumptions", action="store_true", help="Explicit offline demo; never claims collected prices")
    parser.add_argument("--actual-prices", type=Path, help="JSON ingredient->price per recipe unit")
    parser.add_argument("--changes", type=Path, help="JSON ingredient->fractional change")
    args = parser.parse_args()
    if not args.daily.exists() and not args.allow_assumptions:
        parser.error("가격 CSV가 없습니다. 먼저 수집하거나 --allow-assumptions로 가상 사례를 생성하세요")
    daily = read_daily(args.daily) if args.daily.exists() else []
    mapping = read_mapping()
    actual = json.loads(args.actual_prices.read_text(encoding="utf-8")) if args.actual_prices else {}
    changes = json.loads(args.changes.read_text(encoding="utf-8")) if args.changes else {}
    scenarios, coverage, details, industry_rows = [], [], [], []
    from src.simulator import menu_from_dict
    known_ingredients = set()
    for kind in ("korean", "western"):
        known_ingredients.update(yaml.safe_load((ROOT / f"config/recipe_{kind}.yaml").read_text(encoding="utf-8"))["ingredients"])
    if (set(actual) | set(changes)) - known_ingredients:
        parser.error("매입단가/변동률 JSON에 레시피에 없는 품목이 있습니다")
    for kind in ("korean", "western"):
        recipe = yaml.safe_load((ROOT / f"config/recipe_{kind}.yaml").read_text(encoding="utf-8"))
        store = yaml.safe_load((ROOT / f"config/demo_store_{kind}.yaml").read_text(encoding="utf-8"))
        for scenario in SCENARIOS:
            result = recipe_costs(recipe, daily, mapping, scenario=scenario,
                                  actual_prices={k: v for k, v in actual.items() if k in recipe["ingredients"]},
                                  changes={k: v for k, v in changes.items() if k in recipe["ingredients"]},
                                  region_code=store["price_region_code"])
            for menu, costs in result["food_costs"].items():
                scenarios.append({"buz": recipe["buz"], "menu_id": menu, "scenario": scenario, **costs,
                                  "label": "가상 사례", "price_data": "공개가격 자료 포함" if daily else "공개가격 미수집: 입력 매입단가 또는 가정값"})
            coverage.extend({**c, "label": "가상 사례"} for c in result["coverage"])
            details.extend({**d, "label": "가상 사례"} for d in result["details"])
            industry_rows.append({"buz": recipe["buz"], "scenario": scenario, "label": "가상 사례",
                                  **industry_coverage(result["coverage"], [menu_from_dict(m) for m in store["menus"]])})
    write_csv(args.out_dir / "price_scenarios.csv", scenarios, list(scenarios[0]))
    write_csv(args.out_dir / "price_coverage.csv", coverage, list(coverage[0]))
    write_csv(args.out_dir / "price_recipe_details.csv", details, list(details[0]))
    write_csv(args.out_dir / "price_industry_coverage.csv", industry_rows, list(industry_rows[0]))
    status = "public series available" if daily else ("purchase-price inputs and assumptions; no API data collected" if actual else "ASSUMPTIONS ONLY, no API data collected")
    print(f"{len(scenarios)} menu scenarios; {status}")


if __name__ == "__main__":
    main()
