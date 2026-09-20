"""Rank screen-1 candidates by the saved store's profit conditions."""
import streamlit as st

from src.screen2 import evaluate_profile_candidates
from ui.common import BUZ_OPTIONS, diagnosis, footer, page_setup
from ui.recommend import action_specs, render as render_recommendation, shortlist

page_setup("추천 결과")
profiles = st.session_state.get("store_profiles", {})
st.subheader("내 가게 추천 결과")
st.caption("가게 정보와 후보 기본 가정으로 공헌이익 부담을 비교합니다. 지역 진단은 후보를 고르는 데만 사용하며 이 화면에서 손익 근거로 다시 해석하지 않습니다.")

profile_key = st.session_state.get("store_profile_selection")
profile = profiles.get(profile_key) if profile_key else None
if profile is None or not isinstance(profile_key, tuple) or len(profile_key) != 2:
    st.warning("먼저 가게 정보를 저장해 주세요.")
    st.page_link("pages/2_가게_정보.py", label="가게 정보 입력하기 →")
else:
    region, buz = profile_key
    buz_name = next((name for name, code in BUZ_OPTIONS.items() if code == buz), buz)
    st.caption(f"가게 정보 기준: {region} · {buz_name}")
    dg = diagnosis(region, buz)
    picked = shortlist(dg)
    if picked["state"] != "filtered":
        st.info("화면 1에서 비교할 실행 후보가 만들어지지 않았습니다.")
        for line in picked["notes"]:
            st.caption(line)
    else:
        specs = action_specs(dg)
        st.caption("화면 1에서 넘긴 후보를 동일한 메뉴와 가게 조건으로 계산합니다.")
        target_menu_id = st.selectbox(
            "변경을 검토할 메뉴 *", [menu.id for menu in profile.menus],
            format_func=lambda menu_id: next(menu.name for menu in profile.menus if menu.id == menu_id),
        )
        result = evaluate_profile_candidates(
            profile, target_menu_id, action_specs=specs,
            context={"지역": region, "업종": buz_name, "입력 경로": "화면 1 후보 + 가게 정보"},
        )
        render_recommendation(result, dg)
        if profile.sales_volume_basis == "estimate":
            st.warning("판매량이 대략값이므로 공헌이익과 하루 추가 판매량도 참고 수준입니다. 가능하면 최근 4주 POS·주문내역으로 바꿔 주세요.")
        st.page_link("pages/2_가게_정보.py", label="가게 정보 수정하기 →")

footer()
