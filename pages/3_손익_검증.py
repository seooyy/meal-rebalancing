"""3단계: 지역 진단에서 찾은 실행안의 손익 검증."""
import streamlit as st

from src.screen2 import evaluate_profile_candidates
from ui.common import BUZ_OPTIONS, context_bar, diagnosis, footer, page_setup, stepper, won_exact
from ui.recommend import action_specs, render as render_recommendation, shortlist

page_setup("3단계. 손익 검증")
stepper(3)
profiles = st.session_state.get("store_profiles", {})
st.caption("지역 진단에서 찾은 실행안을 우리 가게의 메뉴와 비용 조건으로 계산해 비교합니다.")


def display_text(text):
    return str(text).replace("·", ", ")

profile_key = st.session_state.get("store_profile_selection")
profile = profiles.get(profile_key) if profile_key else None
if profile is None or not isinstance(profile_key, tuple) or len(profile_key) != 2:
    st.warning("먼저 가게 정보를 저장해 주세요.")
    st.page_link("pages/2_가게_정보.py", label="가게 정보 입력하기 →")
else:
    region, buz = profile_key
    buz_name = next((name for name, code in BUZ_OPTIONS.items() if code == buz), buz)
    context_bar(region, buz_name)
    dg = diagnosis(region, buz)
    picked = shortlist(dg)
    if picked["state"] != "filtered":
        st.info("지역 진단에서 손익을 비교할 실행안을 찾지 못했습니다.")
        for line in picked["notes"]:
            st.caption(line)
    else:
        specs = action_specs(dg)
        st.subheader("1. 메뉴 선택")
        target_menu_id = st.selectbox(
            "어떤 메뉴에 적용할까요?", [menu.id for menu in profile.menus],
            format_func=lambda menu_id: next(menu.name for menu in profile.menus if menu.id == menu_id),
        )
        selected = next(menu for menu in profile.menus if menu.id == target_menu_id)
        cols = st.columns(4)
        cols[0].metric("판매가격", won_exact(selected.price))
        cols[1].metric("기준 재료비", won_exact(selected.unit_food_cost))
        cols[2].metric("건당 공헌이익", won_exact(selected.unit_contribution))
        cols[3].metric("하루 판매량", "미입력" if selected.daily_volume is None else f"{selected.daily_volume:,.0f}건")

        st.subheader("2. 실행안 조건")
        st.caption("실행안을 펼쳐 가격, 비용, 적용 범위를 조정해 주세요. 입력값을 바꾸면 비교 결과에 바로 반영됩니다.")
        labels = {"price_delta": "판매가격 증감(원)", "food_cost_delta": "한 건당 재료비 증감(원)",
                  "application_rate": "전체 주문 중 적용 비율(1 = 100%)", "setup_cost": "4주 동안 드는 초기 비용(원)",
                  "extra_minutes": "주문 한 건당 추가 시간(분)", "extra_labor_cost": "주문 한 건당 추가 인건비(원)"}
        defaults = {"price_delta": 0.0, "food_cost_delta": 0.0, "application_rate": 1.0,
                    "setup_cost": 0.0, "extra_minutes": 0.0, "extra_labor_cost": 0.0}
        for spec in specs:
            assumptions = dict(spec.get("assumptions", {}))
            summary = (f"가격 {assumptions.get('price_delta', 0):+,.0f}원, "
                       f"재료비 {assumptions.get('food_cost_delta', 0):+,.0f}원, "
                       f"초기 비용 {assumptions.get('setup_cost', 0):,.0f}원")
            with st.expander(f'{display_text(spec["title"])}  |  {summary}'):
                st.write(display_text(spec["action"]))
                st.caption("실행 전에 확인할 내용: " + display_text(spec["precheck"]))
                cols = st.columns(3)
                for index, field in enumerate(defaults):
                    with cols[index % 3]:
                        kwargs = {"step": 100.0, "format": "%.0f"} if field in {
                            "price_delta", "food_cost_delta", "setup_cost", "extra_labor_cost"
                        } else {"step": 0.1, "format": "%.1f"}
                        assumptions[field] = st.number_input(
                            labels[field], value=float(assumptions.get(field, defaults[field])),
                            min_value=0.0 if field not in {"price_delta", "food_cost_delta"} else None,
                            max_value=1.0 if field == "application_rate" else None,
                            key=f"assumption.{region}.{buz}.{spec['id']}.{field}", **kwargs,
                        )
                spec["assumptions"] = assumptions
        result = evaluate_profile_candidates(
            profile, target_menu_id, action_specs=specs,
            context={"지역": region, "업종": buz_name, "입력 경로": "지역 진단 후보 + 가게 정보"},
        )
        st.subheader("3. 비교 결과")
        render_recommendation(result, dg)
        over_budget = [o["name"] for o in result["options"]
                       if float(o.get("setup_cost", 0)) > profile.experiment_budget]
        over_capacity = [o["name"] for o in result["options"]
                         if float(o.get("extra_minutes", 0)) > profile.extra_minutes_capacity]
        if profile.experiment_budget > 0 and over_budget:
            st.warning("입력한 예산을 넘는 실행안: " + ", ".join(display_text(name) for name in over_budget))
        if profile.extra_minutes_capacity > 0 and over_capacity:
            st.warning("입력한 추가 작업 시간을 넘는 실행안: " + ", ".join(display_text(name) for name in over_capacity))
        if profile.sales_volume_basis == "estimate":
            st.warning("판매량을 기억에 따라 입력했으므로 공헌이익과 추가 판매량은 참고용입니다. 가능하면 최근 4주 POS나 주문내역으로 다시 입력해 주세요.")
        st.page_link("pages/2_가게_정보.py", label="가게 정보 수정하기 →")

footer()
