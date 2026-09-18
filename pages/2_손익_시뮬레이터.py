"""화면 2 · 손익 시뮬레이터 — B 소유.

이 파일 **안쪽만** 채운다. 레이아웃·CSS·고정 문구는 ui/common.py에서 가져다 쓴다.
직접 st.set_page_config 를 부르거나 CSS를 다시 쓰지 않는다.

쓸 수 있는 것:
    from ui.common import page_setup, note, badge, tag, todo, footer, selector
    badge()        -> '가상 사례' 배지 HTML
    tag("관측값")   -> 입력 필드 옆 태그 HTML (관측값/추정값/가정값)
    NOTE_VOLUME    -> "필요 판매량은 달성 조건이며 판매 예측이 아니다"
"""

import streamlit as st

from ui.common import NOTE_VOLUME, badge, footer, note, page_setup, todo

page_setup("화면 2 · 손익 시뮬레이터")

note(NOTE_VOLUME)
st.markdown(f"예시 매장 {badge()}", unsafe_allow_html=True)

st.subheader("입력")
todo("B", "메뉴 3개 × (판매가격·변동비·판매량), 각 필드에 관측값/추정값/가정값 태그")

st.subheader("결과")
todo("B", "대안별 건당 공헌이익 · 필요 판매량 · 필요 증가율")

st.caption("공헌이익은 순이익이 아니다. 임차료·인건비 등 고정비는 빼지 않은 금액이다.")
footer()
