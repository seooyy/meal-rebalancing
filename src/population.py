"""인구 데이터 파싱과 지역명 매칭 — C 담당.

행정안전부 주민등록 연령별 인구현황(월간) 엑셀을 읽어
카드 데이터의 255개 (시도, 시군구) 키에 붙인다.

터미널 검증:
    python -m src.population
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

POP_XLSX = "data/202601_202606_연령별인구현황_월간.xlsx"
POP_SHEET = "연령별인구현황"
REGION_KEYS = "out/region_keys.csv"
ALIAS_CSV = "config/region_alias.csv"
OUT_CSV = "out/population_2026m1.csv"

DEFAULT_MONTH = "2026년01월"
# 기준월에 아직 인구가 잡히지 않는 지역을 메울 때 훑는 순서.
# 화성시 4개 구(만세·효행·병점·동탄)는 구 설치 시행이 늦어 2026년 1월 값이 0이고
# 2월부터 집계된다. 안분 추정 대신 관측된 첫 달 값을 쓰고 pop_asof에 출처를 남긴다.
FALLBACK_MONTHS = ["2026년02월", "2026년03월", "2026년04월", "2026년05월", "2026년06월"]

# 엑셀 '계' 블록의 열 순서. 월 블록 시작 열에서의 상대 위치다.
AGE_BANDS = [
    "0~9세", "10~19세", "20~29세", "30~39세", "40~49세",
    "50~59세", "60~69세", "70~79세", "80~89세", "90~99세", "100세 이상",
]
AGE_COLS = [f"age_{b}" for b in AGE_BANDS]


def _num(v) -> float:
    """'1,234' 또는 1234 -> 1234.0. 빈칸은 0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").strip()
    return float(s) if s and s != "-" else 0.0


def load_population_raw(path: str = POP_XLSX, month: str = DEFAULT_MONTH) -> pd.DataFrame:
    """엑셀의 한 월 '계' 블록을 행정기관 단위로 읽는다.

    반환 열: ADMIN_CD, ADMIN_NM, level, pop_total, age_* 11개
      level: 'sido'(시도) | 'sgg'(시군구) | 'branch'(출장소)
    """
    import openpyxl

    ws = openpyxl.load_workbook(path, data_only=True)[POP_SHEET]

    # 2행에서 월 블록의 시작 열을 찾는다.
    month_col = None
    for c in range(1, ws.max_column + 1):
        if str(ws.cell(2, c).value).strip() == month:
            month_col = c
            break
    if month_col is None:
        raise ValueError(f"{month} 블록을 찾지 못했다. 2행 헤더를 확인한다.")

    # 3행이 '계'인지, 4행 헤더가 기대 순서인지 확인한다. 열이 밀리면 조용히 틀린다.
    if str(ws.cell(3, month_col).value).strip() != "계":
        raise ValueError(f"{month} 블록의 첫 구분이 '계'가 아니다.")
    for i, band in enumerate(AGE_BANDS):
        got = str(ws.cell(4, month_col + 2 + i).value).strip()
        if got != band:
            raise ValueError(f"연령 열 순서가 다르다: {month_col + 2 + i}열 '{got}' != '{band}'")

    rows = []
    for r in range(5, ws.max_row + 1):
        code = ws.cell(r, 1).value
        name = ws.cell(r, 2).value
        if code is None or name is None:
            continue
        code = str(code).strip()
        name = re.sub(r"\s+", " ", str(name)).strip()
        rec = {
            "ADMIN_CD": code,
            "ADMIN_NM": name,
            "pop_total": _num(ws.cell(r, month_col).value),
        }
        for i, band in enumerate(AGE_BANDS):
            rec[f"age_{band}"] = _num(ws.cell(r, month_col + 2 + i).value)
        rows.append(rec)

    df = pd.DataFrame(rows)
    df["level"] = df["ADMIN_CD"].map(
        lambda c: "sido" if c[2:] == "00000000" else ("branch" if "출장소" in "" else "sgg")
    )
    df.loc[df["ADMIN_NM"].str.contains("출장소"), "level"] = "branch"
    return df


