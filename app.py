"""외식 소비 리밸런싱 Streamlit 진입점.

    streamlit run app.py
"""

import streamlit as st

from ui.common import NOTE_SOURCE, NOTE_VOLUME, footer, note, page_setup

page_setup("외식 소비 리밸런싱")

st.markdown(
    "지역·업종별 카드 결제 흐름을 전국 기준선·유사 지역과 나란히 놓고 보고, "
    "실행안의 **달성 조건**을 계산한다."
)

note(f"{NOTE_SOURCE} · {NOTE_VOLUME}")

c1, c2, c3 = st.columns(3)
with c1:
    st.subheader("1단계 · 지역 진단")
    st.caption("지역×업종 지표, 전국 기준선 병기, 유사 지역 비교, 실행 후보")
    st.page_link("pages/1_지역_진단.py", label="열기 →")
with c2:
    st.subheader("2단계 · 가게 정보")
    st.caption("메뉴·원가·판매량과 운영 여력을 입력해 계산 기준 설정")
    st.page_link("pages/2_가게_정보.py", label="열기 →")
with c3:
    st.subheader("3단계 · 실험안 비교")
    st.caption("지역 진단 후보의 가정을 조정하고 필요한 판매 증가율 순으로 비교")
    st.page_link("pages/3_추천_손익_검증.py", label="열기 →")

footer()
