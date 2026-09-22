"""2단계: 가게의 메뉴와 운영 조건 입력."""
import streamlit as st

from src.store_profile import (INGREDIENT_UNITS, PRICE_SOURCES,
                               normalize_ingredient_unit, normalize_price_source, profile_from_form,
                               public_price_options, public_price_range)
from ui.common import footer, page_setup, selector, stepper

page_setup("2단계. 가게 정보 입력")
stepper(2)
st.caption("메뉴별 판매가격, 비용, 하루 판매량을 입력해 실행안별로 현재 이익을 유지하는 데 필요한 판매량을 계산합니다. "
           "입력 내용은 현재 접속 중인 세션에만 저장됩니다.")
region, buz, buz_name = selector()
profiles = st.session_state.setdefault("store_profiles", {})
profile_key = (region, buz)
saved = profiles.get(profile_key) or profiles.get(buz)  # 이전 세션 입력 호환
prefix = f"profile.{buz}.{region}"
ids_key, editing_key, next_id_key = prefix + ".menu_ids", prefix + ".editing", prefix + ".next_id"
snapshot_key = prefix + ".editing_snapshot"

def key(menu_id, field):
    return f"{prefix}.{menu_id}.{field}"


def price_source_label(source):
    return PRICE_SOURCES.get(normalize_price_source(source), str(source))


def ui_unit(value):
    """Migrate common legacy spellings before binding a selectbox."""
    try:
        return normalize_ingredient_unit(value)
    except ValueError:
        return "g"

def seed(menu_id, menu=None):
    defaults = {"name": menu.name if menu else "", "price": menu.price if menu else 10000.0,
                "volume": menu.daily_volume if menu else None,
                "has_packaging": bool(menu and (menu.packaging or "포장비" not in menu.assumed_zero_fields)),
                "packaging": menu.packaging if menu else 0.0,
                "has_fee": bool(menu and (menu.fee_rate or "카드·배달 수수료" not in menu.assumed_zero_fields)),
                "fee": menu.fee_rate if menu else 0.0,
                "has_labor": bool(menu and (menu.variable_labor or "변동 인건비" not in menu.assumed_zero_fields)),
                "labor": menu.variable_labor if menu else 0.0,
                "cost_source": normalize_price_source(menu.cost_source) if menu else "rate",
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
                             "unit": ui_unit(ingredient.unit), "purchase": ingredient.purchase_price,
                             "purchase_low": ingredient.purchase_price_low,
                             "purchase_high": ingredient.purchase_price_high,
                             "public_id": ingredient.public_price_id or "",
                             "price_mode": "public" if ingredient.public_price_id else "direct"}.items():
            st.session_state.setdefault(key(menu_id, f"ingredient.{index}.{field}"), value)


def begin_edit(menu_id, is_new=False):
    menu_prefix = f"{prefix}.{menu_id}."
    st.session_state[snapshot_key] = {
        "menu_id": menu_id,
        "is_new": is_new,
        "values": {name: value for name, value in st.session_state.items() if name.startswith(menu_prefix)},
    }
    st.session_state[editing_key] = menu_id


def cancel_edit(menu_id):
    snapshot = st.session_state.pop(snapshot_key, {})
    menu_prefix = f"{prefix}.{menu_id}."
    for name in [name for name in st.session_state if name.startswith(menu_prefix)]:
        del st.session_state[name]
    if snapshot.get("is_new"):
        st.session_state[ids_key] = [item for item in st.session_state[ids_key] if item != menu_id]
    else:
        st.session_state.update(snapshot.get("values", {}))
    st.session_state[editing_key] = None


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
         "packaging": 300, "fee": .03, "labor": 450, "cost_source": "rate", "cost_rate": .35,
         "ingredients": []},
    ]
    st.session_state[ids_key] = [item["id"] for item in examples]
    st.session_state[next_id_key] = len(examples) + 1
    st.session_state[editing_key] = None
    st.session_state.pop(snapshot_key, None)
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


st.subheader("1. 영업 및 계산 조건")
st.caption("하루 평균 판매량은 최근 4주의 총판매량을 실제 영업일 수로 나눠 입력하는 것이 좋습니다.")
operating_days = st.number_input("최근 4주 실제 영업일 (필수)", min_value=1, max_value=28,
                                 value=int(saved_value("operating_days", 24)), key=prefix + ".days")
