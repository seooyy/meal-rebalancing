"""외식 소비 리밸런싱 — 진입점. C 소유.

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

c1, c2 = st.columns(2)
with c1:
    st.subheader("화면 1 · 지역 진단")
    st.caption("지역×업종 지표, 전국 기준선 병기, 유사 지역 비교, 실행 후보")
    st.page_link("pages/1_지역_진단.py", label="열기 →")
with c2:
    st.subheader("화면 2 · 손익 시뮬레이터")
    st.caption("메뉴 구성별 건당 공헌이익과 필요 판매량")
    st.page_link("pages/2_손익_시뮬레이터.py", label="열기 →")

st.divider()
st.caption("담당 — 화면 껍데기·화면 1: C / 화면 2: B / 집계·진단: A")
footer()