def match_regions(pop: pd.DataFrame, region_keys: pd.DataFrame,
                  alias: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """카드 255개 지역키에 인구 행을 붙인다.

    반환: (매칭된 DataFrame, 미매칭 지역키 DataFrame)

    시도명 접두어를 떼어 (SIDO_NM, CCG_NM)을 만든다. 통합시 상위 행
    ('경기도 수원시')과 출장소 행은 카드에 없으므로 자연히 버려진다.
    """
    sidos = sorted(pop.loc[pop["level"] == "sido", "ADMIN_NM"].tolist(), key=len, reverse=True)

    def split(nm: str):
        for s in sidos:
            if nm.startswith(s + " "):
                return s, nm[len(s) + 1:].strip()
        return None, None

    body = pop[pop["level"] == "sgg"].copy()
    body[["SIDO_NM", "CCG_NM"]] = body["ADMIN_NM"].apply(lambda n: pd.Series(split(n)))

    # 별칭: 카드 지역키 -> 인구 행정기관코드 (수작업 보정)
    if alias is not None and len(alias):
        by_code = pop.set_index("ADMIN_CD")
        for _, a in alias.iterrows():
            code = str(a["ADMIN_CD"]).strip()
            if code not in by_code.index:
                raise ValueError(f"별칭의 행정기관코드 {code}가 인구 파일에 없다.")
            row = by_code.loc[code].to_dict()
            row.update({"ADMIN_CD": code, "SIDO_NM": a["SIDO_NM"], "CCG_NM": a["CCG_NM"]})
            body = pd.concat([body, pd.DataFrame([row])], ignore_index=True)

    body = body.dropna(subset=["SIDO_NM"])
    dup = body.duplicated(subset=["SIDO_NM", "CCG_NM"], keep=False)
    if dup.any():
        raise ValueError(f"인구 쪽 지역키 중복: {body.loc[dup, 'ADMIN_NM'].tolist()}")

    merged = region_keys.merge(
        body[["SIDO_NM", "CCG_NM", "ADMIN_CD", "ADMIN_NM", "pop_total"] + AGE_COLS],
        on=["SIDO_NM", "CCG_NM"], how="left",
    )
    unmatched = merged[merged["ADMIN_CD"].isna()][["SIDO_NM", "CCG_NM"]]
    return merged, unmatched


def build(month: str = DEFAULT_MONTH, out_path: str = OUT_CSV) -> pd.DataFrame:
    """out/population_2026m1.csv 생성."""
    pop = load_population_raw(month=month)
    rk = pd.read_csv(REGION_KEYS, encoding="utf-8-sig", dtype=str)
    alias = None
    if Path(ALIAS_CSV).exists():
        alias = pd.read_csv(ALIAS_CSV, encoding="utf-8-sig", dtype=str)

    merged, unmatched = match_regions(pop, rk, alias)
    if len(unmatched):
        raise ValueError(f"미매칭 {len(unmatched)}건:\n{unmatched.to_string()}")

    out = merged.copy()
    out["pop_asof"] = month

    # 기준월 인구 0 -> 관측된 첫 달로 대체
    zero = out["pop_total"] <= 0
    for m in FALLBACK_MONTHS:
        if not zero.any():
            break
        alt = load_population_raw(month=m).set_index("ADMIN_CD")
        for i in out.index[zero]:
            code = out.at[i, "ADMIN_CD"]
            if code in alt.index and alt.at[code, "pop_total"] > 0:
                out.loc[i, ["pop_total"] + AGE_COLS] = alt.loc[code, ["pop_total"] + AGE_COLS].values
                out.at[i, "pop_asof"] = m
        zero = out["pop_total"] <= 0
    if zero.any():
        raise ValueError(f"6개월 내내 인구 0인 지역: {out.loc[zero, 'ADMIN_NM'].tolist()}")
    out["region_key"] = out["SIDO_NM"] + " " + out["CCG_NM"]

    # 연령 비율. 분모는 연령 합계(= 총인구)다.
    age_sum = out[AGE_COLS].sum(axis=1)
    if (age_sum - out["pop_total"]).abs().max() > 0.5:
        bad = out.loc[(age_sum - out["pop_total"]).abs() > 0.5, "region_key"].tolist()
        raise ValueError(f"연령 합계 != 총인구: {bad}")

    out["ratio_20_39"] = (out["age_20~29세"] + out["age_30~39세"]) / out["pop_total"] * 100
    out["ratio_60_plus"] = (
        out["age_60~69세"] + out["age_70~79세"] + out["age_80~89세"]
        + out["age_90~99세"] + out["age_100세 이상"]
    ) / out["pop_total"] * 100

    cols = (["region_key", "SIDO_NM", "CCG_NM", "ADMIN_CD", "ADMIN_NM", "pop_asof", "pop_total"]
            + AGE_COLS + ["ratio_20_39", "ratio_60_plus"])
    out = out[cols].sort_values("region_key").reset_index(drop=True)
    for c in AGE_COLS + ["pop_total"]:
        out[c] = out[c].astype("int64")
    out[["ratio_20_39", "ratio_60_plus"]] = out[["ratio_20_39", "ratio_60_plus"]].round(2)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out


def self_check() -> bool:
    """미매칭 0건과 기본 정합성을 확인한다."""
    ok = True

    def chk(label, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

    print("[1] 지역 매칭")
    pop = load_population_raw()
    rk = pd.read_csv(REGION_KEYS, encoding="utf-8-sig", dtype=str)
    alias = pd.read_csv(ALIAS_CSV, encoding="utf-8-sig", dtype=str)
    merged, unmatched = match_regions(pop, rk, alias)
    chk("카드 지역키 255", len(rk) == 255, f"실측 {len(rk)}")
    chk("미매칭 0건", len(unmatched) == 0, f"실측 {len(unmatched)}")
    chk("매칭 결과 255행", len(merged) == 255, f"실측 {len(merged)}")

    print("[2] 산출물")
    out = build()
    chk("population_2026m1.csv 255행", len(out) == 255)
    chk("총인구 결측 0", out["pop_total"].isna().sum() == 0)
    chk("총인구 0인 지역 없음", (out["pop_total"] > 0).all())
    late = out[out["pop_asof"] != DEFAULT_MONTH]
    chk("기준월 외 값 대체는 화성시 4구뿐",
        set(late["region_key"]) == {"경기도 화성시 동탄구", "경기도 화성시 만세구",
                                     "경기도 화성시 병점구", "경기도 화성시 효행구"},
        f"{len(late)}건 ({', '.join(late['pop_asof'].unique())})")

    print("[3] 눈으로 확인")
    total = out["pop_total"].sum()
    chk("전국 합계 5,100만~5,300만", 51e6 <= total <= 53e6, f"{total:,.0f}명")
    for key in ["인천광역시 미추홀구", "경기도 이천시", "세종특별자치시 세종특별자치시"]:
        r = out[out["region_key"] == key]
        chk(key, len(r) == 1,
            f"{r['pop_total'].iloc[0]:,}명 / 20~30대 {r['ratio_20_39'].iloc[0]}% / 60대+ {r['ratio_60_plus'].iloc[0]}%")

    print("\n=== " + ("전부 통과" if ok else "실패 있음") + " ===")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_check() else 1)
