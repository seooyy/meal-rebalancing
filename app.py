"""한 끼 리밸런싱 Streamlit 진입점.

    streamlit run app.py
"""

import streamlit as st

from ui.common import footer, page_setup


def home() -> None:
    page_setup("한 끼 리밸런싱")

    st.markdown(
        "외식 업종 소상공인을 위한 판매전략 추천 서비스입니다. "
        "지역 외식 소비의 변화를 전국 및 유사 지역과 비교해 진단하고, "
        "우리 가게에 맞는 실행안을 추천합니다."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("1단계. 지역 진단")
        st.caption("선택한 지역과 업종의 소비 변화를 전국 및 유사 지역과 비교해 문제를 진단하고 실행 후보를 찾습니다.")
        st.page_link("pages/1_지역_진단.py", label="열기 →")
    with c2:
        st.subheader("2단계. 가게 정보 입력")
        st.caption("메뉴 가격, 변동비, 판매량과 운영 조건을 입력해 우리 가게의 손익 기준을 만듭니다.")
        st.page_link("pages/2_가게_정보.py", label="열기 →")
    with c3:
        st.subheader("3단계. 손익 검증")
        st.caption("진단에 맞는 실행안별로 기존 이익을 지키는 데 필요한 판매량을 계산하고 비교합니다.")
        st.page_link("pages/3_손익_검증.py", label="열기 →")

    footer()


navigation = st.navigation(
    [
        st.Page(home, title="한 끼 리밸런싱", default=True),
        st.Page("pages/1_지역_진단.py", title="지역 진단"),
        st.Page("pages/2_가게_정보.py", title="가게 정보 입력"),
        st.Page("pages/3_손익_검증.py", title="손익 검증"),
    ],
    position="sidebar",
)
navigation.run()
