"""src/diagnose.py 회귀 테스트 (STEP 10 검증).

이 파일이 지키는 것은 두 가지다.

  1. 4셀이 문서(docs/plan/01, docs/plan/02)와 같은 판정·후보를 낸다
  2. **게이트 3개가 실제로 무언가를 막고 있다**

2번을 위해 게이트를 끈 상태와 켠 상태를 둘 다 돌린다. 게이트를 켠 결과만
검증하면 게이트가 아예 동작하지 않아도(예: 규칙이 애초에 안 걸려서)
테스트가 통과한다. 끈 상태에서 후보가 쏟아지는 것까지 봐야 게이트가
일을 하고 있다는 증거가 된다.

실행: python -m pytest tests/test_diagnose.py -q
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path

import pandas as pd
import pytest

from src.classify import CNT_BAND, UNIT_BAND
from src.diagnose import (
    GROUP_ORDER,
    PRIORITY_ORDER,
    age_cells,
    build_region_age_metrics,
    build_region_group_metrics,
    diagnose,
    group_cells,
    load_rules,
    region_cells,
)
from src.load import BUZ_KOREAN, BUZ_WESTERN, DAYS_B, aggregate, load_card

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "out"

MICHUHOL = ("미추홀구", "인천광역시")
ICHEON = ("이천시", "경기도")


@lru_cache(maxsize=None)
def card() -> pd.DataFrame:
    return load_card(validate=False)


@lru_cache(maxsize=None)
def cells() -> pd.DataFrame:
    return region_cells(card())


@lru_cache(maxsize=None)
def groups() -> pd.DataFrame:
    return group_cells(card())


@lru_cache(maxsize=None)
def rules() -> dict:
    return load_rules()


def dx(cell, buz, rules_override=None):
    region, sido = cell
    return diagnose(card(), region=region, buz=buz, sido=sido, rules=rules_override)


def relaxed(**gate_overrides) -> dict:
    """게이트 일부를 푼 규칙 사본. 원본을 건드리면 다른 테스트가 오염된다."""
    r = copy.deepcopy(rules())
    r["gates"].update(gate_overrides)
    return r


def cell_row(buz, region_key):
    t = cells()
    r = t[(t["buz"] == buz) & (t["region_key"] == region_key)]
    assert len(r) == 1, region_key
    return r.iloc[0]


def targets(result) -> list[str]:
    return [c["대상"] for c in result["실행후보"]]


# ===========================================================================
# 1. 4셀 판정 — docs/plan/02 "4셀 판정 결과 (회귀 테스트)"
# ===========================================================================

CASES = [
    (MICHUHOL, BUZ_KOREAN, "감소", "동반", "동반 부진", "높음", -7.26, -2.96),
    (ICHEON, BUZ_WESTERN, "감소", "객단가", "객단가 문제", "높음", -4.77, -4.72),
    (MICHUHOL, BUZ_WESTERN, "성장", "전국 수준", "전국 수준 성장", "없음", -1.34, -1.50),
    (ICHEON, BUZ_KOREAN, "성장", "방문", "성장 중 방문 약세", "낮음", -5.14, 0.60),
]


@pytest.mark.parametrize("cell,buz,방향,원인,라벨,우선순위,ce,ue", CASES)
def test_4셀_판정(cell, buz, 방향, 원인, 라벨, 우선순위, ce, ue):
    r = dx(cell, buz)
    assert r["판정"]["방향"] == 방향
    assert r["판정"]["원인"] == 원인
    assert r["판정"]["라벨"] == 라벨
    assert r["판정"]["우선순위"] == 우선순위
    assert r["지표"]["건수_초과분_pp"] == pytest.approx(ce, abs=0.005)
    assert r["지표"]["건당_초과분_pp"] == pytest.approx(ue, abs=0.005)


@pytest.mark.parametrize(
    "cell,buz,amt,cnt,unit",
    [
        (MICHUHOL, BUZ_KOREAN, -2.05, 2.82, -4.74),
        (ICHEON, BUZ_WESTERN, -1.80, 10.47, -11.11),
        (MICHUHOL, BUZ_WESTERN, 4.92, 13.90, -7.89),
        (ICHEON, BUZ_KOREAN, 3.71, 4.95, -1.18),
    ],
)
def test_4셀_지표가_plan01과_일치(cell, buz, amt, cnt, unit):
    m = dx(cell, buz)["지표"]
    assert m["일평균금액_변화_pct"] == pytest.approx(amt, abs=0.005)
    assert m["일평균건수_변화_pct"] == pytest.approx(cnt, abs=0.005)
    assert m["건당금액_변화_pct"] == pytest.approx(unit, abs=0.005)


# ===========================================================================
# 2. 실행 후보 — "억지로 후보를 만들지 않는다"
# ===========================================================================

def test_미추홀구_한식은_동반부진_후보가_난다():
    r = dx(MICHUHOL, BUZ_KOREAN)
    cell = [c for c in r["실행후보"] if c["대상"] == "전체"]
    assert len(cell) == 1
    assert cell[0]["규칙"] == "동반_부진"
    assert "선택형 세트 구성" in cell[0]["후보"]
    assert "사이드 메뉴 노출" in cell[0]["후보"]


def test_이천시_서양음식은_객단가_후보가_난다():
    r = dx(ICHEON, BUZ_WESTERN)
    cell = [c for c in r["실행후보"] if c["대상"] == "전체"]
    assert len(cell) == 1
    assert cell[0]["규칙"] == "객단가_문제"
    assert "메뉴 구성 조정" in cell[0]["후보"]
    assert "상위 옵션 노출" in cell[0]["후보"]
    # 할인은 객단가 하락을 가속한다 — 후보 문구에 들어가면 안 된다
    assert not any("할인" in x for x in cell[0]["후보"])


def test_이천시_한식은_후보가_비고_참고_한줄만_남는다():
    """2일차에서 가장 중요한 테스트.

    매출 +3.71%에 건당금액이 전국보다 +0.60%p 양호하다. 여기서 후보가
    나오면 도구가 억지를 부리는 것이다. 판정('성장 중 방문 약세')은
    남기되 후보는 비어야 한다.
    """
    r = dx(ICHEON, BUZ_KOREAN)
    assert r["실행후보"] == []
    assert r["참고"] is not None
    assert "5.1%p" in r["참고"]
    assert r["판정"]["라벨"] == "성장 중 방문 약세"
    assert any("우선순위 게이트" in g for g in r["게이트"])


def test_미추홀구_서양음식은_후보도_참고도_없다():
    """우선순위 '없음'은 참고 한 줄도 내보내지 않는다 (docs/plan/02 표시 규칙)."""
    r = dx(MICHUHOL, BUZ_WESTERN)
    assert r["실행후보"] == []
    assert r["참고"] is None


def test_후보가_비면_반드시_사유가_남는다():
    """빈 목록만 돌려주면 게이트가 막은 것인지 계산이 빠진 것인지 모른다."""
    for cell, buz, *_ in CASES:
        r = dx(cell, buz)
        if not r["실행후보"]:
            assert r["게이트"], (cell, buz)


# ===========================================================================
# 3. 게이트 0 — 우선순위
# ===========================================================================

def test_게이트0을_끄면_미추홀구_서양음식에_외국인_후보가_뜬다():
    """게이트 0이 실제로 일하고 있다는 증거.

    이 셀의 외국인은 +16.63%로 전국보다 +5.50%p 빠르고 비중도 7.11%라
    규모·초과분 게이트를 **통과한다.** 우선순위 게이트만이 이걸 막는다.
    """
    on = dx(MICHUHOL, BUZ_WESTERN)
    off = dx(MICHUHOL, BUZ_WESTERN, relaxed(min_priority="없음"))
    assert targets(on) == []
    assert "외국인" in targets(off)


def test_낮음은_후보를_비우되_판정은_남긴다():
    low = cells()[cells()["우선순위"] == "낮음"]
    assert len(low) == 51 + 35
    assert (~low["후보생성"]).all()
    assert low["라벨"].notna().all()


def test_후보생성_지역수_23_21():
    """'낮음'까지 포함하면 74/56곳으로 늘어난다 (docs/plan/02 근거)."""
    n = cells().groupby("buz")["후보생성"].sum().to_dict()
    assert n[BUZ_KOREAN] == 23 and n[BUZ_WESTERN] == 21

    loose = cells()["우선순위"].map(PRIORITY_ORDER) >= PRIORITY_ORDER["낮음"]
    n_loose = cells()[loose].groupby("buz").size().to_dict()
    assert n_loose[BUZ_KOREAN] == 74 and n_loose[BUZ_WESTERN] == 56


def test_우선순위_분포가_plan02_표와_일치():
    t = cells().groupby(["buz", "우선순위"]).size().unstack(fill_value=0)
    assert t.loc[BUZ_KOREAN].to_dict() == {"높음": 14, "중간": 9, "낮음": 51, "없음": 181}
    assert t.loc[BUZ_WESTERN].to_dict() == {"높음": 14, "중간": 7, "낮음": 35, "없음": 199}


# ===========================================================================
# 4. 게이트 1·2 — 규모와 전국 초과분 (법인 함정)
# ===========================================================================

def test_법인_후보는_4셀_전부에서_걸러진다():
    for cell, buz, *_ in CASES:
        assert "법인" not in targets(dx(cell, buz)), (cell, buz)


def test_게이트를_모두_끄면_법인이_4셀_전부에_뜬다():
    """docs/plan/02가 경고하는 바로 그 상황을 재현한다.

    4셀 법인은 +9.87 ~ +22.04%로 전부 규칙에 걸린다. 게이트가 없으면
    "법인 수요 증가 -> 예약 구성 도입"이 네 지역 전부에서 후보가 된다.
    실제로는 전국 법인이 +46.41%(한식) / +34.75%(서양음식)라 지역 법인은
    전국보다 **느리게** 늘었다.
    """
    off = relaxed(min_priority="없음", min_share_pct=0.0,
                  national_excess_band_pct=-999.0)
    for cell, buz, *_ in CASES:
        r = dx(cell, buz, off)
        assert "법인" in targets(r), (cell, buz)
        corp = [c for c in r["실행후보"] if c["대상"] == "법인"][0]
        assert corp["금액_변화_pct"] > 1.0
        assert corp["전국_대비_초과분_pp"] < 0  # 전국보다 느리다


@pytest.mark.parametrize(
    "cell,buz,share",
    [(MICHUHOL, BUZ_KOREAN, 3.04), (ICHEON, BUZ_WESTERN, 4.75), (ICHEON, BUZ_KOREAN, 2.43)],
)
def test_규모_게이트가_막은_법인_비중(cell, buz, share):
    r = dx(cell, buz, relaxed(min_priority="없음"))
    hit = [g for g in r["게이트"] if g.startswith("법인: 규모 게이트")]
    assert len(hit) == 1, r["게이트"]
    assert f"{share:.2f}%" in hit[0]


def test_초과분_게이트가_막은_법인_미추홀구_서양음식():
    """비중 5.23%로 규모 게이트는 통과한다. 초과분 게이트가 막는 사례."""
    r = dx(MICHUHOL, BUZ_WESTERN, relaxed(min_priority="없음"))
    hit = [g for g in r["게이트"] if g.startswith("법인: 전국 공통 흐름")]
    assert len(hit) == 1, r["게이트"]
    assert "+22.04%" in hit[0] and "-12.71%p" in hit[0]


def test_외국인_초과분_게이트_미추홀구_한식():
    """+2.77% 증가했지만 전국 외국인이 +7.94%다. 지역 고유 기회가 아니다."""
    r = dx(MICHUHOL, BUZ_KOREAN)
    hit = [g for g in r["게이트"] if g.startswith("외국인: 전국 공통 흐름")]
    assert len(hit) == 1
    assert "-5.18%p" in hit[0]


def test_감소한_집단은_규칙_자체가_안_걸린다():
    """이천시 서양음식 외국인은 -1.90%다. 게이트가 아니라 규칙 미적용이다."""
    r = dx(ICHEON, BUZ_WESTERN, relaxed(min_priority="없음", min_share_pct=0.0,
                                        national_excess_band_pct=-999.0))
    assert "외국인" not in targets(r)


def test_통과한_후보에는_비중과_초과분이_병기된다():
    """docs/plan/02: 모든 후보에 B기간 비중과 전국 대비 초과분을 반드시 함께 표시."""
    off = relaxed(min_priority="없음", min_share_pct=0.0,
                  national_excess_band_pct=-999.0)
    for cell, buz, *_ in CASES:
        for cand in dx(cell, buz, off)["실행후보"]:
            assert isinstance(cand["B기간_비중_pct"], float)
            assert isinstance(cand["전국_대비_초과분_pp"], float)


# ===========================================================================
# 5. 게이트 3 — 관측량
# ===========================================================================

def test_지역x업종_510칸은_모두_관측량_기준_통과():
    assert len(cells()) == 510
    assert cells()["관측량부족"].sum() == 0
    assert cells()["n_min"].min() == 3676  # 경상북도 울릉군 서양음식


def test_관측량_게이트가_걸리면_수치를_숨긴다():
    r = dx(MICHUHOL, BUZ_KOREAN, relaxed(min_count=10**9))
    assert r["관측량부족"] is True
    assert r["실행후보"] == []
    assert r["표시"]["대체문구"] == "관측량 부족"
    assert any("관측량 게이트" in g for g in r["게이트"])


def test_A기간_관측_0이면_정체가_아니라_판정불가():
    """classify는 NaN을 밴드와 비교해 전부 False를 받고 '정체 / 전국 수준'을
    돌려준다. 관측이 없는 것과 변화가 없는 것은 다르다.

    현재 데이터에서 이 경로를 타는 칸은 연령 코드 '1' 한 곳뿐이고 연령
    테이블에서 제외되지만, 막아두지 않으면 데이터가 바뀔 때 화면에
    "변화 미미"라는 거짓 판정이 나간다.
    """
    d = card()
    victim = (d["region_key"] == "경기도 이천시") & (d["TP_BUZ_NO"] == BUZ_KOREAN) & (
        d["period"] == "A"
    )
    holed = d[~victim]
    r = region_cells(holed, [BUZ_KOREAN])
    row = r[r["region_key"] == "경기도 이천시"].iloc[0]
    assert pd.isna(row["daily_amt_chg_pct"])
    assert row["라벨"] == "관측량 부족"
    assert row["원인"] == "판정 불가"
    assert row["관측량부족"] is True or bool(row["관측량부족"])
    assert not bool(row["후보생성"])

    one = diagnose(holed, region="이천시", buz=BUZ_KOREAN, sido="경기도")
    assert one["판정"]["라벨"] == "관측량 부족"
    assert one["실행후보"] == []


def test_현재_데이터에는_판정불가_칸이_없다():
    for frame in (cells(), groups(), age_cells(card())):
        chg = ["daily_amt_chg_pct", "daily_cnt_chg_pct", "unit_chg_pct"]
        assert frame[chg].isna().sum().sum() == 0
    assert "판정 불가" not in set(cells()["원인"])


def test_이천시_서양음식_건당초과분_순위():
    """docs/plan/00·01·02의 '하위 1%'는 과장이었다. 실측은 255곳 중 4번째다."""
    w = cells()[cells()["buz"] == BUZ_WESTERN].sort_values("unit_excess_pp")
    rank = list(w["region_key"]).index("경기도 이천시") + 1
    assert rank == 4
    assert rank / len(w) * 100 == pytest.approx(1.57, abs=0.01)
    for name in ["00_개요와_공통규칙.md", "01_데이터정의와_사례집계_확정.md",
                 "02_지역_소비집단_진단.md"]:
        text = (ROOT / "docs" / "plan" / name).read_text(encoding="utf-8")
        assert "하위 1%" not in text, name


def test_집단칸은_107개가_관측량_미달():
    """지역 칸은 다 통과해도 집단으로 쪼개면 미달이 생긴다 (최소 16건)."""
    g = groups()
    assert len(g) == 1530
    assert g["관측량부족"].sum() == 107
    assert g.groupby("buz")["관측량부족"].sum().to_dict() == {BUZ_KOREAN: 50, BUZ_WESTERN: 57}
    assert g["n_min"].min() == 16


# ===========================================================================
# 6. 산출물 정합성
# ===========================================================================

def test_집단_금액합이_전체와_일치():
    rgm = build_region_group_metrics(card())
    part = rgm[rgm["group"] != "전체"].groupby(["region_key", "buz"])["amt_B"].sum()
    whole = rgm[rgm["group"] == "전체"].set_index(["region_key", "buz"])["amt_B"]
    assert (part - whole).abs().max() < 1e-6


def test_금액기여도_합이_전체_변화율과_일치():
    """집단 기여도를 더하면 셀 전체의 일평균 금액 변화율이 나와야 한다."""
    rgm = build_region_group_metrics(card())
    part = rgm[rgm["group"] != "전체"].groupby(["region_key", "buz"])["금액기여도_pct"].sum()
    whole = rgm[rgm["group"] == "전체"].set_index(["region_key", "buz"])["daily_amt_chg_pct"]
    assert (part - whole).abs().max() < 1e-9


def test_region_group_metrics_행수_2040():
    rgm = build_region_group_metrics(card())
    assert len(rgm) == 510 * 4  # 255지역 x 2업종 x (전체 + 3집단)
    assert set(rgm["group"]) == set(GROUP_ORDER)
    assert rgm.groupby("group").size().unique().tolist() == [510]


def test_region_age_metrics_행수_2550():
    ram = build_region_age_metrics(card())
    assert len(ram) == 510 * 5  # 연령 코드 2~6
    assert sorted(ram["AGE_CD"].unique()) == ["2", "3", "4", "5", "6"]


def test_연령표_제외비중이_병기된다():
    """코드 1·x를 뺀 만큼을 같은 행에서 읽을 수 있어야 한다."""
    a = age_cells(card())
    assert a["제외비중_pct"].between(0, 100).all()
    per_cell = a.groupby(["buz", "region_key"]).agg(
        kept=("share_B_pct", "sum"), dropped=("제외비중_pct", "first")
    )
    assert (per_cell["kept"] + per_cell["dropped"] - 100).abs().max() < 1e-9


def test_판정열이_집단_행에도_따라붙는다():
    """C가 집단 행만 읽어도 그 셀의 판정을 알 수 있어야 한다."""
    rgm = build_region_group_metrics(card())
    one = rgm[(rgm["region_key"] == "경기도 이천시") & (rgm["buz"] == BUZ_WESTERN)]
    assert len(one) == 4
    assert set(one["라벨"]) == {"객단가 문제"}
    assert set(one["후보생성"]) == {True}


def test_csv가_계산결과와_동일():
    """python -m src.diagnose가 만든 파일이 지금 계산과 같아야 한다."""
    for name, builder, keys in [
        ("region_group_metrics.csv", build_region_group_metrics, ["region_key", "buz", "group"]),
        ("region_age_metrics.csv", build_region_age_metrics, ["region_key", "buz", "AGE_CD"]),
    ]:
        path = OUT_DIR / name
        assert path.exists(), f"{name}이 없다. python -m src.diagnose 를 실행한다"
        saved = pd.read_csv(path, encoding="utf-8-sig",
                            dtype={"buz": str, "AGE_CD": str})
        built = builder(card())
        assert list(saved.columns) == list(built.columns), name
        assert len(saved) == len(built), name
        num = built.select_dtypes("number").columns
        pd.testing.assert_frame_equal(
            saved[num].reset_index(drop=True), built[num].reset_index(drop=True),
            check_dtype=False, atol=1e-6,
        )
        assert saved[keys].equals(built[keys].reset_index(drop=True)), name


# ===========================================================================
# 7. 규칙 파일과 금지어
# ===========================================================================

def test_rules_yaml_게이트값():
    g = rules()["gates"]
    assert g["min_priority"] == "중간"
    assert g["min_share_pct"] == 5.0
    assert g["national_excess_band_pct"] == 1.0
    assert g["min_count"] == 1000


def test_게이트_키가_빠지면_로드에서_막힌다(tmp_path):
    """키가 없으면 게이트가 조용히 꺼진다. 그 전에 터져야 한다."""
    import yaml

    broken = copy.deepcopy(rules())
    del broken["gates"]["min_share_pct"]
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(broken, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="min_share_pct"):
        load_rules(p)


def test_잘못된_우선순위값은_로드에서_막힌다(tmp_path):
    import yaml

    broken = copy.deepcopy(rules())
    broken["gates"]["min_priority"] = "보통"
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.safe_dump(broken, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match="min_priority"):
        load_rules(p)


def test_네_가지_원인이_모두_규칙에_있다():
    assert {r["원인"] for r in rules()["cell_rules"]} == {"객단가", "방문", "동반", "전국 수준"}


def test_금지어가_산출_텍스트에_없다():
    """'20대 결제 증가 = 가성비 선호' 류 해석을 막는다. 우리 데이터에 '왜'는 없다."""
    banned = rules()["banned_phrases"]
    texts: list[str] = []
    for cell, buz, *_ in CASES:
        r = dx(cell, buz)
        texts += [r["판정"]["설명"], r["판정"]["라벨"], r["참고"] or ""]
        texts += [str(c) for c in r["실행후보"]]
        texts += r["게이트"]
    texts += list(cells()["설명"].unique()) + list(cells()["라벨"].unique())
    for word in banned:
        assert not any(word in t for t in texts), word


def test_1인당_소비_환산이_없다():
    """docs/plan/00 금지 항목. 카드 데이터에는 결제자 수가 없다."""
    src = (ROOT / "src" / "diagnose.py").read_text(encoding="utf-8")
    yml = (ROOT / "config" / "rules.yaml").read_text(encoding="utf-8")
    # rules.yaml의 banned_phrases에 '1인당'이 적혀 있는 것은 정상이다
    assert "1인당" not in src
    assert yml.count("1인당") == 1


# ===========================================================================
# 8. 업종 합산 차단이 진단 경로에서도 유지되는가
# ===========================================================================

def test_업종_생략은_여전히_에러():
    with pytest.raises(ValueError, match="buz는 필수"):
        aggregate(card())


def test_두_업종이_합쳐지지_않는다():
    for frame in (cells(), groups()):
        assert set(frame["buz"]) == {BUZ_KOREAN, BUZ_WESTERN}
    k = cell_row(BUZ_KOREAN, "인천광역시 미추홀구")
    w = cell_row(BUZ_WESTERN, "인천광역시 미추홀구")
    # 건당금액이 3배 이상 차이 난다. 합산되면 이 차이가 사라진다.
    assert k["unit_B"] / w["unit_B"] > 3


def test_밴드는_classify가_소유한다():
    """diagnose가 밴드를 다시 정의하면 두 곳이 갈라진다."""
    src = (ROOT / "src" / "diagnose.py").read_text(encoding="utf-8")
    assert "CNT_BAND" not in src and "UNIT_BAND" not in src
    assert (CNT_BAND, UNIT_BAND) == (5.0, 2.0)


def test_일수는_91일을_쓴다():
    assert DAYS_B == 91
