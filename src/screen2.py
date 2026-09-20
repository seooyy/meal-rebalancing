"""손익 계산 API와 독립 실행형 입력 화면."""
from __future__ import annotations

import copy
import json

import yaml

from src.collect_price import ROOT, read_mapping
from src.load import BUZ_KOREAN, BUZ_WESTERN
from src.price_scenario import industry_coverage, read_daily, recipe_costs
from src.simulator import (COST_LEVELS, NOTICE, TAGS, alternative_from_dict,
                           menu_from_dict, number, simulate)

KINDS = {BUZ_KOREAN: "korean", BUZ_WESTERN: "western"}
LABELS = {"base": "기준", "rise": "상승 (90분위)", "fall": "하락 (10분위)", "custom": "사용자 지정"}


def config_for(buz):
    if buz not in KINDS:
        raise ValueError("일반한식 또는 서양음식을 선택하세요")
    kind = KINDS[buz]
    store = yaml.safe_load((ROOT / f"config/demo_store_{kind}.yaml").read_text(encoding="utf-8"))
    recipe = yaml.safe_load((ROOT / f"config/recipe_{kind}.yaml").read_text(encoding="utf-8"))
    options = yaml.safe_load((ROOT / "config/options.yaml").read_text(encoding="utf-8"))["industries"][buz]
    return store, recipe, options


def evaluate_inputs(form=None, *, context=None, daily_rows=None):
    """Validate flat form inputs; no network calls or persistent writes.

    Optional context is C's selected region/candidate metadata, displayed separately
    and never interpreted as a sales forecast. Public daily CSV is loaded only if
    recipe pricing is explicitly selected.
    """
    form = dict(form or {})
    buz = form.get("buz", BUZ_KOREAN)
    store, recipe, options = config_for(buz)
    for field in ("period_weeks", "operating_days", "average_people_per_payment"):
        store[field] = float(number(form.get(field, store[field]), field, minimum=1))
        tag = form.get(field + ".tag", "가정값")
        if tag not in TAGS:
            raise ValueError("입력 태그 오류")
        store["tags"][field] = tag
    store["is_demo"] = form.get("own_store") != "yes"
    for menu in store["menus"]:
        prefix = menu["id"] + "."
        menu["name"] = form.get(prefix + "name", menu["name"])
        for field in ("price", "daily_volume", "packaging", "fee_rate", "variable_labor"):
            raw = form.get(prefix + field, menu[field])
            menu[field] = None if field == "daily_volume" and raw == "" else float(number(raw, field, minimum=0))
            menu["tags"][field] = form.get(prefix + field + ".tag", menu["tags"][field])
        for level in COST_LEVELS:
            key = "food_cost." + level
            menu["food_cost"][level] = float(number(form.get(prefix + key, menu["food_cost"][level]), key, minimum=0))
            menu["tags"][key] = form.get(prefix + key + ".tag", menu["tags"][key])
    menus = [menu_from_dict(m) for m in store["menus"]]
    chosen = form.get("option", options[0]["id"])
    if chosen not in {o["id"] for o in options}:
        raise ValueError("알 수 없는 대안")
    active = copy.deepcopy(next(o for o in options if o["id"] == chosen))
    # Defaults are keyed by option, so switching candidates doesn't carry the old
    # candidate's settings into a different one.
    for index, option in enumerate(options):
        oid = option["id"]
        updated = copy.deepcopy(option)
        for key in ("price_delta", "food_cost_delta", "application_rate", "setup_cost", "extra_minutes", "extra_labor_cost"):
            updated[key] = float(number(form.get(f"{oid}.{key}", updated.get(key, 1 if key == "application_rate" else 0)), key))
            updated["tags"][key] = form.get(f"{oid}.{key}.tag", "가정값")
        if oid == chosen:
            updated["target_menu"] = form.get("target_menu", updated["target_menu"])
            updated["cannibalization"] = {m.id: float(number(form.get("cannibal." + m.id, 0), minimum=0, maximum=1))
                                           for m in menus if m.id != updated["target_menu"]}
            active = updated
        options[index] = updated
    scenario = form.get("scenario", "base")
    if scenario not in LABELS:
        raise ValueError("알 수 없는 가격 시나리오")
    pricing = form.get("pricing", "manual")
    if pricing not in {"manual", "recipe"}:
        raise ValueError("알 수 없는 원가 입력 방식")
    if scenario != "base" and pricing != "recipe":
        raise ValueError("가격 시나리오를 적용하려면 레시피·매입단가·공개가격 방식을 선택하세요")
    price_result = None
    scenario_costs = None
    if pricing == "recipe":
        actual = {k: float(number(form["actual." + k], minimum=0)) for k in recipe["ingredients"] if form.get("actual." + k, "") != ""}
        changes = {k: float(number(form.get("change." + k, 0), minimum=-1)) for k in recipe["ingredients"]}
        for menu_id, amounts in recipe["menus"].items():
            for ingredient, quantity in list(amounts.items()):
                amounts[ingredient] = float(number(form.get(f"recipe.{menu_id}.{ingredient}", quantity), minimum=0))
        if daily_rows is None:
            daily_path = ROOT / "out/price_daily.csv"
            daily_rows = read_daily(daily_path) if daily_path.exists() else []
        price_result = recipe_costs(recipe, daily_rows, read_mapping(), scenario=scenario,
                                   actual_prices=actual, changes=changes,
                                   region_code=form.get("price_region_code", store["price_region_code"]) or None,
                                   market_code=form.get("price_market_code") or None)
        scenario_costs = price_result["food_costs"]
        price_result["industry_coverage"] = industry_coverage(price_result["coverage"], menus)
        price_result["data_available"] = bool(daily_rows)
    rows = []
    for option in options[:3] + ([active] if chosen not in {o["id"] for o in options[:3]} else []):
        rows.extend(simulate(menus, alternative_from_dict(option), operating_days=store["operating_days"],
                             period_weeks=store["period_weeks"], scenario_food_costs=scenario_costs, context=context))
    submitted_tags = {v for k, v in form.items() if k.endswith(".tag")}
    if submitted_tags - TAGS:
        raise ValueError("입력 태그 오류")
    for row in rows:
        row["tags"] = sorted(set(row["tags"]) | set(store["tags"].values()) |
                             submitted_tags | ({d["source"] for d in price_result["details"]} if price_result else set()))
    return {"store": store, "recipe": recipe, "options": options, "active": active, "results": rows,
            "prices": price_result, "scenario": scenario, "pricing": pricing, "context": dict(context or {})}



