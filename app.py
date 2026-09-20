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

c1, c2, c3 = st.columns(3)
with c1:
    st.subheader("화면 1 · 지역 진단")
    st.caption("지역×업종 지표, 전국 기준선 병기, 유사 지역 비교, 실행 후보")
    st.page_link("pages/1_지역_진단.py", label="열기 →")
with c2:
    st.subheader("화면 2 · 가게 정보")
    st.caption("전체 메뉴·원가·판매량으로 후보 손익 순위의 계산 기준 입력")
    st.page_link("pages/2_가게_정보.py", label="열기 →")
with c3:
    st.subheader("화면 3 · 후보 손익 순위")
    st.caption("화면 1 후보만 같은 가게 조건에서 필요한 판매 증가율 순으로 비교")
    st.page_link("pages/3_추천_손익_검증.py", label="열기 →")

st.divider()
st.caption("담당 — 화면 껍데기·화면 1: C / 화면 2: B / 집계·진단: A")
footer()