st.caption("메뉴별 판매량은 최근 4주 POS나 주문내역 기준 입력을 권장합니다. 정확한 값을 모르면 비워둘 수 있습니다.")

budget_col, capacity_col = st.columns(2)
with budget_col:
    experiment_budget = st.number_input("실행안 적용에 사용할 예산(원) (선택)", min_value=0.0,
                                        value=float(saved_value("experiment_budget", 0)), step=1000.0, format="%.0f",
                                        key=prefix + ".budget")
with capacity_col:
    extra_minutes_capacity = st.number_input("판매 1건당 추가로 투입할 수 있는 시간(분) (선택)", min_value=0.0,
                                             value=float(saved_value("extra_minutes_capacity", 0)), key=prefix + ".capacity")
st.caption("입력한 한도를 넘는 실행안이 있으면 손익 검증 화면에서 알려드립니다. 0은 한도를 입력하지 않은 것으로 처리합니다.")

st.subheader("2. 메뉴 목록")
public_options = public_price_options()
menu_ids = st.session_state[ids_key]
editing = st.session_state.get(editing_key)

add_col, example_col, _ = st.columns([1.2, 1.6, 5.2], gap="small", vertical_alignment="center")
with add_col:
    if st.button("메뉴 추가", type="primary", disabled=editing is not None,
                 width="stretch", key=prefix + ".add-menu"):
        new_id = f"menu_{st.session_state[next_id_key]}"
        st.session_state[next_id_key] += 1
        st.session_state[ids_key] = [*menu_ids, new_id]
        seed(new_id)
        begin_edit(new_id, is_new=True)
        st.rerun()
with example_col:
    st.button("예시 메뉴 불러오기", disabled=editing is not None,
              width="stretch", key=prefix + ".example", on_click=load_example)
st.caption("예시 메뉴를 불러오면 현재 메뉴 목록을 덮어씁니다.")

if not menu_ids:
    st.info("등록된 메뉴가 없습니다. 대표 메뉴부터 추가해 주세요.")
for menu_id in menu_ids:
    ingredient_count = st.session_state[key(menu_id, "ingredient_count")]
    filled_ingredients = sum(bool(st.session_state.get(key(menu_id, f"ingredient.{index}.name"), "").strip())
                             for index in range(ingredient_count))
    name = st.session_state.get(key(menu_id, "name"), "") or "이름 없는 메뉴"
    price = st.session_state.get(key(menu_id, "price"), 0)
    volume = st.session_state.get(key(menu_id, "volume"), None)
    with st.container(border=True):
        summary, actions = st.columns([7, 2], vertical_alignment="center")
        with summary:
            editing_label = " (수정 중)" if editing == menu_id else ""
            volume_text = "판매량 미입력" if volume is None else f"하루 {volume:,.0f}건"
            name_col, price_col, volume_col = st.columns([4, 2, 2])
            with name_col:
                st.markdown(f"**{name}**{editing_label}")
            with price_col:
                st.write(f"{price:,.0f}원")
            with volume_col:
                st.write(volume_text)
            source = st.session_state.get(key(menu_id, "cost_source"), "rate")
            st.caption(f"원가 입력 방식: {price_source_label(source)}, 등록한 재료 {filled_ingredients}개")
        with actions:
            edit_col, delete_col = st.columns(2, gap="small")
            with edit_col:
                if st.button("수정", disabled=editing is not None,
                             width="stretch", key=key(menu_id, "edit")):
                    begin_edit(menu_id)
                    st.rerun()
            with delete_col:
                if st.button("삭제", width="stretch", key=key(menu_id, "delete")):
                    st.session_state[ids_key] = [item for item in menu_ids if item != menu_id]
                    if editing == menu_id:
                        st.session_state[editing_key] = None
                        st.session_state.pop(snapshot_key, None)
                    st.rerun()

