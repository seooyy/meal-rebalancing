"""외식 소비자물가지수 — C 담당 (단계 6-A).

통계청 품목별 소비자물가지수에서 업종별 외식 물가 변화율을 뽑는다.
화면 1의 명목 건당금액 변화에서 이 값을 빼 "실질(참고)"을 보여주기 위한 것이다.

    실질(참고) = 명목 건당금액 변화 − 해당 업종 외식 물가 변화

**주 지표가 아니라 해석 보조다.** 단순 차감이며 정밀 디플레이션이 아니다.

기간은 카드 데이터와 맞춘다. A = 2026.01~03 평균, B = 2026.04~06 평균.
지역은 전국이다. 시도별을 받아도 시군구를 대표하지 못하므로 "외식 물가가 오르는
국면인가"라는 방향 판단에만 쓴다 (docs/plan/06 "지역을 전국으로 결정한 이유").

⚠️ docs/plan/06의 물가 표와 값이 다르다. 그 표는 폐기된 이전 파일(2026.03~08)로
계산된 것으로 보이며, 이 저장소의 파일로는 어떤 기간 정의로도 재현되지 않는다.
특히 피자는 6개월 내내 지수가 119.68로 고정(+0.00%)인데 docs/plan/06은 +1.40%로 적는다.
self_check()가 그 차이를 경고로 출력한다. 팀 합의 전까지 docs/plan/06은 고치지 않는다.

터미널 검증:
    python -m src.cpi
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

CPI_XLSX = "data/품목별_소비자물가지수_품목성질별_2020100__20260916133542.xlsx"
CPI_SHEET = "데이터"
OUT_CSV = "data/out/cpi_dineout.csv"

BUZ_KOREAN, BUZ_WESTERN = "8001", "8006"

MONTHS_A = ["2026.01", "2026.02", "2026.03"]
MONTHS_B = ["2026.04", "2026.05", "2026.06"]
MONTHS = MONTHS_A + MONTHS_B

# 품목 선택은 docs/plan/06의 팀 결정을 그대로 유지한다. 값만 원본에서 다시 계산한다.
ITEMS = {
    BUZ_KOREAN: ("일반한식", ["김치찌개백반", "비빔밥", "냉면", "삼겹살(외식)"]),
    BUZ_WESTERN: ("서양음식", ["스파게티", "피자", "햄버거", "돈가스", "치킨"]),
}
REFERENCE_ITEM = "외식"  # 대분류. 업종 적용에는 쓰지 않고 참고로만 담는다

# docs/plan/06 기재값. 재현되지 않는다는 사실을 드러내기 위해서만 들고 있다.
PLAN06_CLAIMED = {BUZ_KOREAN: 0.88, BUZ_WESTERN: 0.97}


def load_cpi_raw(path: str = CPI_XLSX) -> pd.DataFrame:
    """CPI 시트를 읽고 품목명을 정규화한다.

    '품목별' 열은 계층을 전각 공백(\\u3000)으로 들여쓰기해 표현한다.
    그대로 두면 '　　　　　　쌀' 처럼 되어 이름으로 찾을 수 없다.
    """
    df = pd.read_excel(path, sheet_name=CPI_SHEET)
    missing = [m for m in MONTHS if m not in df.columns]
    if missing:
        raise ValueError(
            f"CPI 파일에 {missing} 월이 없습니다. 카드 데이터(2026.01~06)와 "
            "기간이 어긋나면 실질 계산이 성립하지 않습니다."
        )
    df = df.copy()
    df["품목"] = df["품목별"].astype(str).str.replace(r"[\s　]", "", regex=True)
    return df


def _item_row(df: pd.DataFrame, name: str) -> pd.Series:
    hit = df[df["품목"] == name]
    if not len(hit):
        raise ValueError(f"CPI 파일에 품목이 없습니다: {name}")
    return hit.iloc[0]


def _change(row: pd.Series) -> tuple[float, float, float]:
    """(A기간 평균지수, B기간 평균지수, 변화율 %)."""
    a = float(row[MONTHS_A].mean())
    b = float(row[MONTHS_B].mean())
    return a, b, (b / a - 1) * 100


def build(out_path: str = OUT_CSV, path: str = CPI_XLSX) -> pd.DataFrame:
    """업종별 외식 물가 변화율을 계산해 CSV로 저장한다.

    업종 변화율은 품목별 변화율의 **단순 평균**이다. 소비 비중 가중평균이
    아니며, 이 사실을 화면에 표기한다.
    """
    df = load_cpi_raw(path)
    rows = []

    for buz, (buz_nm, items) in ITEMS.items():
        for name in items:
            a, b, chg = _change(_item_row(df, name))
            rows.append({"buz": buz, "buz_nm": buz_nm, "수준": "품목", "품목": name,
                         "idx_A": round(a, 4), "idx_B": round(b, 4),
                         "chg_pct": round(chg, 4)})
        chgs = [r["chg_pct"] for r in rows if r["buz"] == buz and r["수준"] == "품목"]
        rows.append({"buz": buz, "buz_nm": buz_nm, "수준": "업종", "품목": f"{buz_nm} 단순평균",
                     "idx_A": None, "idx_B": None,
                     "chg_pct": round(sum(chgs) / len(chgs), 4)})

    a, b, chg = _change(_item_row(df, REFERENCE_ITEM))
    # buz를 빈칸으로 두면 열 전체가 float으로 읽혀 '8001'이 '8001.0'이 된다.
    # 업종 코드는 끝까지 문자열로 유지한다 (계약 6-1절과 같은 함정이다).
    rows.append({"buz": "-", "buz_nm": "(참고)", "수준": "참고", "품목": REFERENCE_ITEM,
                 "idx_A": round(a, 4), "idx_B": round(b, 4), "chg_pct": round(chg, 4)})

    out = pd.DataFrame(rows)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out


def buz_change(buz: str, path: str = OUT_CSV) -> float | None:
    """업종 단위 물가 변화율 %. 산출물이 없으면 None."""
    p = Path(path)
    if not p.exists():
        return None
    df = pd.read_csv(p, encoding="utf-8-sig", dtype={"buz": str})
    hit = df[(df["buz"] == str(buz)) & (df["수준"] == "업종")]
    return float(hit.iloc[0]["chg_pct"]) if len(hit) else None


def self_check() -> bool:
    """원본 정합성을 확인하고 docs/plan/06과의 차이를 드러낸다."""
    ok = True

    def chk(label: str, cond: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

    print("[1] 원본 파일")
    df = load_cpi_raw()
    chk("2026.01~06 6개월 존재", all(m in df.columns for m in MONTHS))
    names = set(df["품목"])
    want = [n for _, items in ITEMS.values() for n in items] + [REFERENCE_ITEM]
    miss = [n for n in want if n not in names]
    chk(f"품목 {len(want)}개 모두 존재", not miss, f"누락 {miss}" if miss else "")

    print("\n[2] 지수 결측")
    sub = df[df["품목"].isin(want)]
    n_na = int(sub[MONTHS].isna().sum().sum())
    chk("결측 0건", n_na == 0, f"실측 {n_na}")

    print("\n[3] 업종별 변화율 (A=2026.01~03 평균 → B=2026.04~06 평균)")
    out = build()
    for buz, (buz_nm, _) in ITEMS.items():
        v = float(out[(out.buz == buz) & (out["수준"] == "업종")].iloc[0]["chg_pct"])
        items = out[(out.buz == buz) & (out["수준"] == "품목")]
        detail = ", ".join(f"{t.품목} {t.chg_pct:+.2f}%" for t in items.itertuples())
        print(f"  INFO  {buz_nm}({buz}) {v:+.4f}%   [{detail}]")
        chk(f"{buz_nm} 변화율이 유한값", pd.notna(v))

    print("\n[4] docs/plan/06 기재값과의 차이 — 경고이며 실패가 아니다")
    for buz, claimed in PLAN06_CLAIMED.items():
        got = float(out[(out.buz == buz) & (out["수준"] == "업종")].iloc[0]["chg_pct"])
        gap = got - claimed
        mark = "일치" if abs(gap) < 0.005 else f"차이 {gap:+.2f}%p"
        print(f"  WARN  {ITEMS[buz][0]}: 재계산 {got:+.2f}% vs docs/plan/06 {claimed:+.2f}%  ({mark})")
    flat = [t.품목 for t in out[out["수준"] == "품목"].itertuples() if abs(t.chg_pct) < 1e-9]
    if flat:
        print(f"  WARN  지수가 6개월 내내 고정된 품목: {', '.join(flat)} "
              f"(단순평균을 끌어내린다. 원본이 그렇게 들어 있다)")

    print(f"\n[5] 산출물\n  INFO  {OUT_CSV} {len(out)}행")
    print("\n" + ("=== 전부 통과 ===" if ok else "=== 실패 항목 있음 ==="))
    return ok


if __name__ == "__main__":
    import sys

    sys.exit(0 if self_check() else 1)
