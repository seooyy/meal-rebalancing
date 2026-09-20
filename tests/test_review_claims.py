"""2일차 시작 전 리뷰에서 Claude가 말한 수치·판정을 원본 데이터로 다시 검증한다.

리뷰 답변에 적힌 숫자를 그대로 기대값으로 박아 두었다. 하나라도 실패하면
그 답변의 해당 주장이 틀렸다는 뜻이다.

핵심 수치(4셀·전국·법인 비중)는 src.load를 거치지 않는 csv 모듈 경로로도
따로 계산한다. 로더가 스스로를 채점하는 구조를 피하기 위해서다.

실행:
    python -m pytest tests/test_review_claims.py      # pytest가 있으면
    python -m tests.test_review_claims                # 없으면
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import math
import subprocess
from collections import Counter, defaultdict
from functools import lru_cache

import numpy as np
import pandas as pd

from src.build_outputs import (
    OUT_DIR,
    build_audit,
    build_case_cells,
    build_codebook,
    build_national_baseline,
    build_support,
)
from src.classify import CNT_BAND, classify, classify_row
from src.load import (
    BUZ_KOREAN,
    BUZ_TARGETS,
    BUZ_WESTERN,
    PROJECT_ROOT,
    aggregate,
    load_card,
    self_check,
)

RAW_CSV = PROJECT_ROOT / "data" / "ABP_CONTEST_DATA.csv"

MICHUHOL = "인천광역시 미추홀구"
ICHEON = "경기도 이천시"
ULLEUNG = "경상북도 울릉군"


def close(got, want, tol):
    assert abs(got - want) <= tol, f"got {got!r}, want {want!r} (tol {tol})"


# ---------------------------------------------------------------------------
# 공용 데이터 (한 번만 계산)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=None)
def card() -> pd.DataFrame:
    return load_card()


@lru_cache(maxsize=None)
def raw_sums():
    """src.load 없이 csv 모듈로 직접 합산한다."""
    s = defaultdict(float)
    info = {"rows": 0, "whitespace": 0, "neg": 0, "cnt0": 0, "codes_G": set(), "codes_A": set()}
    keys = Counter()
    regions_by_month = defaultdict(set)
    with open(RAW_CSV, encoding="utf-8") as f:
        for x in csv.DictReader(f):
            info["rows"] += 1
            for k in ("GENDER_CD", "AGE_CD", "TP_BUZ_NO"):
                if x[k] != x[k].strip():
                    info["whitespace"] += 1
            info["codes_G"].add(x["GENDER_CD"])
            info["codes_A"].add(x["AGE_CD"])
            a, c = float(x["amt"]), float(x["cnt"])
            info["neg"] += a < 0 or c < 0
            info["cnt0"] += c == 0
            keys[(x["STRD_YYMM"], x["SIDO_NM"], x["CCG_NM"], x["GENDER_CD"], x["AGE_CD"], x["TP_BUZ_NO"])] += 1
            regions_by_month[x["STRD_YYMM"]].add((x["SIDO_NM"], x["CCG_NM"]))
            p = "A" if x["STRD_YYMM"] in ("202601", "202602", "202603") else "B"
            s["all"] += a
            if x["GENDER_CD"] == "x":
                s["corp"] += a
            reg = f'{x["SIDO_NM"]} {x["CCG_NM"]}'
            for r in ("NAT", reg):
                s[(r, x["TP_BUZ_NO"], p, "amt")] += a
                s[(r, x["TP_BUZ_NO"], p, "cnt")] += c
    info["dup_keys"] = sum(1 for v in keys.values() if v > 1)
    info["regions_by_month"] = {m: len(v) for m, v in regions_by_month.items()}
    return s, info


def raw_change(reg, buz):
    s, _ = raw_sums()
    aA, aB = s[(reg, buz, "A", "amt")], s[(reg, buz, "B", "amt")]
    cA, cB = s[(reg, buz, "A", "cnt")], s[(reg, buz, "B", "cnt")]
    return (
        ((aB / 91) / (aA / 90) - 1) * 100,
        ((cB / 91) / (cA / 90) - 1) * 100,
        ((aB / cB) / (aA / cA) - 1) * 100,
    )


@lru_cache(maxsize=None)
def national():
    return {b: aggregate(card(), buz=b).iloc[0] for b in BUZ_TARGETS}


@lru_cache(maxsize=None)
def region_table() -> pd.DataFrame:
    """지역×업종 510칸 + 판정."""
    frames = []
    for b in BUZ_TARGETS:
        r = aggregate(card(), buz=b, group_by="region_key")
        r["buz"] = b
        r["n_min"] = r[["cnt_A", "cnt_B"]].min(axis=1)
        r["cnt_ex"] = r["daily_cnt_chg_pct"] - national()[b]["daily_cnt_chg_pct"]
        r["unit_ex"] = r["unit_chg_pct"] - national()[b]["unit_chg_pct"]
        dg = [classify_row(row, national()[b]) for _, row in r.iterrows()]
        r["방향"] = [d.방향 for d in dg]
        r["원인"] = [d.원인 for d in dg]
        r["우선순위"] = [d.우선순위 for d in dg]
        frames.append(r)
    return pd.concat(frames, ignore_index=True)


@lru_cache(maxsize=None)
def group_cells() -> pd.DataFrame:
    """지역×업종×집단 1,530칸 (노트북 A01과 같은 정의)."""
    frames = []
    for b in BUZ_TARGETS:
        nat = aggregate(card(), buz=b, group_by="group").set_index("group")
        r = aggregate(card(), buz=b, group_by=["region_key", "group"])
        r["buz"] = b
        r["n_min"] = r[["cnt_A", "cnt_B"]].min(axis=1)
        r["cnt_ex"] = r["daily_cnt_chg_pct"] - r["group"].map(nat["daily_cnt_chg_pct"])
        r["unit_ex"] = r["unit_chg_pct"] - r["group"].map(nat["unit_chg_pct"])
        r["amt_ex"] = r["daily_amt_chg_pct"] - r["group"].map(nat["daily_amt_chg_pct"])
        frames.append(r)
    return pd.concat(frames, ignore_index=True)


def iqr(s):
    return s.quantile(0.75) - s.quantile(0.25)


def row(df, region_key, buz, group=None):
    m = (df["region_key"] == region_key) & (df["buz"] == buz)
    if group is not None:
        m &= df["group"] == group
    sub = df[m]
    assert len(sub) == 1, (region_key, buz, group, len(sub))
    return sub.iloc[0]


# ===========================================================================
# 답변 1 — 1일차 점검
# ===========================================================================

def test_self_check_전부_통과():
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok = self_check(card())
    assert bool(ok)  # numpy bool을 돌려주므로 `is True`로 비교하지 않는다
    assert "FAIL" not in buf.getvalue()
    assert "전부 통과" in buf.getvalue()


CELLS = [
    (MICHUHOL, BUZ_KOREAN, -2.05, 2.82, -4.74),
    (ICHEON, BUZ_WESTERN, -1.80, 10.47, -11.11),
    (MICHUHOL, BUZ_WESTERN, 4.92, 13.90, -7.89),
    (ICHEON, BUZ_KOREAN, 3.71, 4.95, -1.18),
    ("NAT", BUZ_KOREAN, 8.13, 10.09, -1.78),
    ("NAT", BUZ_WESTERN, 7.88, 15.25, -6.39),
]


def test_로더없이_18개_수치_일치():
    for reg, buz, e_amt, e_cnt, e_unit in CELLS:
        amt, cnt, unit = raw_change(reg, buz)
        close(round(amt, 2), e_amt, 1e-9)
        close(round(cnt, 2), e_cnt, 1e-9)
        close(round(unit, 2), e_unit, 1e-9)


def test_로더없이_법인비중_613():
    s, _ = raw_sums()
    close(round(s["corp"] / s["all"] * 100, 2), 6.13, 1e-9)


def test_원본_품질_공백_음수_건수0_중복키_모두_0건():
    _, info = raw_sums()
    assert info["rows"] == 242_574
    assert info["whitespace"] == 0
    assert info["neg"] == 0
    assert info["cnt0"] == 0
    assert info["dup_keys"] == 0
    assert info["codes_G"] == {"1", "2", "3", "x"}
    assert info["codes_A"] == {"1", "2", "3", "4", "5", "6", "x"}


def test_월별_지역수_255_시군구명_233():
    _, info = raw_sums()
    assert set(info["regions_by_month"].values()) == {255}
    assert len(info["regions_by_month"]) == 6
    assert card()["CCG_NM"].nunique() == 233


def test_일수_2026년_90일_91일_윤년아님():
    assert not calendar.isleap(2026)
    assert sum(calendar.monthrange(2026, m)[1] for m in (1, 2, 3)) == 90
    assert sum(calendar.monthrange(2026, m)[1] for m in (4, 5, 6)) == 91


def test_분해잔차_208e16():
    worst = 0.0
    for reg, buz in [(MICHUHOL, BUZ_KOREAN), (ICHEON, BUZ_WESTERN),
                     (MICHUHOL, BUZ_WESTERN), (ICHEON, BUZ_KOREAN)]:
        sido, ccg = reg.split(" ")
        r = aggregate(card(), region=ccg, sido=sido, buz=buz).iloc[0]
        resid = (np.log(r["daily_amt_B"] / r["daily_amt_A"])
                 - np.log(r["daily_cnt_B"] / r["daily_cnt_A"])
                 - np.log(r["unit_B"] / r["unit_A"]))
        worst = max(worst, abs(resid))
    assert worst < 1e-10
    assert f"{worst:.2e}" == "2.08e-16", worst  # contract.md의 2.67e-16과 다르다는 주장


def test_contract에는_267e16으로_적혀있음():
    text = (PROJECT_ROOT / "config" / "contract.md").read_text(encoding="utf-8")
    assert "2.67e-16" in text
    assert "allow_mixed_buz" not in text  # 시그니처에 새 인자가 빠져 있다는 주장


def test_산출물_재현_커밋본과_동일():
    """생성 시각을 뺀 모든 산출물이 원본에서 똑같이 다시 나온다."""
    df = card()
    builders = {
        "codebook_v1.csv": build_codebook,
        "audit_v1.csv": build_audit,
        "support_v1.csv": build_support,
        "case_cells_v1.csv": build_case_cells,
        "national_baseline_v1.csv": build_national_baseline,
    }
    for name, fn in builders.items():
        fresh = fn(df)
        saved = pd.read_csv(OUT_DIR / name, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        fresh_s = pd.read_csv(
            pd.io.common.StringIO(fresh.to_csv(index=False)), dtype=str, keep_default_na=False
        )
        pd.testing.assert_frame_equal(fresh_s, saved, check_dtype=False, obj=name)


def test_sha256_031c3a5c():
    h = hashlib.sha256(RAW_CSV.read_bytes()).hexdigest()
    assert h.startswith("031c3a5c"), h


def test_민감파일_git_제외():
    root = str(PROJECT_ROOT)
    for p in [".env", "data/ABP_CONTEST_DATA.csv", "plan/MY_A_작업순서.md",
              "1. AI금융빅데이터플랫폼 소비데이터 활용 아이디어 경진대회 참가신청서류.pdf"]:
        r = subprocess.run(["git", "check-ignore", "-q", p], cwd=root)
        assert r.returncode == 0, f"ignore 안 됨: {p}"
    tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True,
                             text=True, encoding="utf-8").stdout
    assert ".env\n" not in tracked
    assert "ABP_CONTEST_DATA.csv" not in tracked


def test_region_keys_기준파일이_존재한다():
    assert (OUT_DIR / "region_keys.csv").exists()
    old = pd.read_csv(OUT_DIR / "codebook.csv", encoding="utf-8-sig")
    assert len(old) == 11


def test_여러지역_리스트는_에러없이_합산됨():
    """'region 리스트는 조용히 합산된다'는 코드 빈 곳 주장."""
    r = aggregate(card(), region=["미추홀구", "이천시"], buz=BUZ_KOREAN)
    assert len(r) == 1


# --- 4셀 판정 (답변 1 · 2) ---

def test_4셀_판정과_초과분():
    t = region_table()
    expect = [
        (MICHUHOL, BUZ_KOREAN, "감소", "동반", "높음", -7.26, -2.96),
        (ICHEON, BUZ_WESTERN, "감소", "객단가", "높음", -4.77, -4.72),
        (MICHUHOL, BUZ_WESTERN, "성장", "전국 수준", "없음", -1.34, -1.50),
        (ICHEON, BUZ_KOREAN, "성장", "방문", "낮음", -5.14, 0.60),
    ]
    for reg, buz, d, c, p, ce, ue in expect:
        r = row(t, reg, buz)
        assert (r["방향"], r["원인"], r["우선순위"]) == (d, c, p), (reg, buz)
        close(round(r["cnt_ex"], 2), ce, 1e-9)
        close(round(r["unit_ex"], 2), ue, 1e-9)


def test_이천시한식_금액초과분_마이너스442():
    r = row(region_table(), ICHEON, BUZ_KOREAN)
    close(round(r["daily_amt_chg_pct"] - national()[BUZ_KOREAN]["daily_amt_chg_pct"], 2), -4.42, 1e-9)


# --- 답변 1 · 2번 (support_v1) ---

def test_support_지역최소_집단칸최소_500미만():
    s = pd.read_csv(OUT_DIR / "support_v1.csv", encoding="utf-8-sig", dtype={"업종코드": str})
    get = lambda b, u: s[(s["업종코드"] == b) & (s["단위"] == u)].iloc[0]
    assert get("8001", "지역")["최소"] == 23_224
    assert get("8006", "지역")["최소"] == 15_021
    assert get("8001", "지역")["n_500미만"] == 0 and get("8006", "지역")["n_500미만"] == 0
    assert get("8001", "지역×집단×기간")["최소"] == 61
    assert get("8006", "지역×집단×기간")["최소"] == 16
    assert get("8001", "지역×집단×기간")["n_500미만"] == 25
    assert get("8006", "지역×집단×기간")["n_500미만"] == 15


def test_plan01_기준선_잠정안_기록됨():
    """리뷰 시점에는 '검토 후 확정' 3칸이 비어 있었다. 잠정안 기록 후 상태를 확인한다."""
    text = next((PROJECT_ROOT / "plan").glob("01_*.md")).read_text(encoding="utf-8")
    assert "검토 후 확정" not in text
    assert "A 잠정안" in text and "min(A기간 건수, B기간 건수) < 1,000" in text


# --- 답변 1 · 3번 (업종표 수치 기준) ---

def _buz_stats(sub, buz):
    t = sub["amt"].sum()
    s = sub[sub["TP_BUZ_NO"] == buz]
    return round(s["amt"].sum() / t * 100, 2), round(s["amt"].sum() / s["cnt"].sum())


def test_문서의_업종수치는_일반개인_기준():
    d = card()
    ind = d[d["GENDER_CD"].isin(["1", "2"])]
    assert _buz_stats(ind, BUZ_KOREAN) == (37.76, 36_869)
    assert _buz_stats(ind, BUZ_WESTERN) == (10.98, 11_023)
    assert _buz_stats(ind, "4020") == (15.02, 19_189)  # 슈퍼마켓도 같은 기준이라는 주장


def test_전체기준_실제값():
    d = card()
    assert _buz_stats(d, BUZ_KOREAN) == (36.86, 36_633)
    assert _buz_stats(d, BUZ_WESTERN) == (11.12, 10_965)
    close(37.76 + 10.98, 48.74, 1e-9)
    close(36.86 + 11.12, 47.98, 1e-9)


def test_문서에_일반개인_수치가_적혀있음():
    for path in [next((PROJECT_ROOT / "plan").glob("00_*.md")),
                 PROJECT_ROOT / "config" / "contract.md",
                 PROJECT_ROOT / "project_idea.md"]:
        text = path.read_text(encoding="utf-8")
        assert "36,869" in text and "11,023" in text, path.name


def test_연령표는_전체기준_50대_2389():
    d = card()
    close(round(d.loc[d["AGE_CD"] == "5", "amt"].sum() / d["amt"].sum() * 100, 2), 23.89, 1e-9)


# ===========================================================================
# 답변 2 · 3 — 이천시 한식 판정 추천
# ===========================================================================

def test_한식_건수초과분_IQR절반_538_서양_421():
    t = region_table()
    close(round(iqr(t[t["buz"] == BUZ_KOREAN]["cnt_ex"]) / 2, 2), 5.38, 1e-9)
    close(round(iqr(t[t["buz"] == BUZ_WESTERN]["cnt_ex"]) / 2, 2), 4.21, 1e-9)


def test_plan02_IQR_근거값_서양건수는_84():
    """plan/02 66행과 src/classify.py 26행 주석은 원래 서양음식 건수 IQR을 8.5로 적었다.

    실측은 8.42다 (quantile 보간을 'higher'로 바꿔야 8.54가 나온다).
    리뷰에서 발견해 8.4로 고쳤다. 다시 틀어지지 않도록 문서와 주석도 확인한다.
    """
    t = region_table()
    close(round(iqr(t[t["buz"] == BUZ_KOREAN]["cnt_ex"]), 1), 10.8, 1e-9)
    close(round(iqr(t[t["buz"] == BUZ_WESTERN]["cnt_ex"]), 2), 8.42, 1e-9)
    assert "서양 8.4)" in next((PROJECT_ROOT / "plan").glob("02_*.md")).read_text(encoding="utf-8")
    assert "서양음식 8.4%p" in (PROJECT_ROOT / "src" / "classify.py").read_text(encoding="utf-8")
    close(round(iqr(t[t["buz"] == BUZ_KOREAN]["unit_ex"]), 1), 4.0, 1e-9)
    close(round(iqr(t[t["buz"] == BUZ_WESTERN]["unit_ex"]), 1), 3.6, 1e-9)


def test_밴드538이면_이천시한식이_전국수준으로_바뀜():
    import src.classify as C
    r = row(region_table(), ICHEON, BUZ_KOREAN)
    nat = national()[BUZ_KOREAN]
    args = (r["daily_amt_chg_pct"], r["daily_cnt_chg_pct"], r["unit_chg_pct"],
            nat["daily_cnt_chg_pct"], nat["unit_chg_pct"])
    assert classify(*args).원인 == "방문"
    saved = C.CNT_BAND
    try:
        C.CNT_BAND = 5.38
        assert classify(*args).원인 == "전국 수준"
    finally:
        C.CNT_BAND = saved
    close(round(abs(r["cnt_ex"]) - CNT_BAND, 2), 0.14, 1e-9)


def test_우선순위_분포():
    t = region_table()
    ko = t[t["buz"] == BUZ_KOREAN]["우선순위"].value_counts().to_dict()
    we = t[t["buz"] == BUZ_WESTERN]["우선순위"].value_counts().to_dict()
    assert ko == {"없음": 181, "낮음": 51, "높음": 14, "중간": 9}
    assert we == {"없음": 199, "낮음": 35, "높음": 14, "중간": 7}
    assert ko["높음"] + ko["중간"] == 23 and we["높음"] + we["중간"] == 21
    assert ko["높음"] + ko["중간"] + ko["낮음"] == 74
    assert we["높음"] + we["중간"] + we["낮음"] == 56


def test_낮음은_성장이거나_정체_전국수준뿐():
    low = region_table()[region_table()["우선순위"] == "낮음"]
    ok = (low["방향"] == "성장") | ((low["방향"] == "정체") & (low["원인"] == "전국 수준"))
    assert ok.all()


# ===========================================================================
# 답변 4 · 5 — 관측량 기준선 잠정안 (노트북 A01)
# ===========================================================================

def test_포아송_이론값():
    assert math.isclose(2 / (CNT_BAND / 100) ** 2, 800)  # 부동소수점: 799.9999999999999
    for n, want in [(500, 6.3), (1000, 4.5), (2000, 3.2), (3676, 2.3)]:
        close(round(100 * math.sqrt(2 / n), 1), want, 1e-9)


def test_건수구간별_퍼짐표():
    c = group_cells().copy()
    assert len(c) == 1530
    bins = [0, 100, 250, 500, 1000, 2000, 5000, 10000, np.inf]
    c["bin"] = pd.cut(c["n_min"], bins, right=False)
    g = c.groupby("bin", observed=True).agg(
        n=("n_min", "size"),
        cnt_IQR=("cnt_ex", iqr),
        p90=("amt_ex", lambda s: s.abs().quantile(0.9)),
    )
    assert g["n"].tolist() == [3, 6, 17, 81, 103, 159, 150, 1011]
    cnt_iqr = g["cnt_IQR"].round(1).tolist()
    p90 = g["p90"].round(1).tolist()
    # 500 미만 3구간: 건수 IQR 40~1,080, 금액 p90 59~2,636
    close(min(cnt_iqr[:3]), 40.8, 1e-9)
    close(max(cnt_iqr[:3]), 1079.9, 1e-9)
    close(round(min(p90[:3])), 59, 1e-9)
    close(max(p90[:3]), 2636.2, 1e-9)
    close(cnt_iqr[3], 59.5, 1e-9)   # 500~1,000
    close(p90[3], 326.4, 1e-9)
    assert p90[3] > 300
    close(cnt_iqr[4], 41.1, 1e-9)   # 1,000~2,000
    close(p90[4], 69.2, 1e-9)
    close(cnt_iqr[7], 9.3, 1e-9)    # 10,000 이상
    close(p90[7], 36.6, 1e-9)


def test_기준별_제외규모():
    c = group_cells()
    total = c["amt_B"].sum()
    for t, n, share in [(300, 11, 0.003), (500, 26, 0.014), (1000, 107, 0.094), (2000, 210, 0.221)]:
        ex = c[c["n_min"] < t]
        assert len(ex) == n, (t, len(ex))
        close(round(ex["amt_B"].sum() / total * 100, 3), share, 1e-9)
        assert (ex["group"] != "일반개인").all()
    close(round(107 / 1530 * 100), 7, 1e-9)


def test_4셀_집단칸_최소는_이천시한식_법인_7842():
    c = group_cells()
    keys = {(MICHUHOL, BUZ_KOREAN), (ICHEON, BUZ_WESTERN), (MICHUHOL, BUZ_WESTERN), (ICHEON, BUZ_KOREAN)}
    case = c[[(k, b) in keys for k, b in zip(c["region_key"], c["buz"])]]
    assert len(case) == 12
    top = case.sort_values("n_min").iloc[0]
    assert (top["region_key"], top["buz"], top["group"], top["n_min"]) == (ICHEON, BUZ_KOREAN, "법인", 7842)


def test_울릉군_외국인_극단사례():
    c = group_cells()
    w = row(c, ULLEUNG, BUZ_WESTERN, "외국인")
    assert (w["cnt_A"], w["cnt_B"]) == (16, 391)
    assert w["cnt_A"] + w["cnt_B"] == 407
    close(round(w["daily_amt_chg_pct"], 1), 3064.8, 1e-9)
    k = row(c, ULLEUNG, BUZ_KOREAN, "외국인")
    assert (k["cnt_A"], k["cnt_B"]) == (61, 520)
    close(round(k["daily_amt_chg_pct"], 1), 974.3, 1e-9)
    assert c["n_min"].min() == 16


def test_지역단위_울릉군_서양음식_3676():
    t = region_table()
    top = t.sort_values("n_min").iloc[0]
    assert (top["region_key"], top["buz"]) == (ULLEUNG, BUZ_WESTERN)
    assert (top["cnt_A"], top["cnt_B"]) == (3676, 11915)
    close(round(top["daily_cnt_chg_pct"], 1), 220.6, 1e-9)
    assert int((t["n_min"] < 5000).sum()) == 1
    assert int((t["n_min"] < 1000).sum()) == 0


def test_지역단위_6개월합계_최소는_23224_15021():
    """처음 '지역 기준 0곳'이라 말한 근거(6개월 합계)도 사실이었는지."""
    t = region_table()
    tot = t["cnt_A"] + t["cnt_B"]
    assert tot[t["buz"] == BUZ_KOREAN].min() == 23_224
    assert tot[t["buz"] == BUZ_WESTERN].min() == 15_021


# ---------------------------------------------------------------------------
# pytest 없이 실행
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import time
    import traceback

    tests = [(n, f) for n, f in list(globals().items()) if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        t0 = time.time()
        try:
            import contextlib, io
            with contextlib.redirect_stdout(io.StringIO()):
                fn()
            print(f"  PASS  {name}  ({time.time() - t0:.1f}s)")
        except Exception:
            failed.append(name)
            print(f"  FAIL  {name}")
            traceback.print_exc(limit=2)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} 통과")
    sys.exit(1 if failed else 0)