if editing is not None:
    menu_id = editing
    st.markdown("#### 메뉴 정보 입력")

    st.markdown("**기본 정보**")
    a, b, c = st.columns(3)
    with a:
        st.text_input("메뉴 이름 (필수)", placeholder="예: 제육볶음 정식", key=key(menu_id, "name"))
    with b:
        st.number_input("판매가(원) (필수)", min_value=1.0, step=100.0, format="%.0f",
                        key=key(menu_id, "price"))
    with c:
        st.number_input("최근 4주 하루 평균 판매량 (선택)", min_value=0.0, value=None,
                        placeholder="모르면 비워두세요", key=key(menu_id, "volume"))

    st.markdown("**판매 관련 비용**")
    packaging_col, fee_col, labor_col = st.columns(3)
    with packaging_col:
        has_packaging = st.checkbox("포장 판매를 함", key=key(menu_id, "has_packaging"))
        if has_packaging:
            st.number_input("판매 1건당 평균 포장비(원)", min_value=0.0, step=10.0, format="%.0f",
                            key=key(menu_id, "packaging"),
                            help="포장 주문 비중을 감안한 평균입니다. 예: 포장재 500원 × 포장 비중 20% = 100원")
    with fee_col:
        has_fee = st.checkbox("카드 및 배달 수수료가 있음", key=key(menu_id, "has_fee"))
        if has_fee:
            st.number_input("평균 수수료율 (0.03 = 3%)", min_value=0.0, max_value=1.0, key=key(menu_id, "fee"),
                            help="카드와 배달 주문을 합친 실제 매출 대비 평균 수수료율을 입력합니다.")
    with labor_col:
        has_labor = st.checkbox("판매 1건마다 추가 인력이 듦", key=key(menu_id, "has_labor"))
        if has_labor:
            st.number_input("건당 변동 인건비(원)", min_value=0.0, step=100.0, format="%.0f",
                            key=key(menu_id, "labor"))

    st.markdown("**원가 정보**")
    cost_source_key = key(menu_id, "cost_source")
    st.session_state[cost_source_key] = normalize_price_source(st.session_state.get(cost_source_key, "rate"))
    source = st.radio("원가 입력 방식 (필수)", ["rate", "recipe"], format_func=price_source_label,
                      horizontal=True, key=key(menu_id, "cost_source"))
    if source == "rate":
        st.number_input("원가율 (필수, 0.35 = 35%)", min_value=0.0, max_value=1.0,
                        key=key(menu_id, "cost_rate"))
    else:
        st.caption("재료별 사용량과 매입단가를 바탕으로 메뉴 원가를 계산합니다.")
        if public_options:
            st.success(f"매입단가를 참고할 수 있는 공개가격 품목이 {len(public_options)}개 있습니다.")
        else:
            st.info("현재 사용할 수 있는 공개가격이 없습니다. 실제 매입단가를 직접 입력해 주세요.")

        st.markdown("**재료 목록**")
        st.caption("판매 1건에 들어가는 재료를 입력해 주세요. 사용량과 매입단가는 선택한 같은 단위를 기준으로 계산합니다.")

        for index in range(st.session_state[key(menu_id, "ingredient_count")]):
            with st.container(border=True):
                count = st.session_state[key(menu_id, "ingredient_count")]
                entered_name = st.session_state.get(key(menu_id, f"ingredient.{index}.name"), "").strip()
                card_title = f"재료 {index + 1}" + (f" · {entered_name}" if entered_name else "")
                ingredient_name, remove = st.columns([6, 2], vertical_alignment="center")
                with ingredient_name:
                    st.markdown(f"**{card_title}**")
                with remove:
                    if st.button("재료 삭제", disabled=count <= 1, width="stretch",
                                 key=key(menu_id, f"ingredient.{index}.remove")):
                        for later in range(index + 1, count):
                            for field in ("name", "quantity", "unit", "purchase", "purchase_low", "purchase_high", "public_id", "price_mode"):
                                st.session_state[key(menu_id, f"ingredient.{later - 1}.{field}")] = st.session_state.get(key(menu_id, f"ingredient.{later}.{field}"), "" if field in {"name", "unit"} else 0)
                        st.session_state[key(menu_id, "ingredient_count")] -= 1
                        st.rerun()
                x, y, z = st.columns([3, 2, 2])
                with x:
                    st.text_input("재료명 (필수)", key=key(menu_id, f"ingredient.{index}.name"))
                with y:
                    st.number_input("사용량 (필수)", min_value=0.0, key=key(menu_id, f"ingredient.{index}.quantity"))
                with z:
                    mode_key = key(menu_id, f"ingredient.{index}.price_mode")
                    public_key = key(menu_id, f"ingredient.{index}.public_id")
                    if st.session_state.get(mode_key) == "public":
                        selected_public = public_price_range(st.session_state.get(public_key, ""))
                        st.text_input("단위 (공개가격 기준)",
                                      value=selected_public["unit"] if selected_public else "품목 선택 후 자동 적용",
                                      disabled=True, key=key(menu_id, f"ingredient.{index}.public_unit"))
                    else:
                        unit_key = key(menu_id, f"ingredient.{index}.unit")
                        st.session_state[unit_key] = ui_unit(st.session_state.get(unit_key, "g"))
                        st.selectbox("단위 (필수)", INGREDIENT_UNITS, key=unit_key)
                price_mode = st.radio(
                    "매입단가 입력 방식",
                    ["direct", "public"] if public_options else ["direct"],
                    format_func={"direct": "내 매입단가 직접 입력", "public": "공개시장 가격 참고"}.get,
                    horizontal=True, key=key(menu_id, f"ingredient.{index}.price_mode"),
                )
                if price_mode == "public":
                    public_id = st.selectbox(
                        "품종, 등급, 단위가 같은 공개가격 품목을 선택해 주세요",
                        ["", *public_options],
                        format_func=lambda value: "품목을 선택하세요" if not value else public_options[value],
                        key=key(menu_id, f"ingredient.{index}.public_id"),
                    )
                    if public_id:
                        price = public_price_range(public_id)
                        st.info(f"{price['name']}, {price['unit']}당 "
                                f"낮은 가격 {price['low']:,.0f}원 / 기준 가격 {price['base']:,.0f}원 / 높은 가격 {price['high']:,.0f}원, "
                                f"관측 기간 {price['observed_days']}일\n\n실제 매입가격과 다를 수 있으며, 선택한 공개가격을 계산에 사용합니다.")
                    else:
                        st.warning("계산에 사용할 공개가격 품목을 선택해 주세요.")
                else:
                    base, lo, hi = st.columns(3)
                    with base:
                        unit = st.session_state.get(key(menu_id, f"ingredient.{index}.unit"), "g")
                        st.number_input(f"기준 매입단가(원/{unit}) (필수)", min_value=0.0, step=100.0, format="%.0f",
                                        key=key(menu_id, f"ingredient.{index}.purchase"))
                    with lo:
                        st.number_input("낮은 단가(원) (선택)", min_value=0.0, value=None, step=100.0, format="%.0f",
                                        key=key(menu_id, f"ingredient.{index}.purchase_low"))
                    with hi:
                        st.number_input("높은 단가(원) (선택)", min_value=0.0, value=None, step=100.0, format="%.0f",
                                        key=key(menu_id, f"ingredient.{index}.purchase_high"))
        if st.button("＋ 재료 추가", width="stretch", key=key(menu_id, "add-ingredient")):
            new_index = st.session_state[key(menu_id, "ingredient_count")]
            for field, value in {"name": "", "quantity": 0.0, "unit": "g", "purchase": 0.0,
                                 "purchase_low": None, "purchase_high": None, "public_id": "",
                                 "price_mode": "direct"}.items():
                st.session_state[key(menu_id, f"ingredient.{new_index}.{field}")] = value
            st.session_state[key(menu_id, "ingredient_count")] = new_index + 1
            st.rerun()
        st.caption("낮은 단가와 높은 단가를 입력하지 않으면 기준 단가로 계산합니다.")

    _, save_col, cancel_col = st.columns([6, 1, 1], gap="small")
    with save_col:
        if st.button("메뉴 저장", type="primary", width="stretch", key=key(menu_id, "close")):
            st.session_state[editing_key] = None
            st.session_state.pop(snapshot_key, None)
            st.rerun()
    with cancel_col:
        if st.button("취소", width="stretch", key=key(menu_id, "cancel")):
            cancel_edit(menu_id)
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
if editing is not None:
    st.caption("편집 중인 메뉴를 먼저 저장하면 다음 단계로 이동할 수 있습니다.")
if st.button("저장하고 손익 검증하기", type="primary", disabled=editing is not None, key=prefix + ".save"):
    try:
        profile = profile_from_form({"buz": buz, "menus": [menu_payload(menu_id) for menu_id in st.session_state[ids_key]],
                                     "operating_days": operating_days, "price_source": "rate", "food_cost_rate": .35,
                                     "experiment_budget": experiment_budget,
                                     "extra_minutes_capacity": extra_minutes_capacity})
        profiles[profile_key] = profile
        st.session_state["store_profile_selection"] = profile_key
        st.success(f"메뉴 {len(profile.menus)}개를 저장했습니다. 이제 실행안별로 필요한 판매량을 비교할 수 있습니다.")
        st.page_link("pages/3_손익_검증.py", label="손익 검증 결과 보기 →")
    except ValueError as exc:
        st.error(str(exc))

footer()
