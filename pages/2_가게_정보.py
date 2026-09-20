"""Step 2: store profile editor with a menu list and focused menu editor."""
import streamlit as st

from src.store_profile import (PRICE_SOURCES, profile_from_form,
                               public_price_options, public_price_range)
from ui.common import footer, page_setup, selector, stepper

page_setup("2단계 · 가게 정보")
stepper(2)
st.caption("메뉴별 판매가격과 비용을 입력하면 실행안별 손익 유지 조건을 계산합니다. 입력값은 현재 브라우저 세션에만 저장됩니다.")
region, buz, buz_name = selector()
profiles = st.session_state.setdefault("store_profiles", {})
profile_key = (region, buz)
saved = profiles.get(profile_key) or profiles.get(buz)  # 이전 세션 입력 호환
prefix = f"profile.{buz}.{region}"
ids_key, editing_key, next_id_key = prefix + ".menu_ids", prefix + ".editing", prefix + ".next_id"

def key(menu_id, field):
    return f"{prefix}.{menu_id}.{field}"

def seed(menu_id, menu=None):
    defaults = {"name": menu.name if menu else "", "price": menu.price if menu else 10000.0,
                "volume": menu.daily_volume if menu else None,
                "has_packaging": bool(menu and (menu.packaging or "포장비" not in menu.assumed_zero_fields)),
                "packaging": menu.packaging if menu else 0.0,
                "has_fee": bool(menu and (menu.fee_rate or "카드·배달 수수료" not in menu.assumed_zero_fields)),
                "fee": menu.fee_rate if menu else 0.0,
                "has_labor": bool(menu and (menu.variable_labor or "변동 인건비" not in menu.assumed_zero_fields)),
                "labor": menu.variable_labor if menu else 0.0,
                "cost_source": ("recipe" if menu and menu.cost_source == "actual" else menu.cost_source) if menu else "rate",
                "cost_rate": menu.food_cost_rate if menu and menu.food_cost_rate is not None else .35,
                "ingredient_count": max(1, len(menu.ingredients) if menu else 1)}
    for field, value in defaults.items():
        st.session_state.setdefault(key(menu_id, field), value)
    for index in range(defaults["ingredient_count"]):
        for field, value in {"name": "", "quantity": 0.0, "unit": "g", "purchase": 0.0,
                             "purchase_low": None, "purchase_high": None, "public_id": "",
                             "price_mode": "direct"}.items():
            st.session_state.setdefault(key(menu_id, f"ingredient.{index}.{field}"), value)
    for index, ingredient in enumerate(menu.ingredients if menu else ()):
        for field, value in {"name": ingredient.name, "quantity": ingredient.quantity,
                             "unit": ingredient.unit, "purchase": ingredient.purchase_price,
                             "purchase_low": ingredient.purchase_price_low,
                             "purchase_high": ingredient.purchase_price_high,
                             "public_id": ingredient.public_price_id or "",
                             "price_mode": "public" if ingredient.public_price_id else "direct"}.items():
            st.session_state.setdefault(key(menu_id, f"ingredient.{index}.{field}"), value)


def load_example():
    """Replace the current draft with a small, internally consistent test store."""
    examples = [
        {"id": "menu_1", "name": "제육볶음 정식", "price": 10000, "volume": 25,
         "packaging": 300, "fee": .03, "labor": 500, "cost_source": "rate", "cost_rate": .38,
         "ingredients": []},
        {"id": "menu_2", "name": "김치찌개", "price": 9000, "volume": 18,
         "packaging": 300, "fee": .03, "labor": 400, "cost_source": "recipe", "cost_rate": None,
         "ingredients": [
             {"name": "돼지고기", "quantity": .15, "unit": "kg", "purchase": 12000},
             {"name": "김치", "quantity": .25, "unit": "kg", "purchase": 4000},
             {"name": "쌀", "quantity": .25, "unit": "kg", "purchase": 3000},
         ]},
        {"id": "menu_3", "name": "비빔밥", "price": 9500, "volume": 15,
         "packaging": 300, "fee": .03, "labor": 450, "cost_source": "unknown", "cost_rate": None,
         "ingredients": []},
    ]
    st.session_state[ids_key] = [item["id"] for item in examples]
    st.session_state[next_id_key] = len(examples) + 1
    st.session_state[editing_key] = None
    st.session_state[prefix + ".days"] = 24
    for menu in examples:
        st.session_state[key(menu["id"], "has_packaging")] = bool(menu["packaging"])
        st.session_state[key(menu["id"], "has_fee")] = bool(menu["fee"])
        st.session_state[key(menu["id"], "has_labor")] = bool(menu["labor"])
        for field in ("name", "price", "volume", "packaging", "fee", "labor", "cost_source", "cost_rate"):
            st.session_state[key(menu["id"], field)] = menu[field]
        st.session_state[key(menu["id"], "ingredient_count")] = len(menu["ingredients"])
        for index, ingredient in enumerate(menu["ingredients"]):
            for field, value in ingredient.items():
                st.session_state[key(menu["id"], f"ingredient.{index}.{field}")] = value
            st.session_state[key(menu["id"], f"ingredient.{index}.public_id")] = ""
            st.session_state[key(menu["id"], f"ingredient.{index}.price_mode")] = "direct"

