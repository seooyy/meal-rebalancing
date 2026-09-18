"""화면 공통 껍데기 — C 소유.

레이아웃·CSS·고정 문구·데이터 로더를 여기 모은다.
**화면 파일(pages/)에서 CSS나 고정 문구를 다시 쓰지 않는다.** 둘이 따로 고치면 어긋난다.

B에게: 2일차에 `pages/2_손익_시뮬레이터.py` 안쪽만 채운다.
이 파일과 `app.py`는 C가 소유한다. 바꿀 게 있으면 요청한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent

BUZ_KOREAN, BUZ_WESTERN = "8001", "8006"
BUZ_OPTIONS = {"일반한식": BUZ_KOREAN, "서양음식": BUZ_WESTERN}

# 계약 10절. 화면에 반드시 남는 문구다. 지우지 않는다.
NOTE_SOURCE = "BC카드 관측 집계 기준"
NOTE_SEASON = "5월 결제금액이 전국 평균 대비 약 +11%로 높음 — 계절 요인 포함"
NOTE_VOLUME = "필요 판매량은 달성 조건이며 판매 예측이 아니다"
BADGE_DEMO = "가상 사례"

CSS = """
<style>
  .block-container { padding-top: 2.2rem; max-width: 1100px; }
  .mr-note {
      background: rgba(127,127,127,.10); border-left: 3px solid rgba(127,127,127,.45);
      padding: .55rem .8rem; border-radius: 4px; font-size: .84rem;
      line-height: 1.5; margin: .35rem 0;
  }
  .mr-badge {
      display: inline-block; padding: .12rem .5rem; border-radius: 999px;
      font-size: .74rem; font-weight: 600; letter-spacing: .01em;
      background: rgba(217,119,6,.16); color: #b45309; border: 1px solid rgba(217,119,6,.35);
  }
  .mr-tag {
      display: inline-block; padding: .08rem .42rem; border-radius: 3px;
      font-size: .72rem; margin-left: .3rem; border: 1px solid rgba(127,127,127,.4);
  }
  .mr-todo {
      border: 1px dashed rgba(127,127,127,.5); border-radius: 6px;
      padding: 1.1rem; text-align: center; color: rgba(127,127,127,.95); font-size: .88rem;
  }
  @media (prefers-color-scheme: dark) { .mr-badge { color: #fbbf24; } }
</style>
"""


def page_setup(title: str) -> None:
    """모든 화면의 첫 줄에서 부른다. 페이지 설정 + CSS + 제목."""
    st.set_page_config(page_title=f"{title} · 외식 소비 리밸런싱", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)


def note(text: str) -> None:
    st.markdown(f'<div class="mr-note">{text}</div>', unsafe_allow_html=True)


def badge(text: str = BADGE_DEMO) -> str:
    return f'<span class="mr-badge">{text}</span>'


def tag(kind: str) -> str:
    """관측값 / 추정값 / 가정값 태그. 계약상 모든 입력 필드에 붙는다."""
    return f'<span class="mr-tag">{kind}</span>'


def todo(owner: str, what: str) -> None:
    st.markdown(f'<div class="mr-todo"><b>{owner}</b> 담당 — {what}<br>2일차 작업 구역</div>',
                unsafe_allow_html=True)


def footer() -> None:
    """모든 화면 맨 아래. 출처와 계절 요인 주석을 고정한다."""
    st.divider()
    note(f"{NOTE_SOURCE} · {NOTE_SEASON}")
    st.caption("주민 1인당 환산은 하지 않는다. CCG_NM이 가맹점 소재지인지 고객 거주지인지 미확인.")


# ---- 데이터 ----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_csv(name: str) -> pd.DataFrame:
    """out/ 의 CSV를 읽는다. 없으면 빈 DataFrame."""
    p = ROOT / "out" / name
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, encoding="utf-8-sig")


@st.cache_data(show_spinner=False)
def region_keys() -> list[str]:
    pop = load_csv("population_2026m1.csv")
    if len(pop):
        return sorted(pop["region_key"].tolist())
    rk = load_csv("region_keys.csv")
    return sorted((rk["SIDO_NM"] + " " + rk["CCG_NM"]).tolist()) if len(rk) else []


def selector() -> tuple[str, str, str]:
    """지역·업종 선택. 화면 1·2가 같은 위젯을 쓴다.

    반환: (region_key, buz_code, buz_name)
    지역은 반드시 region_key('시도 시군구')다. 시군구명만 쓰면 중구가 6곳 합쳐진다.
    """
    keys = region_keys()
    c1, c2 = st.columns([3, 2])
    with c1:
        region = st.selectbox("지역", keys,
                              index=keys.index("인천광역시 미추홀구") if "인천광역시 미추홀구" in keys else 0,
                              key="sel_region")
    with c2:
        buz_nm = st.radio("업종", list(BUZ_OPTIONS), horizontal=True, key="sel_buz")
    return region, BUZ_OPTIONS[buz_nm], buz_nm
