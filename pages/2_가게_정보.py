"""Step 2: store profile editor with a menu list and focused menu editor."""
import streamlit as st

from src.store_profile import PRICE_SOURCES, profile_from_form
from ui.common import footer, page_setup, selector

page_setup("가게 정보")
st.caption("손익 계산에 필요한 가게 숫자만 입력합니다. * 표시는 필수이며, 입력값은 이 브라우저 세션에만 저장됩니다.")
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
                "cost_source": menu.cost_source if menu else "rate",
                "cost_rate": menu.food_cost_rate if menu and menu.food_cost_rate is not None else .35,
                "ingredient_count": max(1, len(menu.ingredients) if menu else 1)}
    for field, value in defaults.items():
        st.session_state.setdefault(key(menu_id, field), value)
    for index in range(defaults["ingredient_count"]):
        for field, value in {"name": "", "quantity": 0.0, "unit": "g", "purchase": 0.0}.items():
            st.session_state.setdefault(key(menu_id, f"ingredient.{index}.{field}"), value)
    for index, ingredient in enumerate(menu.ingredients if menu else ()):
        for field, value in {"name": ingredient.name, "quantity": ingredient.quantity,
                             "unit": ingredient.unit, "purchase": ingredient.purchase_price}.items():
            st.session_state.setdefault(key(menu_id, f"ingredient.{index}.{field}"), value)


def load_example():
    """Replace the current draft with a small, internally consistent test store."""
    examples = [
        {"id": "menu_1", "name": "제육볶음 정식", "price": 10000, "volume": 25,
         "packaging": 300, "fee": .03, "labor": 500, "cost_source": "rate", "cost_rate": .38,
         "ingredients": []},
        {"id": "menu_2", "name": "김치찌개", "price": 9000, "volume": 18,
         "packaging": 300, "fee": .03, "labor": 400, "cost_source": "actual", "cost_rate": None,
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

st.subheader(f"{buz_name} · 최근 4주 기준")
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

st.subheader("메뉴 목록")
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
    source = st.radio("이 메뉴의 원가 입력 방식 *", list(PRICE_SOURCES), format_func=PRICE_SOURCES.get,
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
        st.number_input("최근 4주 하루 평균 판매량 *", min_value=0.0, placeholder="4주 총판매량 ÷ 실제 영업일", key=key(menu_id, "volume"))
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
    st.caption("레시피는 1인분/1건 기준입니다. 재료를 입력할 때는 재료명·사용량·단위·그 단위의 매입단가를 모두 입력하세요. 사용량과 매입단가의 단위는 같아야 합니다.")
    if st.button("+ 재료 추가", key=key(menu_id, "add-ingredient")):
        new_index = st.session_state[key(menu_id, "ingredient_count")]
        for field, value in {"name": "", "quantity": 0.0, "unit": "g", "purchase": 0.0}.items():
            st.session_state[key(menu_id, f"ingredient.{new_index}.{field}")] = value
        st.session_state[key(menu_id, "ingredient_count")] = new_index + 1
        st.rerun()
    for index in range(st.session_state[key(menu_id, "ingredient_count")]):
        x, y, z, w, remove = st.columns([3, 2, 2, 3, 1])
        with x:
            st.text_input("재료명" + ingredient_label, key=key(menu_id, f"ingredient.{index}.name"))
        with y:
            st.number_input("사용량" + ingredient_label, min_value=0.0, key=key(menu_id, f"ingredient.{index}.quantity"))
        with z:
            st.text_input("단위" + ingredient_label, key=key(menu_id, f"ingredient.{index}.unit"))
        with w:
            st.number_input("그 단위의 매입단가(원)" + ingredient_label, min_value=0.0, key=key(menu_id, f"ingredient.{index}.purchase"))
        with remove:
            st.write("")
            if st.button("×", key=key(menu_id, f"ingredient.{index}.remove")):
                # Shift later rows up, then shorten the visible recipe list.
                count = st.session_state[key(menu_id, "ingredient_count")]
                for later in range(index + 1, count):
                    for field in ("name", "quantity", "unit", "purchase"):
                        st.session_state[key(menu_id, f"ingredient.{later - 1}.{field}")] = st.session_state.get(key(menu_id, f"ingredient.{later}.{field}"), "" if field in {"name", "unit"} else 0)
                st.session_state[key(menu_id, "ingredient_count")] -= 1
                st.rerun()
    if st.button("메뉴 저장", type="primary", key=key(menu_id, "close")):
        st.session_state[editing_key] = None
        st.rerun()

def menu_payload(menu_id):
    ingredients = []
    for index in range(st.session_state[key(menu_id, "ingredient_count")]):
        ingredients.append({"name": st.session_state.get(key(menu_id, f"ingredient.{index}.name"), ""),
                            "quantity": st.session_state.get(key(menu_id, f"ingredient.{index}.quantity"), 0),
                            "unit": st.session_state.get(key(menu_id, f"ingredient.{index}.unit"), "g"),
                            "purchase_price": st.session_state.get(key(menu_id, f"ingredient.{index}.purchase"), 0)})
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
if st.button("가게 정보 저장하고 후보 순위 보기", type="primary", disabled=editing is not None, key=prefix + ".save"):
    try:
        profile = profile_from_form({"buz": buz, "goal": "sales", "menus": [menu_payload(menu_id) for menu_id in st.session_state[ids_key]],
                                     "operating_days": operating_days, "price_source": "unknown", "food_cost_rate": None,
                                     "experiment_budget": 0, "extra_minutes_capacity": 0,
                                     "sales_volume_basis": sales_volume_basis})
        profiles[profile_key] = profile
        st.session_state["store_profile_selection"] = profile_key
        st.success(f"메뉴 {len(profile.menus)}개를 저장했습니다. 이제 화면 1의 후보를 내 가게 기준으로 비교할 수 있습니다.")
        st.page_link("pages/3_추천_손익_검증.py", label="추천 결과 보기 →")
    except ValueError as exc:
        st.error(str(exc))

footer()