if ids_key not in st.session_state:
    initial = [menu.id for menu in saved.menus] if saved and saved.menus else ["menu_1"]
    st.session_state[ids_key] = initial
    st.session_state[next_id_key] = len(initial) + 1
    for index, menu_id in enumerate(initial):
        seed(menu_id, saved.menus[index] if saved and saved.menus else None)

def saved_value(name, default):
    return getattr(saved, name, default) if saved else default


if st.button("예시 입력값 채우기", key=prefix + ".example"):
    load_example()
    st.rerun()
st.caption("현재 입력을 예시 가게로 바꿉니다. 제육볶음 정식(원가율), 김치찌개(실제 레시피 원가), 비빔밥(원가 모름)으로 결과를 비교할 수 있습니다.")

st.subheader("1. 계산 기간과 운영 조건")
st.caption("하루 판매량은 특정 하루가 아니라 최근 4주 총판매량을 실제 영업일로 나눈 값이 가장 안정적입니다.")
operating_days = st.number_input("최근 4주 실제 영업일 *", min_value=1, max_value=28,
                                 value=int(saved_value("operating_days", 24)), key=prefix + ".days")
sales_volume_basis = st.radio(
    "판매량 자료",
    ["pos", "estimate"],
    format_func={"pos": "POS·주문내역으로 계산", "estimate": "기억에 따른 대략값"}.get,
    horizontal=True, key=prefix + ".sales-volume-basis",
)
if sales_volume_basis == "estimate":
    st.info("대략값이어도 계산할 수 있지만, 하루 추가 판매량과 후보 순위는 참고 수준입니다.")

budget_col, capacity_col = st.columns(2)
with budget_col:
    experiment_budget = st.number_input("평가기간에 쓸 수 있는 도입 예산(원)", min_value=0.0,
                                        value=float(saved_value("experiment_budget", 0)), key=prefix + ".budget")
with capacity_col:
    extra_minutes_capacity = st.number_input("판매 1건당 추가 작업 가능 시간(분)", min_value=0.0,
                                             value=float(saved_value("extra_minutes_capacity", 0)), key=prefix + ".capacity")
st.caption("지역 진단이 실행 후보를 정하고, 예산과 작업 여력은 실행 가능성 경고에만 사용합니다.")

st.subheader("2. 메뉴 목록")
public_options = public_price_options()
if public_options:
    st.success(f"공개시장 가격을 직접 선택할 수 있는 품목이 {len(public_options)}개 있습니다.")
else:
    st.info("공개가격 수집 파일이 없어 현재는 직접 입력한 매입단가를 사용합니다.")
menu_ids = st.session_state[ids_key]
editing = st.session_state.get(editing_key)

if editing is None:
    if not menu_ids:
        st.info("등록된 메뉴가 없습니다. 대표 메뉴부터 추가해 주세요.")
    for menu_id in menu_ids:
        ingredient_count = st.session_state[key(menu_id, "ingredient_count")]
        filled_ingredients = sum(bool(st.session_state.get(key(menu_id, f"ingredient.{index}.name"), "").strip())
                                 for index in range(ingredient_count))
        name = st.session_state.get(key(menu_id, "name"), "") or "이름 없는 메뉴"
        price = st.session_state.get(key(menu_id, "price"), 0)
        volume = st.session_state.get(key(menu_id, "volume"), None)
        left, middle, edit, delete = st.columns([5, 3, 1, 1])
        with left:
            st.write(f"**{name}**")
            source = st.session_state.get(key(menu_id, "cost_source"), "rate")
            st.caption(f"원가: {PRICE_SOURCES[source]} · 입력한 재료 {filled_ingredients}개")
        with middle:
            st.write(f"{price:,.0f}원")
            st.caption("판매량 미입력" if volume is None else f"하루 {volume:,.0f}건")
        with edit:
            if st.button("수정", key=key(menu_id, "edit")):
                st.session_state[editing_key] = menu_id
                st.rerun()
        with delete:
            if st.button("삭제", key=key(menu_id, "delete")):
                st.session_state[ids_key] = [item for item in menu_ids if item != menu_id]
                st.rerun()
    if st.button("+ 메뉴 추가", type="primary", key=prefix + ".add-menu"):
        new_id = f"menu_{st.session_state[next_id_key]}"
        st.session_state[next_id_key] += 1
        st.session_state[ids_key] = [*menu_ids, new_id]
        seed(new_id)
        st.session_state[editing_key] = new_id
        st.rerun()