def render_screen2(*, buz=None, context=None, key="screen2", daily_rows=None):
    """Render inside C's Streamlit page and return the current result (None on error).

    Pass C's selected industry as buz and optional diagnosis metadata as context.
    Does not set page configuration, create routes, start a server, or alter C's
    session keys. Each key prefix stores its own inputs per industry for reruns.
    """
    import streamlit as st

    st.subheader("우리 가게 실험안")
    st.info(NOTICE)
    st.caption("공헌이익 = 판매가격 − 변동비. 임차료·기본 인건비를 차감한 순이익이 아닙니다.")
    industries = {BUZ_KOREAN: "일반한식", BUZ_WESTERN: "서양음식"}
    if buz is None:
        buz = st.selectbox("업종", list(industries), format_func=industries.get, key=f"{key}.buz")
    if buz not in industries:
        st.error("일반한식 또는 서양음식을 선택하세요.")
        return None
    store, recipe, options = config_for(buz)
    saved_by_industry = st.session_state.setdefault(f"{key}.inputs", {})
    saved = saved_by_industry.get(buz, {})
    form = {"buz": buz}
    prefix = f"{key}.{buz}."

    def choose(name, label, choices, default):
        names = dict(choices)
        value = saved.get(name, default)
        if value not in names:
            value = default
        form[name] = st.selectbox(label, list(names), index=list(names).index(value),
                                  format_func=names.get, key=prefix + name)
        return form[name]

    def numeric(name, label, default, *, minimum=0.0, maximum=None, tag="가정값", tagged=True):
        initial = saved.get(name, default)
        if initial == "" or initial is None:
            initial = None
        else:
            initial = float(initial)
        columns = st.columns([3, 1]) if tagged else [st.container()]
        with columns[0]:
            value = st.number_input(label, value=initial, min_value=minimum, max_value=maximum,
                                    key=prefix + name, placeholder="모르면 비워두세요")
        form[name] = "" if value is None else value
        if tagged:
            with columns[1]:
                choose(name + ".tag", label + " · 출처",
                       [(t, t) for t in ("관측값", "추정값", "가정값")], tag)
        return value

    own = st.checkbox("내 매장 자료로 입력했습니다", value=saved.get("own_store") == "yes",
                      key=prefix + "own_store")
    form["own_store"] = "yes" if own else ""
    if not own:
        st.warning("가상 사례 — 기본 가격·원가·판매량·레시피는 모두 가정값입니다.")
    for field, label in (("period_weeks", "평가기간 (주)"),
                         ("operating_days", "기간 내 실제 영업일"),
                         ("average_people_per_payment", "결제당 평균 인원 (참고용)")):
        numeric(field, label, store[field], minimum=1.0, tag=store["tags"][field])
    st.caption("결제 건당금액은 1인 식사 가격이 아닙니다. 평균 인원은 계산에 사용하지 않습니다.")
    menu_tab, option_tab, price_tab = st.tabs(["메뉴 입력", "대안 설정", "식재료 가격"])
    with menu_tab:
        for menu in store["menus"]:
            mid = menu["id"]
            with st.expander(menu["name"], expanded=mid == store["menus"][0]["id"]):
                form[mid + ".name"] = st.text_input("메뉴 이름", saved.get(mid + ".name", menu["name"]),
                                                     key=prefix + mid + ".name")
                for field, label in (("price", "판매가격 (원)"), ("daily_volume", "일평균 판매량 (모르면 비움)"),
                                     ("packaging", "건당 포장비 (원)"), ("fee_rate", "결제·배달 수수료율 (0.02 = 2%)"),
                                     ("variable_labor", "건당 변동 노동비 (원)")):
                    numeric(mid + "." + field, label, menu[field], maximum=1.0 if field == "fee_rate" else None,
                            tag=menu["tags"][field])
                for level, label in zip(COST_LEVELS, ("낮음", "기준", "높음")):
                    field = "food_cost." + level
                    numeric(mid + "." + field, "변경 전 식재료비 · " + label, menu["food_cost"][level],
                            tag=menu["tags"][field])
    with option_tab:
        choose("option", "중점 비교 대안", [(o["id"], o["name"]) for o in options], options[0]["id"])
        target = choose("target_menu", "대상 메뉴", [(m["id"], form[m["id"] + ".name"]) for m in store["menus"]],
                        options[0]["target_menu"])
        for option in options:
            with st.expander(option["name"] + " · " + option["kind"]):
                for field, label in (("price_delta", "판매가격 증감 (원)"), ("food_cost_delta", "식재료비 증감 (원)"),
                                     ("application_rate", "적용 비율 (0~1)"), ("setup_cost", "평가기간 총 도입비용 (원)"),
                                     ("extra_minutes", "적용 판매 1건 추가 조리시간 (분)"),
                                     ("extra_labor_cost", "적용 판매 1건 추가 노동비 (원)")):
                    numeric(option["id"] + "." + field, label,
                            option.get(field, 1 if field == "application_rate" else 0),
                            minimum=None if field.endswith("delta") else 0.0,
                            maximum=1.0 if field == "application_rate" else None)
        st.caption("잠식률은 다른 메뉴의 기존 판매량 감소 비율입니다. 기본 0%는 잠식 미반영입니다.")
        for menu in store["menus"]:
            if menu["id"] != target:
                numeric("cannibal." + menu["id"], form[menu["id"] + ".name"] + " 잠식률 (0~1)", 0,
                        maximum=1.0)
    with price_tab:
        pricing = choose("pricing", "변경 후 원가 입력",
                         [("manual", "입력한 식재료비 사용"), ("recipe", "레시피·매입단가·공개가격 사용")], "manual")
        if pricing == "recipe":
            choose("scenario", "가격 시나리오", list(LABELS.items()), "base")
            st.caption("변경 전 원가는 비교 기준으로 유지합니다. 레시피 원가에 대안의 식재료비 증감을 추가 적용합니다. "
                       "구성 변경을 레시피에 이미 반영했다면 대안의 식재료비 증감을 0원으로 입력하세요.")
            form["price_region_code"] = st.text_input("가격 지역코드 (비우면 전국)",
                                                      saved.get("price_region_code", store["price_region_code"]),
                                                      key=prefix + "price_region_code")
            form["price_market_code"] = st.text_input("가격 시장코드 (비우면 관측일이 가장 많은 시장)",
                                                      saved.get("price_market_code", ""), key=prefix + "price_market_code")
            st.caption("기본 중도매(02), 품종·등급·포장단위 고정. 지역 자료가 없으면 동일 규격 전국 자료로 대체합니다.")
            with st.expander("품목별 매입단가·변동률"):
                for ingredient_id, ingredient in recipe["ingredients"].items():
                    numeric("actual." + ingredient_id,
                            ingredient["name"] + " 실제 매입단가 · 관측값 (원/" + ingredient["unit"] + ")",
                            None, tagged=False)
                    numeric("change." + ingredient_id, ingredient["name"] + " 사용자 지정 변동률 (0.1 = +10%)",
                            0, minimum=-1.0)
            with st.expander("메뉴별 레시피 투입량"):
                for menu_id, amounts in recipe["menus"].items():
                    st.text(form[menu_id + ".name"])
                    for ingredient_id, quantity in amounts.items():
                        ingredient = recipe["ingredients"][ingredient_id]
                        numeric(f"recipe.{menu_id}.{ingredient_id}",
                                ingredient["name"] + " (" + ingredient["unit"] + ")", quantity)
        else:
            form["scenario"] = "base"
    # Keep non-widget snapshots so changing industries/tabs doesn't lose entered values.
    saved_by_industry[buz] = {**saved, **form}
    try:
        result = evaluate_inputs(form, context=context, daily_rows=daily_rows)
    except (ValueError, KeyError, TypeError) as exc:
        st.error("입력 확인: " + str(exc))
        return None

    st.subheader("매장 입력 기반 계산" if own else "가상 사례 계산 결과")
    if context:
        st.caption("지역 진단 참고 — 판매량 예측에 사용하지 않습니다.")
        st.write(context)
        st.caption("BC카드 관측 집계 기준")
        st.caption("5월 결제금액이 전국 평균 대비 약 +11%로 높음 — 계절 요인 포함")
    rows = result["results"]
    st.dataframe([{
        "대안": r["alternative"], "원가 범위": {"low": "낮음", "base": "기준", "high": "높음"}[r["cost_level"]],
        "건당 공헌이익": r["unit_cm"], "기간 필요 판매량": r["required_volume"],
        "판매량 미상 시 필요 지수": r["required_index"], "필요 증가율 %": r["increase_pct"],
        "기존 매장 공헌이익": r["base_store_cm"],
        "기존 판매량 유지 시 도입비 차감 후 공헌이익": r["after_store_cm_after_setup"],
        "총 도입비": r["setup_cost"], "판정": r["status"]
    } for r in rows], hide_index=True)
    for warning in sorted({w for r in rows for w in r["warnings"]}):
        st.caption(warning)
    st.caption("입력 출처: " + ", ".join(sorted({t for r in rows for t in r["tags"]})))
    st.caption(f"선택 대안 추가 조리시간: {result['active'].get('extra_minutes', 0)}분/적용 판매 1건. "
               "수요와 주방 수용량은 점주가 별도로 확인해야 합니다.")
    if result["prices"]:
        prices = result["prices"]
        st.subheader("가격 출처와 적용 범위")
        st.caption("공개가격 파일 사용" if prices["data_available"] else "실제 가격 미수집: 입력 매입단가 또는 가정값 사용")
        st.dataframe(prices["coverage"], hide_index=True)
        overall = prices["industry_coverage"]
        st.caption("업종 공개가격 커버리지: " +
                   (f"{overall['public_coverage']:.1%}" if overall["public_coverage"] is not None else "판매량 입력 필요") +
                   " (" + overall["basis"] + ")")
        with st.expander("재료별 가격·결측·대체 내역"):
            st.dataframe(prices["details"], hide_index=True)
    st.download_button("계산 결과 JSON 다운로드", json.dumps({
        "label": "매장 입력" if own else "가상 사례", "results": rows, "prices": result["prices"]
    }, ensure_ascii=False, allow_nan=False, indent=2), file_name="simulator_result.json",
                       mime="application/json", key=prefix + "download")
    return result



