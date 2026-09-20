"""카드 데이터 로더와 집계 함수.

한 끼 리밸런싱 프로젝트의 모든 카드 데이터 접근은 이 모듈을 거친다.
pandas.read_csv를 직접 쓰면 아래 실수가 조용히 발생한다.

  - 법인 코드가 소문자 'x'인데 대문자 'X'로 필터 -> 법인 금액 전부 누락
  - TP_BUZ_NO가 int로 읽혀 선행 0 소실
  - 일반한식과 서양음식을 합산 -> 업종 구성비 변화가 객단가 변화로 둔갑
  - 기간 일수(90/91) 대신 월 수(3)로 나눔

계약: docs/contract.md 4·5·6절
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 공통 상수 (docs/contract.md 5절)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CARD_PATH = "data/ABP_CONTEST_DATA.csv"

PERIOD_A = ["202601", "202602", "202603"]
PERIOD_B = ["202604", "202605", "202606"]
DAYS_A, DAYS_B = 90, 91
DAYS = {"A": DAYS_A, "B": DAYS_B}

# 법인은 소문자 'x'. 대문자 'X'가 아니다.
GROUP_MAP = {"1": "일반개인", "2": "일반개인", "3": "외국인", "x": "법인"}
GROUPS = ["일반개인", "외국인", "법인"]

# 연령 비교용. '1'(범위 미확인)과 'x'(법인)는 제외한다.
AGE_FOR_COMPARISON = ["2", "3", "4", "5", "6"]

BUZ_KOREAN = "8001"   # 일반한식
BUZ_WESTERN = "8006"  # 서양음식
BUZ_TARGETS = [BUZ_KOREAN, BUZ_WESTERN]

NOISE_BAND = 0.01  # ±1%. 이 안쪽은 "변화 미미"
SHARE_GATE = 0.05  # B기간 금액 비중 5% 미만이면 실행 후보에서 제외

# 로드 시 검증에 쓰는 관측 사실 (원본에서 실측)
EXPECTED_ROWS = 242_574
EXPECTED_MONTHS = set(PERIOD_A + PERIOD_B)
EXPECTED_GENDER_CD = {"1", "2", "3", "x"}
EXPECTED_AGE_CD = {"1", "2", "3", "4", "5", "6", "x"}

# 지역은 (SIDO_NM, CCG_NM) 쌍이 255개다. CCG_NM만 세면 233개다.
# '중구'는 6개 시도에, '동구'도 6개 시도에 있다. 시군구명만으로는 특정되지 않는다.
EXPECTED_REGION_PAIRS = 255
EXPECTED_CCG_NAMES = 233

CORP_AMT_SHARE_PCT = 6.13  # 전국 법인 금액 비중. 로더 정확성의 핵심 지표

_DTYPE = {
    "STRD_YYMM": str,
    "SIDO_NM": str,
    "CCG_NM": str,
    "GENDER_CD": str,
    "AGE_CD": str,
    "TP_BUZ_NO": str,
    "TP_BUZ_NM": str,
}


# ---------------------------------------------------------------------------
# 로드
# ---------------------------------------------------------------------------

def _resolve(path: str | Path) -> Path:
    """상대 경로를 프로젝트 루트 기준으로 푼다.

    작업 디렉터리가 어디든 동일하게 동작해야 한다. 노트북에서 import하는
    경우와 터미널에서 실행하는 경우의 cwd가 다르기 때문이다.
    """
    p = Path(path)
    if p.is_absolute():
        return p
    if p.exists():
        return p.resolve()
    return (PROJECT_ROOT / p).resolve()


def load_card(path: str | Path = DEFAULT_CARD_PATH, *, validate: bool = True) -> pd.DataFrame:
    """카드 원본을 읽어 타입을 고정하고 파생 열을 붙여 반환한다.

    파생 열:
      group  : '일반개인' | '외국인' | '법인'
      period : 'A' (202601~03) | 'B' (202604~06)
      days   : 해당 period의 일수 (90 또는 91)

    Parameters
    ----------
    path : 카드 CSV 경로. 상대 경로는 프로젝트 루트 기준으로 푼다.
    validate : True면 코드값·행수·관측월을 검사하고 어긋나면 예외를 던진다.

    Raises
    ------
    FileNotFoundError : 파일이 없을 때. 확보 방법은 data/README.md 참조.
    ValueError : 예상 밖의 코드값이나 관측월이 있을 때.
    """
    src = _resolve(path)
    if not src.exists():
        raise FileNotFoundError(
            f"카드 데이터를 찾을 수 없습니다: {src}\n"
            "공모전 제공 파일이라 git에 없습니다. data/README.md의 안내를 따르세요."
        )

    df = pd.read_csv(src, dtype=_DTYPE, encoding="utf-8")

    missing = {"amt", "cnt"} - set(df.columns)
    if missing:
        raise ValueError(f"필수 열이 없습니다: {sorted(missing)}")

    df["amt"] = pd.to_numeric(df["amt"], errors="raise").astype("float64")
    df["cnt"] = pd.to_numeric(df["cnt"], errors="raise").astype("float64")

    if validate:
        _validate_codes(df)

    df["group"] = df["GENDER_CD"].map(GROUP_MAP)
    if df["group"].isna().any():
        bad = sorted(df.loc[df["group"].isna(), "GENDER_CD"].unique())
        raise ValueError(f"GROUP_MAP에 없는 GENDER_CD: {bad}")

    df["period"] = np.where(
        df["STRD_YYMM"].isin(PERIOD_A), "A",
        np.where(df["STRD_YYMM"].isin(PERIOD_B), "B", ""),
    )
    if (df["period"] == "").any():
        bad = sorted(set(df["STRD_YYMM"]) - EXPECTED_MONTHS)
        raise ValueError(f"A/B 기간에 속하지 않는 관측월: {bad}")

    df["days"] = df["period"].map(DAYS).astype("int16")

    # 시군구명은 시도를 건너뛰면 유일하지 않다 ('중구'는 6개 시도에 존재).
    # 지역을 다룰 때는 이 열을 키로 쓴다.
    df["region_key"] = df["SIDO_NM"] + " " + df["CCG_NM"]

    if validate:
        _validate_corp_share(df)

    return df


def ambiguous_ccg(df: pd.DataFrame) -> dict[str, list[str]]:
    """여러 시도에 같은 이름이 있는 시군구를 반환한다.

    예: {'중구': ['서울특별시', '부산광역시', ...], '동구': [...]}
    """
    pairs = df[["SIDO_NM", "CCG_NM"]].drop_duplicates()
    grouped = pairs.groupby("CCG_NM")["SIDO_NM"].apply(list)
    return {k: v for k, v in grouped.items() if len(v) > 1}


def _validate_codes(df: pd.DataFrame) -> None:
    """코드값이 실측 사실과 일치하는지 검사한다."""
    g = set(df["GENDER_CD"].unique())
    if g != EXPECTED_GENDER_CD:
        raise ValueError(
            f"GENDER_CD가 예상과 다릅니다. 관측={sorted(g)}, 기대={sorted(EXPECTED_GENDER_CD)}\n"
            "법인은 소문자 'x'입니다. 대문자 'X'가 관측되면 원본이 바뀐 것입니다."
        )

    a = set(df["AGE_CD"].unique())
    if not a <= EXPECTED_AGE_CD:
        raise ValueError(f"예상 밖 AGE_CD: {sorted(a - EXPECTED_AGE_CD)}")

    m = set(df["STRD_YYMM"].unique())
    if m != EXPECTED_MONTHS:
        raise ValueError(f"관측월이 예상과 다릅니다. 관측={sorted(m)}")

    if len(df) != EXPECTED_ROWS:
        raise ValueError(f"행수가 예상과 다릅니다. 관측={len(df):,}, 기대={EXPECTED_ROWS:,}")


def _validate_corp_share(df: pd.DataFrame) -> None:
    """법인 금액 비중으로 대소문자 실수를 잡는다.

    이 검사가 이 모듈에서 가장 중요하다. 대문자 'X'로 필터하면
    법인 금액이 전부 사라지는데 합계는 그럴듯해 보여 발견이 늦다.
    """
    share = df.loc[df["group"] == "법인", "amt"].sum() / df["amt"].sum() * 100
    if not np.isclose(share, CORP_AMT_SHARE_PCT, atol=0.01):
        raise ValueError(
            f"법인 금액 비중이 {share:.2f}%입니다. 기대값 {CORP_AMT_SHARE_PCT}%.\n"
            "0%라면 대문자 'X'로 필터한 것입니다. GROUP_MAP을 확인하세요."
        )


# ---------------------------------------------------------------------------
# 집계
# ---------------------------------------------------------------------------

def aggregate(
    df: pd.DataFrame,
    region: str | list[str] | None = None,
    buz: str | list[str] | None = None,
    group_by: str | list[str] | None = None,
    sido: str | None = None,
    allow_mixed_buz: bool = False,
) -> pd.DataFrame:
    """지역·업종·집단별로 A/B 기간 지표를 집계한다.

    Parameters
    ----------
    df : load_card()의 반환값
    region : 시군구명. None이면 전국. 여러 시도에 같은 이름이 있으면
             sido를 함께 주어야 한다 (안 주면 ValueError)
    buz : 업종코드. **생략하면 ValueError.** 아래 Notes 참조
    group_by : 추가 분해 축. 예: 'group', 'AGE_CD', ['region_key', 'group']
    sido : 시도명. region이 여러 시도에 걸칠 때 특정하는 데 쓴다

    Returns
    -------
    열: amt_A, amt_B, cnt_A, cnt_B,
        daily_amt_A/B, daily_cnt_A/B, unit_A/B,
        daily_amt_chg_pct, daily_cnt_chg_pct, unit_chg_pct,
        share_B_pct (필터 범위 내 B기간 금액 비중)

    Raises
    ------
    ValueError : buz가 None일 때.

    Notes
    -----
    업종을 필수로 둔 이유: 일반한식 36,869원과 서양음식 11,023원은 건당
    결제금액이 3배 이상 차이 난다. 합산하면 업종 구성비 변화가 객단가
    변화로 나타나 진단이 틀린다. (docs/contract.md 6-2절)

    시도 확인이 필요한 이유: '중구'는 서울·부산·대구·인천·대전·울산 6곳에
    있다. sido 없이 region='중구'로 부르면 6개가 조용히 합산된다.
    """
    if buz is None:
        raise ValueError(
            "buz는 필수입니다. 업종을 생략하면 일반한식과 서양음식이 합산됩니다.\n"
            "두 업종은 건당 결제금액이 3배 이상 차이 나 합산값은 의미가 없습니다.\n"
            f"예: aggregate(df, buz='{BUZ_KOREAN}')  # 일반한식"
        )

    sub = df
    if sido is not None:
        sub = sub[sub["SIDO_NM"] == sido]
        if sub.empty:
            raise ValueError(f"해당 시도의 관측이 없습니다: {sido}")

    if region is not None:
        regions = [region] if isinstance(region, str) else list(region)
        if sido is None:
            amb = ambiguous_ccg(df)
            clash = {r: amb[r] for r in regions if r in amb}
            if clash:
                lines = "\n".join(f"  '{r}' -> {v}" for r, v in clash.items())
                raise ValueError(
                    "시군구명이 여러 시도에 있어 지역이 특정되지 않습니다.\n"
                    f"{lines}\n"
                    "sido를 함께 지정하세요. 예: aggregate(df, region='중구', "
                    "sido='서울특별시', buz='8001')"
                )
        sub = sub[sub["CCG_NM"].isin(regions)]
        if sub.empty:
            raise ValueError(f"해당 지역의 관측이 없습니다: {regions}")

    buzz = [buz] if isinstance(buz, str) else list(buz)
    if len(buzz) > 1 and not allow_mixed_buz and "TP_BUZ_NO" not in (
        [group_by] if isinstance(group_by, str) else list(group_by or [])
    ):
        raise ValueError(
            f"업종 {buzz}를 합산하려 합니다. 건당 결제금액이 크게 달라 합산값은 "
            "업종 구성비 변화를 객단가 변화로 잘못 보여줍니다.\n"
            "  - 업종별로 따로 부르거나\n"
            "  - group_by='TP_BUZ_NO'로 분해하거나\n"
            "  - 정말 합산이 필요하면 allow_mixed_buz=True를 명시하세요."
        )
    sub = sub[sub["TP_BUZ_NO"].isin(buzz)]
    if sub.empty:
        raise ValueError(f"해당 업종의 관측이 없습니다: {buzz}")

    if group_by is None:
        keys: list[str] = []
    elif isinstance(group_by, str):
        keys = [group_by]
    else:
        keys = list(group_by)

    unknown = [k for k in keys if k not in sub.columns]
    if unknown:
        raise ValueError(f"존재하지 않는 열: {unknown}")

    # CCG_NM 단독 그룹핑은 '중구' 6곳 등 22개 지역을 조용히 합친다.
    if "CCG_NM" in keys and "SIDO_NM" not in keys:
        raise ValueError(
            "group_by='CCG_NM'은 여러 시도의 동명 시군구를 합칩니다 "
            "(중구·동구 각 6곳 등, 시군구명 233개 vs 실제 지역 255개).\n"
            "  group_by='region_key'  또는  group_by=['SIDO_NM', 'CCG_NM'] 을 쓰세요."
        )

    if keys:
        wide = (
            sub.groupby(keys + ["period"], dropna=False)[["amt", "cnt"]]
            .sum()
            .unstack("period")
        )
    else:
        wide = (
            sub.groupby(["period"])[["amt", "cnt"]]
            .sum()
            .unstack("period")
            .to_frame()
            .T
        )

    # A 또는 B가 없는 조합은 0으로 채운다 (변화율은 NaN으로 드러난다)
    for col in [("amt", "A"), ("amt", "B"), ("cnt", "A"), ("cnt", "B")]:
        if col not in wide.columns:
            wide[col] = 0.0
    wide = wide.fillna(0.0)

    out = pd.DataFrame(index=wide.index)
    out["amt_A"] = wide[("amt", "A")]
    out["amt_B"] = wide[("amt", "B")]
    out["cnt_A"] = wide[("cnt", "A")]
    out["cnt_B"] = wide[("cnt", "B")]

    out["daily_amt_A"] = out["amt_A"] / DAYS_A
    out["daily_amt_B"] = out["amt_B"] / DAYS_B
    out["daily_cnt_A"] = out["cnt_A"] / DAYS_A
    out["daily_cnt_B"] = out["cnt_B"] / DAYS_B
    out["unit_A"] = _safe_div(out["amt_A"], out["cnt_A"])
    out["unit_B"] = _safe_div(out["amt_B"], out["cnt_B"])

    out["daily_amt_chg_pct"] = _pct_change(out["daily_amt_A"], out["daily_amt_B"])
    out["daily_cnt_chg_pct"] = _pct_change(out["daily_cnt_A"], out["daily_cnt_B"])
    out["unit_chg_pct"] = _pct_change(out["unit_A"], out["unit_B"])

    total_b = out["amt_B"].sum()
    out["share_B_pct"] = (out["amt_B"] / total_b * 100) if total_b else np.nan

    if keys:
        out = out.reset_index()
    else:
        out = out.reset_index(drop=True)
    return out


def _safe_div(num, den):
    num = np.asarray(num, dtype="float64")
    den = np.asarray(den, dtype="float64")
    return np.divide(num, den, out=np.full_like(num, np.nan), where=den != 0)


def _pct_change(a, b):
    """(B/A - 1) * 100. A가 0이면 NaN."""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    return np.divide(b, a, out=np.full_like(a, np.nan), where=a != 0) * 100 - 100


def national_baseline(df: pd.DataFrame, buz_list: list[str] | None = None) -> pd.DataFrame:
    """업종별 전국 기준선. 지역 수치를 읽을 때 반드시 병기한다."""
    rows = []
    for b in (buz_list or BUZ_TARGETS):
        r = aggregate(df, buz=b).iloc[0].to_dict()
        r["TP_BUZ_NO"] = b
        r["TP_BUZ_NM"] = df.loc[df["TP_BUZ_NO"] == b, "TP_BUZ_NM"].iloc[0]
        rows.append(r)
    res = pd.DataFrame(rows)
    front = ["TP_BUZ_NO", "TP_BUZ_NM"]
    return res[front + [c for c in res.columns if c not in front]]


# ---------------------------------------------------------------------------
# 자체 점검
# ---------------------------------------------------------------------------

# (지역, 업종, 라벨, 기대 금액변화, 기대 건수변화, 기대 건당변화)
CASE_CELLS = [
    ("미추홀구", BUZ_KOREAN, "미추홀구 일반한식", -2.05, 2.82, -4.74),
    ("이천시", BUZ_WESTERN, "이천시 서양음식", -1.80, 10.47, -11.11),
    ("미추홀구", BUZ_WESTERN, "미추홀구 서양음식", 4.92, 13.90, -7.89),
    ("이천시", BUZ_KOREAN, "이천시 일반한식", 3.71, 4.95, -1.18),
]

NATIONAL_EXPECTED = [
    (BUZ_KOREAN, "전국 일반한식", 8.13, 10.09, -1.78),
    (BUZ_WESTERN, "전국 서양음식", 7.88, 15.25, -6.39),
]


def self_check(df: pd.DataFrame | None = None) -> bool:
    """docs/contract.md 7절의 기준값과 대조한다.

    터미널에서:  python -m src.load
    """
    df = load_card() if df is None else df
    ok = True

    def chk(label: str, got: float, want: float, tol: float = 0.01) -> None:
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= good
        mark = "OK  " if good else "FAIL"
        print(f"  {mark}  {label:<30} {got:>9.2f}   (기대 {want:>7.2f})")

    print("[1] 법인 금액 비중")
    corp = df.loc[df["group"] == "법인", "amt"].sum() / df["amt"].sum() * 100
    chk("전국 법인 비중 %", corp, CORP_AMT_SHARE_PCT)

    print("\n[2] 4셀 (금액 / 건수 / 건당)")
    for reg, b, label, e_amt, e_cnt, e_unit in CASE_CELLS:
        r = aggregate(df, region=reg, buz=b).iloc[0]
        chk(f"{label} 금액", r["daily_amt_chg_pct"], e_amt)
        chk(f"{label} 건수", r["daily_cnt_chg_pct"], e_cnt)
        chk(f"{label} 건당", r["unit_chg_pct"], e_unit)

    print("\n[3] 전국 기준선")
    for b, label, e_amt, e_cnt, e_unit in NATIONAL_EXPECTED:
        r = aggregate(df, buz=b).iloc[0]
        chk(f"{label} 금액", r["daily_amt_chg_pct"], e_amt)
        chk(f"{label} 건수", r["daily_cnt_chg_pct"], e_cnt)
        chk(f"{label} 건당", r["unit_chg_pct"], e_unit)

    print("\n[4] 안전장치 — 조용히 틀린 값이 나오는 경로 차단")
    guards = [
        ("aggregate(buz 생략)", lambda: aggregate(df)),
        ("buz=['8001','8006'] 합산", lambda: aggregate(df, buz=BUZ_TARGETS)),
        ("group_by='CCG_NM'", lambda: aggregate(df, buz=BUZ_KOREAN, group_by="CCG_NM")),
        ("region='중구' (sido 없음)", lambda: aggregate(df, region="중구", buz=BUZ_KOREAN)),
    ]
    for label, fn in guards:
        try:
            fn()
        except ValueError:
            print(f"  OK    {label:<28} -> ValueError")
        else:
            ok = False
            print(f"  FAIL  {label:<28} 차단되지 않음")

    allowed = [
        ("buz 리스트 + group_by='TP_BUZ_NO'",
         lambda: aggregate(df, buz=BUZ_TARGETS, group_by="TP_BUZ_NO"), 2),
        ("group_by='region_key'",
         lambda: aggregate(df, buz=BUZ_KOREAN, group_by="region_key"), EXPECTED_REGION_PAIRS),
        ("region='중구' + sido",
         lambda: aggregate(df, region="중구", sido="서울특별시", buz=BUZ_KOREAN), 1),
    ]
    for label, fn, n in allowed:
        try:
            got = len(fn())
            good = got == n
            ok &= good
            print(f"  {'OK  ' if good else 'FAIL'}  {label:<28} -> {got}행 (기대 {n})")
        except ValueError as exc:
            ok = False
            print(f"  FAIL  {label:<28} 정당한 사용이 막힘: {exc}")

    print("\n[5] 관측 범위")
    n_pairs = df["region_key"].nunique()
    good = n_pairs == EXPECTED_REGION_PAIRS
    ok &= good
    print(f"  {'OK  ' if good else 'FAIL'}  (시도,시군구) 쌍 {n_pairs} (기대 {EXPECTED_REGION_PAIRS})")

    n_ccg = df["CCG_NM"].nunique()
    good = n_ccg == EXPECTED_CCG_NAMES
    ok &= good
    print(f"  {'OK  ' if good else 'FAIL'}  시군구명 {n_ccg} (기대 {EXPECTED_CCG_NAMES}, 중복 이름 존재)")

    by_month = df.groupby("STRD_YYMM")["region_key"].nunique()
    good = (by_month == EXPECTED_REGION_PAIRS).all()
    ok &= good
    print(f"  {'OK  ' if good else 'FAIL'}  월별 지역수 모두 {EXPECTED_REGION_PAIRS}")

    amb = ambiguous_ccg(df)
    print(f"  INFO  여러 시도에 걸친 시군구명 {len(amb)}개: {', '.join(sorted(amb))}")

    try:
        aggregate(df, region="중구", buz=BUZ_KOREAN)
    except ValueError:
        print("  OK    aggregate(region='중구', sido 없음) -> ValueError")
    else:
        ok = False
        print("  FAIL  모호한 시군구명이 조용히 합산됨")

    r = aggregate(df, region="중구", sido="서울특별시", buz=BUZ_KOREAN)
    print(f"  OK    sido 지정 시 정상 동작 (서울 중구 한식 금액변화 {r.iloc[0]['daily_amt_chg_pct']:+.2f}%)")

    print("\n[6] 분해 잔차 (log 금액 = log 건수 + log 건당)")
    worst = 0.0
    for reg, b, *_ in CASE_CELLS:
        r = aggregate(df, region=reg, buz=b).iloc[0]
        resid = (
            np.log(r["daily_amt_B"] / r["daily_amt_A"])
            - np.log(r["daily_cnt_B"] / r["daily_cnt_A"])
            - np.log(r["unit_B"] / r["unit_A"])
        )
        worst = max(worst, abs(resid))
    good = worst < 1e-10
    ok &= good
    print(f"  {'OK  ' if good else 'FAIL'}  최대 잔차 {worst:.2e} (기준 < 1e-10)")

    print("\n" + ("=== 전부 통과 ===" if ok else "=== 실패 항목 있음 ==="))
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if self_check() else 1)
