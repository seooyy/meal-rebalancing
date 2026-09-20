"""STEP 3~6 산출물을 한 번에 생성한다.

생성 파일:
  data/out/codebook_v1.csv          STEP 3  코드 정의 확정본
  data/out/audit_v1.csv             STEP 4  월별 관측 범위 감사
  data/out/support_v1.csv           STEP 4  조합별 관측량 분포 (기준선 결정 근거)
  data/out/case_cells_v1.csv        STEP 5  4셀 × 집단별 사례 집계
  data/out/national_baseline_v1.csv STEP 6  업종별 전국 기준선
  data/out/manifest_v1.json                 재현용 메타데이터

실행:
    python -m src.build_outputs

모든 수치는 원본에서 파생한다. 문서의 값을 베껴 넣지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from src.load import (
    AGE_FOR_COMPARISON,
    BUZ_KOREAN,
    BUZ_TARGETS,
    BUZ_WESTERN,
    CORP_AMT_SHARE_PCT,
    DAYS_A,
    DAYS_B,
    DEFAULT_CARD_PATH,
    EXPECTED_CCG_NAMES,
    EXPECTED_REGION_PAIRS,
    GROUP_MAP,
    NOISE_BAND,
    PERIOD_A,
    PERIOD_B,
    PROJECT_ROOT,
    SHARE_GATE,
    _resolve,
    aggregate,
    ambiguous_ccg,
    load_card,
)
from src.classify import AMT_BAND, CNT_BAND, UNIT_BAND, classify_row

OUT_DIR = PROJECT_ROOT / "data" / "out"

# 사례 4셀: (시도, 시군구, 업종코드, 라벨)
CASE_DEFS = [
    ("인천광역시", "미추홀구", BUZ_KOREAN, "주사례1 분해형"),
    ("경기도", "이천시", BUZ_WESTERN, "주사례2 객단가 하락"),
    ("인천광역시", "미추홀구", BUZ_WESTERN, "대조군 동반 성장"),
    ("경기도", "이천시", BUZ_KOREAN, "대조군 건강한 업종"),
]

AGE_MEANING = {
    "1": "범위 미확인",
    "2": "20대",
    "3": "30대",
    "4": "40대",
    "5": "50대",
    "6": "60대 이상",
    "x": "법인(연령 없음)",
}

GENDER_MEANING = {"1": "남성", "2": "여성", "3": "외국인", "x": "법인"}


# ---------------------------------------------------------------------------
# STEP 3 — 코드북
# ---------------------------------------------------------------------------

def build_codebook(df: pd.DataFrame) -> pd.DataFrame:
    """GENDER_CD·AGE_CD·업종코드 세 표를 long 형식 한 장으로 만든다."""
    total = df["amt"].sum()
    rows = []

    for code, share in (df.groupby("GENDER_CD")["amt"].sum() / total * 100).items():
        rows.append({
            "차원": "GENDER_CD",
            "코드": code,
            "의미": GENDER_MEANING.get(code, "?"),
            "집단": GROUP_MAP.get(code, "?"),
            "금액비중_pct": round(share, 3),
            "건당결제금액": round(
                df.loc[df.GENDER_CD == code, "amt"].sum()
                / df.loc[df.GENDER_CD == code, "cnt"].sum()
            ),
            "비고": "법인은 소문자 x. 대문자 X 아님" if code == "x" else "",
        })

    for code, share in (df.groupby("AGE_CD")["amt"].sum() / total * 100).items():
        rows.append({
            "차원": "AGE_CD",
            "코드": code,
            "의미": AGE_MEANING.get(code, "?"),
            "집단": "",
            "금액비중_pct": round(share, 3),
            "건당결제금액": round(
                df.loc[df.AGE_CD == code, "amt"].sum()
                / df.loc[df.AGE_CD == code, "cnt"].sum()
            ),
            "비고": (
                "연령 비교에서 제외 (정의 미확인)" if code == "1"
                else "연령 비교에서 제외 (법인)" if code == "x"
                else "연령 비교 대상"
            ),
        })

    buz = df.groupby(["TP_BUZ_NO", "TP_BUZ_NM"]).agg(amt=("amt", "sum"), cnt=("cnt", "sum"))
    buz = buz.sort_values("amt", ascending=False).reset_index()
    for _, r in buz.iterrows():
        is_target = r.TP_BUZ_NO in BUZ_TARGETS
        rows.append({
            "차원": "TP_BUZ_NO",
            "코드": r.TP_BUZ_NO,
            "의미": r.TP_BUZ_NM,
            "집단": "",
            "금액비중_pct": round(r.amt / total * 100, 3),
            "건당결제금액": round(r.amt / r.cnt),
            "비고": "주 분석 업종" if is_target else (
                "관측량 부족, 시군구 해석 부적합" if r.amt / total * 100 < 0.1 else ""
            ),
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# STEP 4 — 감사
# ---------------------------------------------------------------------------

def build_audit(df: pd.DataFrame) -> pd.DataFrame:
    """월별 행수·금액·건수·지역수. 계절성 확인용 지수도 함께."""
    g = df.groupby("STRD_YYMM")
    a = pd.DataFrame({
        "행수": g.size(),
        "금액": g["amt"].sum(),
        "건수": g["cnt"].sum(),
        "지역수_시도시군구쌍": g["region_key"].nunique(),
        "지역수_시군구명": g["CCG_NM"].nunique(),
        "업종수": g["TP_BUZ_NO"].nunique(),
    }).reset_index()
    a["금액_평균대비_pct"] = (a["금액"] / a["금액"].mean() * 100 - 100).round(2)
    a["기간"] = np.where(a["STRD_YYMM"].isin(PERIOD_A), "A", "B")
    return a


def build_support(df: pd.DataFrame) -> pd.DataFrame:
    """조합별 관측량 분포. 관측량 기준선 결정의 근거 자료."""
    rows = []
    for buz in BUZ_TARGETS:
        sub = df[df.TP_BUZ_NO == buz]
        nm = sub["TP_BUZ_NM"].iloc[0]

        # 지역 단위
        per_region = sub.groupby("region_key")["cnt"].sum()
        # 지역 × 집단 단위 (진단에서 실제로 쓰는 최소 단위)
        per_cell = sub.groupby(["region_key", "group", "period"])["cnt"].sum()

        for label, s in (("지역", per_region), ("지역×집단×기간", per_cell)):
            rows.append({
                "업종코드": buz,
                "업종명": nm,
                "단위": label,
                "조합수": len(s),
                "최소": int(s.min()),
                "p1": int(s.quantile(0.01)),
                "p5": int(s.quantile(0.05)),
                "p10": int(s.quantile(0.10)),
                "중앙값": int(s.median()),
                "최대": int(s.max()),
                "n_1000미만": int((s < 1000).sum()),
                "n_500미만": int((s < 500).sum()),
                "n_100미만": int((s < 100).sum()),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# STEP 5 — 4셀 사례
# ---------------------------------------------------------------------------

_METRIC_COLS = [
    "amt_A", "amt_B", "cnt_A", "cnt_B",
    "daily_amt_A", "daily_amt_B", "daily_cnt_A", "daily_cnt_B",
    "unit_A", "unit_B",
    "daily_amt_chg_pct", "daily_cnt_chg_pct", "unit_chg_pct", "share_B_pct",
]


def build_case_cells(df: pd.DataFrame) -> pd.DataFrame:
    nat = {b: aggregate(df, buz=b).iloc[0] for b in BUZ_TARGETS}
    rows = []
    for sido, ccg, buz, label in CASE_DEFS:
        buz_nm = df.loc[df.TP_BUZ_NO == buz, "TP_BUZ_NM"].iloc[0]

        tot = aggregate(df, region=ccg, sido=sido, buz=buz).iloc[0]
        dg = classify_row(tot, nat[buz])
        base = {
            "사례": label, "SIDO_NM": sido, "CCG_NM": ccg,
            "region_key": f"{sido} {ccg}", "TP_BUZ_NO": buz, "TP_BUZ_NM": buz_nm,
        }
        rows.append({
            **base, "집단": "전체",
            **{c: tot[c] for c in _METRIC_COLS},
            "방향": dg.방향, "원인": dg.원인, "변화유형": dg.라벨,
            "우선순위": dg.우선순위,
            "건당_초과분": dg.건당_초과분, "건수_초과분": dg.건수_초과분,
            "설명": dg.설명,
        })

        grp = aggregate(df, region=ccg, sido=sido, buz=buz, group_by="group")
        for _, r in grp.iterrows():
            rows.append({
                **base, "집단": r["group"],
                **{c: r[c] for c in _METRIC_COLS},
                "방향": "", "원인": "", "변화유형": "", "우선순위": "",
                "건당_초과분": round(r["unit_chg_pct"] - nat[buz]["unit_chg_pct"], 2),
                "건수_초과분": round(r["daily_cnt_chg_pct"] - nat[buz]["daily_cnt_chg_pct"], 2),
                "설명": "",
            })

    out = pd.DataFrame(rows)
    for c in ["daily_amt_chg_pct", "daily_cnt_chg_pct", "unit_chg_pct", "share_B_pct"]:
        out[c] = out[c].round(2)
    for c in ["daily_amt_A", "daily_amt_B", "daily_cnt_A", "daily_cnt_B", "unit_A", "unit_B"]:
        out[c] = out[c].round(0)
    return out


# ---------------------------------------------------------------------------
# STEP 6 — 전국 기준선
# ---------------------------------------------------------------------------

def build_national_baseline(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for buz in BUZ_TARGETS:
        buz_nm = df.loc[df.TP_BUZ_NO == buz, "TP_BUZ_NM"].iloc[0]
        tot = aggregate(df, buz=buz).iloc[0]
        rows.append({
            "TP_BUZ_NO": buz, "TP_BUZ_NM": buz_nm, "집단": "전체",
            **{c: tot[c] for c in _METRIC_COLS},
        })
        grp = aggregate(df, buz=buz, group_by="group")
        for _, r in grp.iterrows():
            rows.append({
                "TP_BUZ_NO": buz, "TP_BUZ_NM": buz_nm, "집단": r["group"],
                **{c: r[c] for c in _METRIC_COLS},
            })

    out = pd.DataFrame(rows)
    for c in ["daily_amt_chg_pct", "daily_cnt_chg_pct", "unit_chg_pct", "share_B_pct"]:
        out[c] = out[c].round(2)
    for c in ["daily_amt_A", "daily_amt_B", "daily_cnt_A", "daily_cnt_B", "unit_A", "unit_B"]:
        out[c] = out[c].round(0)
    return out


# ---------------------------------------------------------------------------
# 매니페스트
# ---------------------------------------------------------------------------

def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(df: pd.DataFrame, written: dict[str, int]) -> dict:
    src = _resolve(DEFAULT_CARD_PATH)
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": DEFAULT_CARD_PATH,
        "source_sha256": _sha256(src),
        "rows": int(len(df)),
        "months": sorted(df["STRD_YYMM"].unique().tolist()),
        "period_a": PERIOD_A,
        "period_b": PERIOD_B,
        "days_a": DAYS_A,
        "days_b": DAYS_B,
        "region_pairs": int(df["region_key"].nunique()),
        "ccg_names": int(df["CCG_NM"].nunique()),
        "ambiguous_ccg": {k: v for k, v in ambiguous_ccg(df).items()},
        "buz_targets": BUZ_TARGETS,
        "noise_band": NOISE_BAND,
        "share_gate": SHARE_GATE,
        "age_for_comparison": AGE_FOR_COMPARISON,
        "corp_amt_share_pct": round(
            float(df.loc[df.group == "법인", "amt"].sum() / df["amt"].sum() * 100), 4
        ),
        "outputs": written,
        "env": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "unresolved": [
            "CCG_NM이 가맹점 소재지인지 고객 거주지인지 미확인",
            "GENDER_CD=3(외국인)의 모집단 정의 미확인",
            "AGE_CD=1의 연령 범위 미확인",
        ],
    }


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("카드 데이터 로드 중...")
    df = load_card()
    print(f"  {len(df):,}행, {df['region_key'].nunique()}개 지역\n")

    written: dict[str, int] = {}

    def write(name: str, frame: pd.DataFrame, step: str) -> None:
        path = OUT_DIR / name
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        written[name] = len(frame)
        print(f"  {step}  {name:<28} {len(frame):>4}행")

    print("산출물 생성")
    write("codebook_v1.csv", build_codebook(df), "STEP3")
    write("audit_v1.csv", build_audit(df), "STEP4")
    write("support_v1.csv", build_support(df), "STEP4")
    write("case_cells_v1.csv", build_case_cells(df), "STEP5")
    write("national_baseline_v1.csv", build_national_baseline(df), "STEP6")

    manifest = build_manifest(df, written)
    (OUT_DIR / "manifest_v1.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  META   manifest_v1.json            sha256 {manifest['source_sha256'][:12]}...")

    return _report(df)


def _report(df: pd.DataFrame) -> int:
    """생성 결과를 눈으로 확인할 수 있게 요약 출력."""
    ok = True

    print("\n[감사] 월별 관측")
    a = pd.read_csv(OUT_DIR / "audit_v1.csv")
    for _, r in a.iterrows():
        flag = "" if r.지역수_시도시군구쌍 == EXPECTED_REGION_PAIRS else "  <- 이상"
        print(f"  {r.STRD_YYMM} ({r.기간})  지역 {r.지역수_시도시군구쌍}  "
              f"금액 {r.금액/1e12:.3f}조  평균대비 {r.금액_평균대비_pct:+.2f}%{flag}")
        ok &= r.지역수_시도시군구쌍 == EXPECTED_REGION_PAIRS
    peak = a.loc[a.금액.idxmax()]
    print(f"  최대: {peak.STRD_YYMM} ({peak.금액_평균대비_pct:+.2f}%) — A/B 비교 시 계절 주석 필요")

    print(f"\n[4셀] 진단  (밴드: 금액 ±{AMT_BAND}%, 건당초과 ±{UNIT_BAND}%p, 건수초과 ±{CNT_BAND}%p)")
    c = pd.read_csv(OUT_DIR / "case_cells_v1.csv")
    for _, r in c[c.집단 == "전체"].iterrows():
        print(f"\n  {r.region_key} {r.TP_BUZ_NM}  [{r.사례}]")
        print(f"     금액 {r.daily_amt_chg_pct:+6.2f}%   건수 {r.daily_cnt_chg_pct:+6.2f}%   "
              f"건당 {r.unit_chg_pct:+7.2f}%")
        print(f"     전국대비   건수 {r.건수_초과분:+6.2f}p   건당 {r.건당_초과분:+6.2f}p")
        print(f"     => {r.변화유형}  [{r.방향}/{r.원인}]  우선순위 {r.우선순위}")
        print(f"        {r.설명}")

    print("\n[전국 기준선]")
    n = pd.read_csv(OUT_DIR / "national_baseline_v1.csv")
    for _, r in n[n.집단 == "전체"].iterrows():
        print(f"  {r.TP_BUZ_NM:<5} 금액 {r.daily_amt_chg_pct:+6.2f}% / "
              f"건수 {r.daily_cnt_chg_pct:+6.2f}% / 건당 {r.unit_chg_pct:+6.2f}%")

    print("\n[법인] 지역 vs 전국 — 게이트 필요성 확인")
    for buz in BUZ_TARGETS:
        nat = n[(n.TP_BUZ_NO.astype(str) == buz) & (n.집단 == "법인")].iloc[0]
        print(f"  전국 {nat.TP_BUZ_NM}: {nat.daily_amt_chg_pct:+.2f}% (비중 {nat.share_B_pct:.2f}%)")
    for _, r in c[c.집단 == "법인"].iterrows():
        nat = n[(n.TP_BUZ_NO.astype(str) == str(r.TP_BUZ_NO)) & (n.집단 == "법인")].iloc[0]
        excess = r.daily_amt_chg_pct - nat.daily_amt_chg_pct
        gate = "제외" if r.share_B_pct < SHARE_GATE * 100 else "통과"
        print(f"  {r.region_key} {r.TP_BUZ_NM:<5} {r.daily_amt_chg_pct:+6.2f}%  "
              f"전국대비 {excess:+7.2f}%p  비중 {r.share_B_pct:5.2f}% -> 규모게이트 {gate}")

    print("\n[관측량 분포] 기준선 결정 근거")
    s = pd.read_csv(OUT_DIR / "support_v1.csv")
    for _, r in s.iterrows():
        print(f"  {r.업종명:<5} {r.단위:<12} 조합 {r.조합수:>5}  "
              f"최소 {r.최소:>6,}  p5 {r.p5:>7,}  중앙값 {r.중앙값:>8,}  "
              f"| 500미만 {r.n_500미만}개")

    print("\n" + ("=== 생성 완료 ===" if ok else "=== 확인 필요 ==="))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