def evaluate_profile_candidates(profile, target_menu_id: str, *, action_specs=None, context=None):
    """Calculate concrete screen-1 actions from a saved store profile.

    The caller filters these rows using the candidates that survived screen 1.
    All alternatives deliberately share one target menu and the same store facts,
    so the resulting order compares alternatives rather than demo menus.
    """
    from src.store_profile import simulator_menus

    menus = simulator_menus(profile)
    if target_menu_id not in {menu.id for menu in menus}:
        raise ValueError("대상 메뉴를 선택하세요")
    _, _, configured_options = config_for(profile.buz)
    templates = {option["id"]: option for option in configured_options}
    if action_specs:
        options = []
        for action in action_specs:
            option = copy.deepcopy(templates[action["base_option"]])
            option.update({"id": action["id"], "name": action["title"], "kind": action["kind"],
                           "candidate": action["candidate"], "action": action["action"],
                           "measure": action["measure"], "precheck": action["precheck"]})
            option.update(action.get("assumptions", {}))
            option["assumptions"] = dict(action.get("assumptions", {}))
            options.append(option)
    else:
        options = copy.deepcopy(configured_options)
    for option in options:
        option["target_menu"] = target_menu_id
        option["cannibalization"] = {}
    store = {
        "menus": [{
            "id": menu.id, "name": menu.name, "price": menu.price,
            "daily_volume": menu.daily_volume, "packaging": menu.packaging,
            "fee_rate": menu.fee_rate, "variable_labor": menu.variable_labor,
            "food_cost": dict(menu.food_cost), "tags": dict(menu.tags),
            "public_price_ingredients": [ingredient.name for source in profile.menus
                                           if source.id == menu.id for ingredient in source.ingredients
                                           if ingredient.public_price_id],
            "assumed_zero_fields": list(next(
                (source.assumed_zero_fields for source in profile.menus if source.id == menu.id), ())),
        } for menu in menus],
        "operating_days": profile.operating_days,
        "period_weeks": 4,
    }
    rows = [row for option in options for row in simulate(
        menus, alternative_from_dict(option), operating_days=profile.operating_days,
        period_weeks=4, context=context,
    )]
    return {"store": store, "options": options, "active": options[0],
            "results": rows, "prices": None, "context": dict(context or {})}


if __name__ == "__main__":
    render_screen2()