else:
    menu_id = editing
    st.subheader("3. 메뉴 정보 입력")
    source = st.radio("이 메뉴의 원가 입력 방식 *", ["unknown", "rate", "recipe"], format_func=PRICE_SOURCES.get,
                      horizontal=True, key=key(menu_id, "cost_source"))
    rate = None
    if source == "rate":
        rate = st.number_input("이 메뉴의 대략 원가율 * (0.35 = 35%)", min_value=0.0, max_value=1.0,
                               key=key(menu_id, "cost_rate"))
    elif source == "unknown":
        st.warning("이 메뉴는 35% 가정 원가율로 참고 계산합니다.")
    else:
        st.caption("이 메뉴의 재료 사용량과 실제 매입단가로 원가를 계산합니다.")
    ingredient_label = " *" if source in {"recipe", "actual"} else " · 선택"
    a, b, c = st.columns(3)
    with a:
        st.text_input("메뉴 이름 *", placeholder="예: 제육볶음 정식", key=key(menu_id, "name"))
        st.number_input("판매가(원) *", min_value=1.0, key=key(menu_id, "price"))
    with b:
        st.number_input("최근 4주 하루 평균 판매량 · 선택", min_value=0.0, value=None,
                        placeholder="모르면 비워두세요", key=key(menu_id, "volume"))
        has_packaging = st.checkbox("포장 판매를 함", key=key(menu_id, "has_packaging"))
        if has_packaging:
            st.number_input("판매 1건당 평균 포장비(원)", min_value=0.0, key=key(menu_id, "packaging"),
                            help="포장 주문 비중을 감안한 평균입니다. 예: 포장재 500원 × 포장 비중 20% = 100원")
    with c:
        has_fee = st.checkbox("카드·배달 수수료가 있음", key=key(menu_id, "has_fee"))
        if has_fee:
            st.number_input("평균 수수료율 (0.03 = 3%)", min_value=0.0, max_value=1.0, key=key(menu_id, "fee"),
                            help="카드·배달 주문을 합친 실제 매출 대비 평균 수수료율을 입력합니다.")
        has_labor = st.checkbox("판매 1건마다 추가 인력이 듦", key=key(menu_id, "has_labor"))
        if has_labor:
            st.number_input("건당 변동 인건비(원)", min_value=0.0, key=key(menu_id, "labor"))
    st.caption("레시피는 1인분/1건 기준입니다. 사용량과 매입단가의 단위는 같아야 합니다. 낮음·높음 단가를 비우면 기준 단가를 그대로 사용합니다.")
    if st.button("+ 재료 추가", key=key(menu_id, "add-ingredient")):
        new_index = st.session_state[key(menu_id, "ingredient_count")]
        for field, value in {"name": "", "quantity": 0.0, "unit": "g", "purchase": 0.0,
                             "purchase_low": None, "purchase_high": None, "public_id": "",
                             "price_mode": "direct"}.items():
            st.session_state[key(menu_id, f"ingredient.{new_index}.{field}")] = value
        st.session_state[key(menu_id, "ingredient_count")] = new_index + 1
        st.rerun()
    for index in range(st.session_state[key(menu_id, "ingredient_count")]):
        st.markdown(f"**재료 {index + 1}**")
        x, y, z, remove = st.columns([3, 2, 2, 1])
        with x:
            st.text_input("재료명" + ingredient_label, key=key(menu_id, f"ingredient.{index}.name"))
        with y:
            st.number_input("사용량" + ingredient_label, min_value=0.0, key=key(menu_id, f"ingredient.{index}.quantity"))
        with z:
            st.text_input("단위" + ingredient_label, key=key(menu_id, f"ingredient.{index}.unit"))
        with remove:
            st.write("")
            if st.button("×", key=key(menu_id, f"ingredient.{index}.remove")):
                # Shift later rows up, then shorten the visible recipe list.
                count = st.session_state[key(menu_id, "ingredient_count")]
                for later in range(index + 1, count):
                    for field in ("name", "quantity", "unit", "purchase", "purchase_low", "purchase_high", "public_id", "price_mode"):
                        st.session_state[key(menu_id, f"ingredient.{later - 1}.{field}")] = st.session_state.get(key(menu_id, f"ingredient.{later}.{field}"), "" if field in {"name", "unit"} else 0)
                st.session_state[key(menu_id, "ingredient_count")] -= 1
                st.rerun()
        if source in {"recipe", "actual"}:
            price_mode = st.radio(
                "가격은 어디에서 가져올까요?",
                ["direct", "public"] if public_options else ["direct"],
                format_func={"direct": "내 매입단가 직접 입력", "public": "공개시장 가격 참고"}.get,
                horizontal=True, key=key(menu_id, f"ingredient.{index}.price_mode"),
            )
            if price_mode == "public":
                public_id = st.selectbox(
                    "같은 품종·등급·단위의 공개가격 품목을 선택하세요",
                    ["", *public_options],
                    format_func=lambda value: "품목을 선택하세요" if not value else public_options[value],
                    key=key(menu_id, f"ingredient.{index}.public_id"),
                )
                if public_id:
                    price = public_price_range(public_id)
                    st.info(f"{price['name']} · {price['unit']}당 "
                               f"낮음 {price['low']:,.0f}원 / 기준 {price['base']:,.0f}원 / 높음 {price['high']:,.0f}원 · "
                               f"관측 {price['observed_days']}일\n\n실제 매입가격과 다를 수 있으며, 선택한 공개가격이 계산에 사용됩니다.")
                else:
                    st.warning("계산에 사용할 공개가격 품목을 선택해 주세요.")
            else:
                base, lo, hi = st.columns(3)
                with base:
                    st.number_input("기준 매입단가(원) *", min_value=0.0,
                                    key=key(menu_id, f"ingredient.{index}.purchase"))
                with lo:
                    st.number_input("낮은 단가(원) · 선택", min_value=0.0, value=None,
                                    key=key(menu_id, f"ingredient.{index}.purchase_low"))
                with hi:
                    st.number_input("높은 단가(원) · 선택", min_value=0.0, value=None,
                                    key=key(menu_id, f"ingredient.{index}.purchase_high"))
    if st.button("메뉴 저장", type="primary", key=key(menu_id, "close")):
        st.session_state[editing_key] = None
        st.rerun()

