"""지역 x 업종 x 집단 진단과 실행 후보 생성.

`src.classify`가 "이 셀이 어떤 상태인가"를 답하고, 이 모듈이 "그래서 무엇을
해볼 수 있는가"를 답한다. 둘을 나눈 이유는 후보 생성이 판정보다 훨씬 보수적
이어야 하기 때문이다. **판정은 모든 셀에 남기고, 후보만 게이트로 거른다.**

게이트 (config/rules.yaml)

  0. 우선순위   : 셀 우선순위가 '중간' 미만이면 집단 규칙을 보지 않고 비운다
  1. 규모       : 집단의 B기간 금액 비중 5% 미만이면 제외
  2. 전국 초과분 : 전국과 같은 방향·비슷한 크기면 '전국 공통 흐름'으로 표기
  3. 관측량     : min(A건수, B건수) < 1,000이면 수치를 숨기고 후보를 만들지 않는다

게이트가 없으면 4셀 전부에서 "법인 결제 +7~22% 증가 -> 예약 구성 도입"이
1순위 후보로 뜬다. 전국 법인이 +46.41%(한식) / +34.75%(서양음식)라 지역
법인은 오히려 전국보다 **느리게** 늘었는데도 그렇다.

계약: config/contract.md, plan/02_지역_소비집단_진단.md
터미널: python -m src.diagnose
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .classify import classify_row
from .load import (
    AGE_FOR_COMPARISON,
    BUZ_TARGETS,
    DAYS_B,
    aggregate,
    load_card,
)

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "config" / "rules.yaml"
OUT_DIR = ROOT / "out"

# 우선순위 게이트는 대소 비교가 필요하다. 문자열 비교로는 '중간' < '높음'이
# 성립하지 않으므로 순서를 명시한다.
PRIORITY_ORDER = {"없음": 0, "낮음": 1, "중간": 2, "높음": 3}

GROUP_ORDER = {"전체": 0, "일반개인": 1, "외국인": 2, "법인": 3}

JUDGE_COLS = ["방향", "원인", "라벨", "우선순위", "설명"]

METRIC_COLS = [
    "amt_A", "amt_B", "cnt_A", "cnt_B",
    "daily_amt_A", "daily_amt_B", "daily_cnt_A", "daily_cnt_B",
    "unit_A", "unit_B",
    "daily_amt_chg_pct", "daily_cnt_chg_pct", "unit_chg_pct",
]


# ---------------------------------------------------------------------------
# 규칙 파일
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def load_rules(path: str | Path = RULES_PATH) -> dict:
    """config/rules.yaml을 읽어 검증한 뒤 돌려준다.

    게이트 값이 빠져 있으면 여기서 막는다. 키가 없으면 게이트가 조용히
    꺼지고 후보가 쏟아지는데, 숫자는 그럴듯해 보여 발견이 늦다.
    """
    with open(path, encoding="utf-8") as f:
        rules = yaml.safe_load(f)

    gates = rules.get("gates")
    if not gates:
        raise ValueError(f"{path}에 gates가 없습니다.")
    if gates.get("min_priority") not in PRIORITY_ORDER:
        raise ValueError(
            f"gates.min_priority가 '{gates.get('min_priority')}'입니다. "
            f"{list(PRIORITY_ORDER)} 중 하나여야 합니다."
        )
    for key in ("min_share_pct", "national_excess_band_pct", "min_count"):
        if key not in gates:
            raise ValueError(f"gates.{key}가 없습니다. 게이트가 조용히 꺼집니다.")

    causes = {r["원인"] for r in rules["cell_rules"]}
    missing = {"객단가", "방문", "동반", "전국 수준"} - causes
    if missing:
        raise ValueError(f"cell_rules에 빠진 원인: {sorted(missing)}")
    return rules


# ---------------------------------------------------------------------------
# 전국 기준선
# ---------------------------------------------------------------------------

def national_by_buz(df: pd.DataFrame) -> dict[str, pd.Series]:
    """업종별 전국 기준선 한 행씩."""
    return {b: aggregate(df, buz=b).iloc[0] for b in BUZ_TARGETS}


def national_by_group(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """업종별 전국 집단 기준선. 집단 후보의 초과분 게이트가 이걸 쓴다."""
    return {
        b: aggregate(df, buz=b, group_by="group").set_index("group")
        for b in BUZ_TARGETS
    }


def _pct(num, den):
    """num / den * 100. 분모가 0이면 NaN."""
    num = np.asarray(num, dtype="float64")
    den = np.broadcast_to(np.asarray(den, dtype="float64"), num.shape)
    return np.divide(num, den, out=np.full_like(num, np.nan), where=den != 0) * 100


# ---------------------------------------------------------------------------
# 셀 테이블 — 지역 x 업종
# ---------------------------------------------------------------------------

def region_cells(df: pd.DataFrame, buz_list: list[str] | None = None) -> pd.DataFrame:
    """255개 지역 x 업종 = 510칸. 지표 + 전국 대비 초과분 + 판정.

    `후보생성` 열이 우선순위·관측량 게이트를 통과했는지를 담는다. 화면은
    이 열만 보고 후보 영역을 그릴지 정하면 된다.
    """
    rules = load_rules()
    gates = rules["gates"]
    nat = national_by_buz(df)

    frames = []
    for buz in buz_list or BUZ_TARGETS:
        r = aggregate(df, buz=buz, group_by="region_key")
        r.insert(1, "buz", buz)

        base = nat[buz]
        r["cnt_excess_pp"] = r["daily_cnt_chg_pct"] - base["daily_cnt_chg_pct"]
        r["unit_excess_pp"] = r["unit_chg_pct"] - base["unit_chg_pct"]
        r["amt_excess_pp"] = r["daily_amt_chg_pct"] - base["daily_amt_chg_pct"]

        judged = [classify_row(row, base) for _, row in r.iterrows()]
        for col in JUDGE_COLS:
            r[col] = [getattr(d, col) for d in judged]

        r["n_min"] = r[["cnt_A", "cnt_B"]].min(axis=1)
        r["관측량부족"] = r["n_min"] < gates["min_count"]

        # A기간 관측이 없으면 변화율이 NaN이다. classify는 NaN을 밴드와
        # 비교해 전부 False를 받고 조용히 '정체 / 전국 수준'으로 판정한다.
        # 관측이 없는 것과 변화가 없는 것은 다르다. 화면에 거짓 라벨이
        # 나가기 전에 여기서 갈아끼운다.
        blank = r[["daily_amt_chg_pct", "daily_cnt_chg_pct", "unit_chg_pct"]].isna().any(axis=1)
        if blank.any():
            r.loc[blank, "방향"] = "판정 불가"
            r.loc[blank, "원인"] = "판정 불가"
            r.loc[blank, "라벨"] = "관측량 부족"
            r.loc[blank, "우선순위"] = "없음"
            r.loc[blank, "설명"] = "A기간 관측이 없어 변화를 계산할 수 없습니다."
            r.loc[blank, "관측량부족"] = True
        r["후보생성"] = (
            r["우선순위"].map(PRIORITY_ORDER)
            >= PRIORITY_ORDER[gates["min_priority"]]
        ) & ~r["관측량부족"]
        frames.append(r)

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 집단 테이블 — 지역 x 업종 x 집단
# ---------------------------------------------------------------------------

def group_cells(df: pd.DataFrame, buz_list: list[str] | None = None) -> pd.DataFrame:
    """지역 x 업종 x 집단(일반개인/외국인/법인).

    `share_B_pct`는 **셀 안에서의 비중**으로 다시 계산한다. aggregate()가
    돌려주는 share_B_pct는 필터 전체(=전국) 대비라 규모 게이트에 그대로
    쓰면 모든 집단이 5% 미만으로 떨어져 후보가 전멸한다.
    """
    rules = load_rules()
    min_count = rules["gates"]["min_count"]
    nat_g = national_by_group(df)

    frames = []
    for buz in buz_list or BUZ_TARGETS:
        r = aggregate(df, buz=buz, group_by=["region_key", "group"])
        r.insert(2, "buz", buz)

        base = nat_g[buz]
        r["cnt_excess_pp"] = r["daily_cnt_chg_pct"] - r["group"].map(base["daily_cnt_chg_pct"])
        r["unit_excess_pp"] = r["unit_chg_pct"] - r["group"].map(base["unit_chg_pct"])
        r["amt_excess_pp"] = r["daily_amt_chg_pct"] - r["group"].map(base["daily_amt_chg_pct"])

        cell_amt_b = r.groupby("region_key")["amt_B"].transform("sum")
        cell_daily_amt_a = r.groupby("region_key")["daily_amt_A"].transform("sum")
        r["share_B_pct"] = _pct(r["amt_B"], cell_amt_b)
        # 금액 기여도 = (집단 B금액 - 집단 A일평균x91) / (전체 A일평균x91)
        r["금액기여도_pct"] = _pct(
            r["amt_B"] - r["daily_amt_A"] * DAYS_B, cell_daily_amt_a * DAYS_B
        )

        r["n_min"] = r[["cnt_A", "cnt_B"]].min(axis=1)
        r["관측량부족"] = r["n_min"] < min_count
        frames.append(r)

    return pd.concat(frames, ignore_index=True)


def age_cells(df: pd.DataFrame, buz_list: list[str] | None = None) -> pd.DataFrame:
    """지역 x 업종 x 연령(코드 2~6).

    코드 `1`(미상)과 `x`(법인)는 제외하고, 제외 비중을 `제외비중_pct` 열에
    담아 같은 행에서 읽히게 한다. 화면이 이 숫자를 반드시 표시한다.
    """
    rules = load_rules()
    min_count = rules["gates"]["min_count"]

    frames = []
    for buz in buz_list or BUZ_TARGETS:
        full = aggregate(df, buz=buz, group_by=["region_key", "AGE_CD"])
        full.insert(2, "buz", buz)

        cell_amt_b = full.groupby("region_key")["amt_B"].transform("sum")
        full["share_B_pct"] = _pct(full["amt_B"], cell_amt_b)

        kept = full["AGE_CD"].isin(AGE_FOR_COMPARISON)
        excluded = (
            full[~kept]
            .groupby("region_key")["share_B_pct"]
            .sum()
            .rename("제외비중_pct")
            .reset_index()
        )

        base = aggregate(df, buz=buz, group_by="AGE_CD").set_index("AGE_CD")
        r = full[kept].copy()
        r["cnt_excess_pp"] = r["daily_cnt_chg_pct"] - r["AGE_CD"].map(base["daily_cnt_chg_pct"])
        r["unit_excess_pp"] = r["unit_chg_pct"] - r["AGE_CD"].map(base["unit_chg_pct"])
        r["amt_excess_pp"] = r["daily_amt_chg_pct"] - r["AGE_CD"].map(base["daily_amt_chg_pct"])
        r = r.merge(excluded, on="region_key", how="left")
        r["제외비중_pct"] = r["제외비중_pct"].fillna(0.0)

        r["n_min"] = r[["cnt_A", "cnt_B"]].min(axis=1)
        r["관측량부족"] = r["n_min"] < min_count
        frames.append(r)

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# 게이트와 실행 후보
# ---------------------------------------------------------------------------

def _cell_rule(cause: str, rules: dict) -> dict | None:
    """셀 원인에 대응하는 규칙. 후보가 빈 규칙('전국 수준')은 None."""
    for rule in rules["cell_rules"]:
        if rule["원인"] == cause:
            return rule if rule["후보"] else None
    return None


def _group_candidates(
    groups: pd.DataFrame, rules: dict
) -> tuple[list[dict], list[str]]:
    """집단 규칙 + 규모·초과분·관측량 게이트.

    통과한 후보와 **탈락 사유**를 함께 돌려준다. 사유를 남기지 않으면
    후보가 비었을 때 게이트가 막은 것인지 계산이 빠진 것인지 알 수 없다.
    """
    gates = rules["gates"]
    passed: list[dict] = []
    blocked: list[str] = []

    indexed = groups.set_index("group")
    for rule in rules["group_rules"]:
        name = rule["group"]
        if name not in indexed.index:
            continue
        row = indexed.loc[name]

        amt = float(row["daily_amt_chg_pct"])
        if amt <= rule["amt_min_pct"]:
            continue  # 규칙 자체가 걸리지 않는다. 게이트 사유로 남길 일이 아니다.

        share = float(row["share_B_pct"])
        excess = float(row["amt_excess_pp"])

        if bool(row["관측량부족"]):
            blocked.append(
                f"{name}: 관측량 게이트 — 최소 {int(row['n_min']):,}건 "
                f"(< {gates['min_count']:,}건)"
            )
            continue
        if share < gates["min_share_pct"]:
            blocked.append(
                f"{name}: 규모 게이트 — B기간 금액 비중 {share:.2f}% "
                f"(< {gates['min_share_pct']}%)"
            )
            continue
        if excess <= gates["national_excess_band_pct"]:
            blocked.append(
                f"{name}: 전국 공통 흐름 — 지역 {amt:+.2f}%이지만 "
                f"전국 대비 {excess:+.2f}%p"
            )
            continue

        passed.append(
            {
                "규칙": rule["id"],
                "대상": name,
                "확인": rule["확인"],
                "후보": list(rule["후보"]),
                "B기간_비중_pct": round(share, 2),
                "전국_대비_초과분_pp": round(excess, 2),
                "금액_변화_pct": round(amt, 2),
            }
        )
    return passed, blocked


def _reference_line(diag, display: dict) -> str:
    """우선순위 '낮음'에서 후보 대신 내보내는 '참고' 한 줄."""
    if diag.원인 == "객단가":
        지표, 값 = "1건당 결제금액", abs(diag.건당_초과분)
    elif diag.원인 == "방문":
        지표, 값 = "결제 건수 증가", abs(diag.건수_초과분)
    else:
        지표, 값 = "결제 건수 증가", abs(min(diag.건수_초과분, diag.건당_초과분))
    return display["reference_line"].format(지표=지표, 값=f"{값:.1f}")


def diagnose(
    df: pd.DataFrame,
    region: str,
    buz: str,
    sido: str | None = None,
    rules: dict | None = None,
) -> dict:
    """화면 1이 쓰는 단일 셀 진단.

    Parameters
    ----------
    rules : config/rules.yaml 대신 쓸 규칙 사전. 게이트를 끄거나 임계값을
            바꿨을 때 후보가 어떻게 달라지는지 확인하는 용도다
            (tests/test_diagnose.py의 게이트 민감도 테스트).

    Returns
    -------
    dict — 지표 / 판정 / 실행후보 / 참고 / 게이트 / 표시 문구.
    실행 후보가 비어 있을 때 **왜 비었는지**가 `게이트`에 남는다.
    """
    rules = load_rules() if rules is None else rules
    gates = rules["gates"]
    display = rules["display"]

    cell = aggregate(df, region=region, buz=buz, sido=sido).iloc[0]
    base = aggregate(df, buz=buz).iloc[0]
    diag = classify_row(cell, base)

    n_min = float(min(cell["cnt_A"], cell["cnt_B"]))
    result = {
        "지역": region if sido is None else f"{sido} {region}",
        "업종": buz,
        "지표": {
            "일평균금액_변화_pct": round(float(cell["daily_amt_chg_pct"]), 2),
            "일평균건수_변화_pct": round(float(cell["daily_cnt_chg_pct"]), 2),
            "건당금액_변화_pct": round(float(cell["unit_chg_pct"]), 2),
            "금액_초과분_pp": round(
                float(cell["daily_amt_chg_pct"] - base["daily_amt_chg_pct"]), 2
            ),
            "건수_초과분_pp": diag.건수_초과분,
            "건당_초과분_pp": diag.건당_초과분,
            "관측건수_최소": int(n_min),
        },
        "판정": {
            "방향": diag.방향,
            "원인": diag.원인,
            "라벨": diag.라벨,
            "우선순위": diag.우선순위,
            "설명": diag.설명,
        },
        "실행후보": [],
        "참고": None,
        "게이트": [],
        "표시": {"footer": display["footer"], "주석": display["seasonality"]},
    }

    # --- 게이트 3: 관측량 ---------------------------------------------------
    blank = pd.isna(
        [cell["daily_amt_chg_pct"], cell["daily_cnt_chg_pct"], cell["unit_chg_pct"]]
    ).any()
    if blank or n_min < gates["min_count"]:
        result["관측량부족"] = True
        result["표시"]["대체문구"] = display["insufficient"]
        if blank:
            # 관측이 없는 것과 변화가 없는 것은 다르다. classify가 NaN을
            # 밴드와 비교해 내놓은 '정체 / 전국 수준'을 그대로 내보내면
            # 화면에 거짓 판정이 뜬다.
            result["판정"] = {
                "방향": "판정 불가", "원인": "판정 불가", "라벨": "관측량 부족",
                "우선순위": "없음",
                "설명": "A기간 관측이 없어 변화를 계산할 수 없습니다.",
            }
            result["게이트"].append("관측량 게이트: A기간 관측이 없어 변화율을 낼 수 없다.")
        else:
            result["게이트"].append(
                f"관측량 게이트: 최소 {int(n_min):,}건 (< {gates['min_count']:,}건). "
                "수치를 표시하지 않는다."
            )
        return result
    result["관측량부족"] = False

    # --- 게이트 0: 우선순위 -------------------------------------------------
    if PRIORITY_ORDER[diag.우선순위] < PRIORITY_ORDER[gates["min_priority"]]:
        result["게이트"].append(
            f"우선순위 게이트: '{diag.우선순위}' < '{gates['min_priority']}' — "
            "집단 규칙을 보지 않고 후보를 비운다."
        )
        if diag.우선순위 == "낮음":
            result["참고"] = _reference_line(diag, display)
        return result

    # --- 셀 원인 기반 후보 --------------------------------------------------
    rule = _cell_rule(diag.원인, rules)
    if rule is None:
        result["게이트"].append(
            f"전국 초과분 게이트: 원인이 '{diag.원인}' — 전국 공통 흐름으로 표기."
        )
    else:
        result["실행후보"].append(
            {
                "규칙": rule["id"],
                "대상": "전체",
                "확인": rule["확인"],
                "후보": list(rule["후보"]),
                "B기간_비중_pct": 100.0,
                "전국_대비_초과분_pp": (
                    diag.건당_초과분 if diag.원인 == "객단가" else diag.건수_초과분
                ),
                "비고": rule.get("비고"),
            }
        )

    # --- 게이트 1·2: 집단 후보 ---------------------------------------------
    groups = aggregate(df, region=region, buz=buz, sido=sido, group_by="group")
    nat_g = aggregate(df, buz=buz, group_by="group").set_index("group")
    groups["amt_excess_pp"] = groups["daily_amt_chg_pct"] - groups["group"].map(
        nat_g["daily_amt_chg_pct"]
    )
    groups["share_B_pct"] = _pct(groups["amt_B"], groups["amt_B"].sum())
    groups["n_min"] = groups[["cnt_A", "cnt_B"]].min(axis=1)
    groups["관측량부족"] = groups["n_min"] < gates["min_count"]

    passed, blocked = _group_candidates(groups, rules)
    result["실행후보"].extend(passed)
    result["게이트"].extend(blocked)
    return result


# ---------------------------------------------------------------------------
# 산출물 — C에게 넘기는 CSV
# ---------------------------------------------------------------------------

def build_region_group_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """out/region_group_metrics.csv — 255지역 x 2업종 x (전체 + 3집단).

    전체 행을 `group='전체'`로 함께 넣는다. C가 셀 판정과 집단 지표를 한
    파일에서 읽어야 화면에서 둘을 맞물려 보여줄 수 있다. 판정 열은 셀 단위
    값이라 같은 셀의 집단 행에 그대로 반복된다.
    """
    cells = region_cells(df)
    groups = group_cells(df)

    total = cells.copy()
    total["group"] = "전체"
    total["share_B_pct"] = 100.0
    # 전체의 금액 기여도는 정의상 일평균 금액 변화율과 같다
    # (amt_B - daily_amt_A*91) / (daily_amt_A*91) = daily_amt_B/daily_amt_A - 1
    total["금액기여도_pct"] = _pct(
        total["amt_B"] - total["daily_amt_A"] * DAYS_B,
        total["daily_amt_A"] * DAYS_B,
    )

    groups = groups.merge(
        cells[["region_key", "buz", "후보생성"] + JUDGE_COLS],
        on=["region_key", "buz"],
        how="left",
    )

    cols = (
        ["region_key", "buz", "group"]
        + METRIC_COLS
        + ["share_B_pct", "금액기여도_pct",
           "cnt_excess_pp", "unit_excess_pp", "amt_excess_pp",
           "n_min", "관측량부족", "후보생성"]
        + JUDGE_COLS
    )
    out = pd.concat([total[cols], groups[cols]], ignore_index=True)
    out["_g"] = out["group"].map(GROUP_ORDER)
    out = (
        out.sort_values(["buz", "region_key", "_g"])
        .drop(columns="_g")
        .reset_index(drop=True)
    )
    return out


def build_region_age_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """out/region_age_metrics.csv — 255지역 x 2업종 x 연령 2~6."""
    a = age_cells(df)
    cols = (
        ["region_key", "buz", "AGE_CD"]
        + METRIC_COLS
        + ["share_B_pct", "제외비중_pct",
           "cnt_excess_pp", "unit_excess_pp", "amt_excess_pp",
           "n_min", "관측량부족"]
    )
    return (
        a[cols]
        .sort_values(["buz", "region_key", "AGE_CD"])
        .reset_index(drop=True)
    )


# ---------------------------------------------------------------------------
# 자체 점검 — python -m src.diagnose
# ---------------------------------------------------------------------------

CASE_CELLS = [
    ("미추홀구", "인천광역시", "8001", "동반 부진", "높음", True),
    ("이천시", "경기도", "8006", "객단가 문제", "높음", True),
    ("미추홀구", "인천광역시", "8006", "전국 수준 성장", "없음", False),
    ("이천시", "경기도", "8001", "성장 중 방문 약세", "낮음", False),
]


def self_check(df: pd.DataFrame | None = None) -> bool:
    """4셀 판정·게이트·산출물 정합성을 한 번에 확인한다."""
    df = load_card() if df is None else df
    ok = True

    print("4셀 판정과 실행 후보")
    for region, sido, buz, label, priority, has_cand in CASE_CELLS:
        r = diagnose(df, region=region, buz=buz, sido=sido)
        got_label = r["판정"]["라벨"]
        got_pri = r["판정"]["우선순위"]
        got_cand = len(r["실행후보"]) > 0
        hit = (got_label, got_pri, got_cand) == (label, priority, has_cand)
        ok &= hit
        mark = "OK " if hit else "실패"
        print(
            f"  [{mark}] {sido} {region} {buz}: {got_label} / {got_pri} / "
            f"후보 {len(r['실행후보'])}건"
        )
        if not hit:
            print(f"         기대: {label} / {priority} / 후보 있음={has_cand}")
        for line in r["게이트"]:
            print(f"         게이트 | {line}")
        if r["참고"]:
            print(f"         참고   | {r['참고']}")

    cells = region_cells(df)
    print("\n우선순위 분포")
    print(
        cells.pivot_table(
            index="buz", columns="우선순위", values="region_key",
            aggfunc="count", fill_value=0,
        )
    )
    n_cand = cells.groupby("buz")["후보생성"].sum().to_dict()
    print(f"후보 생성 지역: {n_cand}")

    rgm = build_region_group_metrics(df)
    part = rgm[rgm["group"] != "전체"].groupby(["region_key", "buz"])["amt_B"].sum()
    whole = rgm[rgm["group"] == "전체"].set_index(["region_key", "buz"])["amt_B"]
    gap = float((part - whole).abs().max())
    hit = gap < 1e-6
    ok &= hit
    print(f"\n[{'OK ' if hit else '실패'}] 집단 합 = 전체: 최대 차이 {gap:.6f}원")

    print("\n전부 통과" if ok else "\n실패한 항목이 있다")
    return bool(ok)


def _write(frame: pd.DataFrame, name: str) -> None:
    OUT_DIR.mkdir(exist_ok=True)
    frame.to_csv(OUT_DIR / name, index=False, encoding="utf-8-sig")
    print(f"  {name:<28} {len(frame):>7,}행  {len(frame.columns):>2}열")


def main() -> int:
    df = load_card()
    print("산출물 생성")
    _write(build_region_group_metrics(df), "region_group_metrics.csv")
    _write(build_region_age_metrics(df), "region_age_metrics.csv")
    print()
    return 0 if self_check(df) else 1


if __name__ == "__main__":
    raise SystemExit(main())
