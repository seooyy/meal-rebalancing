"""공통 레이아웃, 문구, 데이터 로더와 표시 형식."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent

BUZ_KOREAN, BUZ_WESTERN = "8001", "8006"
BUZ_OPTIONS = {"일반한식": BUZ_KOREAN, "서양음식": BUZ_WESTERN}

NOTE_SOURCE = "지역 소비 지표는 BC카드 결제 데이터를 집계한 결과입니다."

CSS = """
<style>
  .block-container { padding-top: 2.2rem; max-width: 1100px; }
  .mr-note {
      background: rgba(127,127,127,.10); border-left: 3px solid rgba(127,127,127,.45);
      padding: .55rem .8rem; border-radius: 4px; font-size: .84rem;
      line-height: 1.5; margin: .35rem 0;
  }
  .mr-steps { display:flex; gap:.45rem; margin:.1rem 0 1.15rem; flex-wrap:wrap; }
  .mr-step { padding:.38rem .72rem; border-radius:999px; font-size:.82rem;
      border:1px solid rgba(127,127,127,.3); opacity:.68; }
  .mr-step-active { opacity:1; font-weight:700; border-color:#2563eb;
      background:rgba(37,99,235,.12); }
  .mr-step-done { opacity:1; background:rgba(22,163,74,.10); }
  .mr-context { display:flex; gap:.5rem; flex-wrap:wrap; margin:-.25rem 0 1rem; }
  .mr-context span { padding:.22rem .55rem; border-radius:5px;
      background:rgba(127,127,127,.10); font-size:.8rem; }
  .mr-verdict {
      background: rgba(127,127,127,.07); border-left: 3px solid rgba(127,127,127,.45);
      border-radius: 4px; padding: .65rem .9rem; margin: .4rem 0 .9rem;
  }
  .mr-verdict-why { font-size: .86rem; line-height: 1.55; }
  .mr-pri {
      display: inline-block; padding: .1rem .5rem; border-radius: 999px;
      font-size: .74rem; font-weight: 600; margin-right: .45rem;
      border: 1px solid transparent;
  }
  .mr-pri-high { background: rgba(220,38,38,.14); color: #b91c1c; border-color: rgba(220,38,38,.35); }
  .mr-pri-mid  { background: rgba(217,119,6,.14); color: #b45309; border-color: rgba(217,119,6,.35); }
  .mr-pri-low  { background: rgba(127,127,127,.14); color: #6b7280; border-color: rgba(127,127,127,.35); }
  .mr-card {
      border: 1px solid rgba(127,127,127,.28); border-radius: 8px;
      box-sizing: border-box; width: 100%; padding: .85rem 1rem; margin: .5rem 0;
  }
  .mr-card-head {
      display: flex; flex-wrap: wrap; gap: .4rem 1rem;
      align-items: baseline; justify-content: space-between;
  }
  .mr-card-num { font-size: .78rem; opacity: .75; }
  .mr-card-desc { font-size: .84rem; margin: .5rem 0 .25rem; opacity: .9; }
  .mr-card-list { margin: .2rem 0 0; padding-left: 1.15rem; font-size: .89rem; line-height: 1.65; }
  .mr-card-note { font-size: .8rem; margin-top: .5rem; opacity: .75; }
  .mr-check-list { margin: .35rem 0 .1rem; padding-left: 1.25rem; font-size: .86rem; line-height: 1.5; }
  .mr-check-list li { margin-bottom: .6rem; }
  .mr-check-name { font-weight: 600; }
  .mr-check-stop {
      display: inline-block; padding: .04rem .38rem; border-radius: 3px; margin-left: .35rem;
      font-size: .7rem; font-weight: 600; vertical-align: .05rem;
      background: rgba(127,127,127,.16); border: 1px solid rgba(127,127,127,.35);
  }
  .mr-check-see { display: block; opacity: .85; margin-top: .1rem; }
  @media (prefers-color-scheme: dark) {
    .mr-pri-high { color: #fca5a5; }
    .mr-pri-mid  { color: #fbbf24; }
    .mr-pri-low  { color: #9ca3af; }
  }
</style>
"""


def page_setup(title: str) -> None:
    """모든 화면의 첫 줄에서 부른다. 페이지 설정 + CSS + 제목."""
    st.set_page_config(page_title=f"{title} | 외식 소비 리밸런싱", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)


def note(text: str) -> None:
    st.markdown(f'<div class="mr-note">{text}</div>', unsafe_allow_html=True)


def stepper(current: int) -> None:
    labels = ("지역 진단", "가게 정보 입력", "손익 검증")
    items = []
    for index, label in enumerate(labels, 1):
        state = "mr-step-active" if index == current else "mr-step-done" if index < current else ""
        mark = "✓" if index < current else str(index)
        items.append(f'<span class="mr-step {state}">{mark} {label}</span>')
    st.markdown('<div class="mr-steps">' + ''.join(items) + '</div>', unsafe_allow_html=True)


def context_bar(region: str, buz_name: str) -> None:
    st.markdown(f'<div class="mr-context"><span>지역: {region}</span>'
                f'<span>업종: {buz_name}</span></div>', unsafe_allow_html=True)


def footer() -> None:
    """모든 화면 맨 아래에 데이터 출처만 표시한다."""
    st.divider()
    note(NOTE_SOURCE)


# ---- 데이터 ----------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_csv(name: str) -> pd.DataFrame:
    """data/out/ 의 CSV를 읽는다. 없으면 빈 DataFrame."""
    p = ROOT / "data" / "out" / name
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
    """지역과 업종 선택. 지역 진단과 가게 정보 단계가 같은 위젯을 쓴다.

    반환: (region_key, buz_code, buz_name)
    지역은 반드시 region_key('시도 시군구')다. 시군구명만 쓰면 중구가 6곳 합쳐진다.
    """
    keys = region_keys()
    region = st.selectbox(
        "지역",
        keys,
        index=keys.index("인천광역시 미추홀구") if "인천광역시 미추홀구" in keys else 0,
        key="sel_region",
    )
    buz_nm = st.selectbox("업종", list(BUZ_OPTIONS), key="sel_buz")
    return region, BUZ_OPTIONS[buz_nm], buz_nm


# ---- 카드 집계 -------------------------------------------------------------
#
# 집계는 A의 src/load.py 를 그대로 거친다. 화면에서 groupby를 직접 쓰지 않는다.
# (계약 6-2·6-6절: 업종 합산과 동명 시군구 합산을 load.py 가 막아준다)

@st.cache_data(show_spinner="카드 데이터를 읽는 중…")
def card() -> pd.DataFrame:
    """카드 원본 + 파생 열. 이미 집계된 24만 행이라 1초 안에 읽힌다."""
    from src.load import load_card

    return load_card(ROOT / "data" / "ABP_CONTEST_DATA.csv")


@st.cache_data(show_spinner=False)
def _region_parts() -> dict[str, tuple[str, str]]:
    """region_key -> (SIDO_NM, CCG_NM). aggregate()가 둘을 따로 받는다."""
    pop = load_csv("population_2026m1.csv")
    if len(pop):
        return {r.region_key: (r.SIDO_NM, r.CCG_NM) for r in pop.itertuples()}
    rk = load_csv("region_keys.csv")
    return {f"{r.SIDO_NM} {r.CCG_NM}": (r.SIDO_NM, r.CCG_NM) for r in rk.itertuples()}


def split_region(region_key: str) -> tuple[str, str]:
    """'경기도 고양시 덕양구' -> ('경기도', '고양시 덕양구').

    표를 먼저 찾고 없을 때만 첫 공백으로 자른다. 시군구명에 공백이 있는
    지역(고양시 덕양구 등)이 있어 뒤쪽 공백으로 자르면 안 된다.
    """
    parts = _region_parts()
    if region_key in parts:
        return parts[region_key]
    sido, _, ccg = region_key.partition(" ")
    return sido, ccg


@st.cache_data(show_spinner=False)
def region_metrics(region_key: str, buz: str, group_by: str | None = None) -> pd.DataFrame:
    """지역×업종 A/B 지표. 관측이 없으면 빈 DataFrame."""
    from src.load import aggregate

    sido, ccg = split_region(region_key)
    try:
        return aggregate(card(), region=ccg, buz=buz, sido=sido, group_by=group_by)
    except ValueError:
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def baseline(buz: str, group: str = "전체") -> pd.Series | None:
    """전국 기준선 한 행. 계약 6-5절에 따라 지역 수치 옆에 반드시 병기한다."""
    nb = load_csv("national_baseline_v1.csv")
    if not len(nb):
        return None
    hit = nb[(nb["TP_BUZ_NO"].astype(str) == str(buz)) & (nb["집단"] == group)]
    return hit.iloc[0] if len(hit) else None


# ---- 표시 형식 -------------------------------------------------------------

def won(v: float) -> str:
    if pd.isna(v):
        return "—"
    if abs(v) >= 1e8:
        return f"{v / 1e8:,.2f}억원"
    if abs(v) >= 1e4:
        return f"{v / 1e4:,.0f}만원"
    return f"{v:,.0f}원"


def cases(v: float) -> str:
    return "—" if pd.isna(v) else f"{v:,.0f}건"


def pct(v: float) -> str:
    return "—" if pd.isna(v) else f"{v:+.2f}%"


def pp(v: float) -> str:
    """%p. 전국 대비 초과분에 쓴다."""
    return "—" if pd.isna(v) else f"{v:+.2f}%p"


def won_exact(v: float) -> str:
    """원 단위 그대로. 건당 결제금액처럼 만/억으로 뭉개면 안 되는 값에 쓴다."""
    return "—" if pd.isna(v) else f"{v:,.0f}원"


# 두 비교 기간 중 적은 결제건수가 이 값보다 작으면 변화율을 숨긴다.

MIN_CASES = 1000
NOTE_THIN = "관측량 부족"


def obs_count(cnt_a: float, cnt_b: float) -> float:
    """두 기간 중 적은 쪽 건수. 변화율의 신뢰도는 이쪽이 결정한다."""
    if pd.isna(cnt_a) or pd.isna(cnt_b):
        return 0.0
    return min(float(cnt_a), float(cnt_b))


def observed(cnt_a: float, cnt_b: float) -> bool:
    """A·B 두 기간 모두 기준 건수 이상 관측됐는가."""
    return obs_count(cnt_a, cnt_b) >= MIN_CASES


# ---- 진단 (A의 src/diagnose.py) --------------------------------------------

@st.cache_data(show_spinner=False)
def diagnosis(region_key: str, buz: str) -> dict | None:
    """단일 셀 진단. 판정 + 실행 후보 + 게이트 기록.

    계약 4절: 후보가 비었으면 화면에 아무것도 그리지 않는다. 빈 목록을
    '문제 없음'으로 바꿔 쓰지 않는다. '게이트' 문자열은 개발용이라 노출하지 않는다.
    """
    from src.diagnose import diagnose

    sido, ccg = split_region(region_key)
    try:
        return diagnose(card(), region=ccg, buz=buz, sido=sido)
    except (ValueError, KeyError):
        return None


_PRI_CLASS = {"높음": "mr-pri-high", "중간": "mr-pri-mid",
              "낮음": "mr-pri-low", "없음": "mr-pri-low"}


def priority_badge(priority: str) -> str:
    return f'<span class="mr-pri {_PRI_CLASS.get(priority, "mr-pri-low")}">우선순위 {priority}</span>'


# ---- 확인 항목 안내 --------------------------------------------------------
#
# A의 rules.yaml은 확인할 항목의 이름만 준다 ("영업일·품절·주문 불편·고객 의견").
# 이름만으로는 무엇을 꺼내 보고 봤으면 뭐가 갈리는지 알 수 없어서,
# C가 소유하는 config/check_guide.yaml로 항목마다 세 줄을 붙인다.

CHECK_GUIDE_PATH = ROOT / "config" / "check_guide.yaml"


@st.cache_data(show_spinner=False)
def check_guide(path: str = str(CHECK_GUIDE_PATH)) -> dict:
    import yaml

    guide = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not guide.get("items"):
        raise ValueError(f"{path}에 items가 없습니다.")
    return guide["items"]


def split_checks(text: str) -> list[str]:
    """A의 확인 문자열을 항목으로 끊는다.

    '영업일·품절·주문 불편·고객 의견, 그리고 메뉴 판매 비중·옵션 선택률'
      -> ['영업일', '품절', '주문 불편', '고객 의견', '메뉴 판매 비중', '옵션 선택률']

    '실제 이용 언어와 주문의 어려움'처럼 구분자가 없으면 통째로 한 항목이다.
    """
    items = []
    for chunk in str(text or "").split(", 그리고 "):
        items += [p.strip() for p in chunk.split("·") if p.strip()]
    return items


# ---- 외식 물가 (단계 6-A) --------------------------------------------------

@st.cache_data(show_spinner=False)
def cpi_change(buz: str) -> float | None:
    """업종별 외식 물가 변화율 %. data/out/cpi_dineout.csv 가 없으면 None.

    None이면 화면은 물가 섹션을 조용히 접는다. 참고 지표라서 없다고 해서
    나머지 화면이 막히면 안 된다.
    """
    df = load_csv("cpi_dineout.csv")
    if not len(df):
        return None
    # 업종 코드가 float으로 읽혀 '8001.0'이 되는 경우를 막는다.
    code = df["buz"].astype(str).str.replace(r"\.0$", "", regex=True)
    hit = df[(code == str(buz)) & (df["수준"] == "업종")]
    return float(hit.iloc[0]["chg_pct"]) if len(hit) else None