def menu_payload(menu_id):
    ingredients = []
    for index in range(st.session_state[key(menu_id, "ingredient_count")]):
        ingredients.append({"name": st.session_state.get(key(menu_id, f"ingredient.{index}.name"), ""),
                            "quantity": st.session_state.get(key(menu_id, f"ingredient.{index}.quantity"), 0),
                            "unit": st.session_state.get(key(menu_id, f"ingredient.{index}.unit"), "g"),
                            "purchase_price": st.session_state.get(key(menu_id, f"ingredient.{index}.purchase"), 0),
                            "purchase_price_low": st.session_state.get(key(menu_id, f"ingredient.{index}.purchase_low")),
                            "purchase_price_high": st.session_state.get(key(menu_id, f"ingredient.{index}.purchase_high")),
                            "price_mode": st.session_state.get(key(menu_id, f"ingredient.{index}.price_mode"), "direct")})
        mode = st.session_state.get(key(menu_id, f"ingredient.{index}.price_mode"), "direct")
        ingredients[-1]["public_price_id"] = (st.session_state.get(
            key(menu_id, f"ingredient.{index}.public_id"), "") if mode == "public" else "")
    return {"id": menu_id, "name": st.session_state.get(key(menu_id, "name"), ""),
            "price": st.session_state.get(key(menu_id, "price"), 10000),
            "daily_volume": st.session_state.get(key(menu_id, "volume"), None),
            "packaging": st.session_state.get(key(menu_id, "packaging"), 0) if st.session_state.get(key(menu_id, "has_packaging"), False) else None,
            "fee_rate": st.session_state.get(key(menu_id, "fee"), 0) if st.session_state.get(key(menu_id, "has_fee"), False) else None,
            "variable_labor": st.session_state.get(key(menu_id, "labor"), 0) if st.session_state.get(key(menu_id, "has_labor"), False) else None,
            "cost_source": st.session_state.get(key(menu_id, "cost_source"), "rate"),
            "food_cost_rate": st.session_state.get(key(menu_id, "cost_rate"), None),
            "ingredients": ingredients}

st.divider()
if st.button("저장하고 실행안 비교하기", type="primary", disabled=editing is not None, key=prefix + ".save"):
    try:
        profile = profile_from_form({"buz": buz, "menus": [menu_payload(menu_id) for menu_id in st.session_state[ids_key]],
                                     "operating_days": operating_days, "price_source": "unknown", "food_cost_rate": None,
                                     "experiment_budget": experiment_budget,
                                     "extra_minutes_capacity": extra_minutes_capacity,
                                     "sales_volume_basis": sales_volume_basis})
        profiles[profile_key] = profile
        st.session_state["store_profile_selection"] = profile_key
        st.success(f"메뉴 {len(profile.menus)}개를 저장했습니다. 이제 지역 진단 후보를 내 가게 기준으로 비교할 수 있습니다.")
        st.page_link("pages/3_추천_손익_검증.py", label="실행안 비교 결과 보기 →")
    except ValueError as exc:
        st.error(str(exc))

footer()
