"""대안 추천 테스트 — C 담당.

카드 원본 없이 돈다. 진단 결과는 A의 diagnose()가 돌려주는 모양으로 직접 만들고,
계산 결과는 B의 evaluate_inputs()가 설정 파일만 읽어 만드는 기본값을 쓴다.
"""
from __future__ import annotations

import pytest

from src.screen2 import evaluate_inputs
from ui.recommend import load_policy, rank, rows_for_all, shortlist


@pytest.fixture(scope="module")
def result():
    """기본 폼 = 가상 한식 매장, 원가 직접 입력, 기준 시나리오."""
    return evaluate_inputs()


def diagnosis(cause, candidates, *, priority="높음", thin=False, gates=()):
    return {
        "지역": "경기도 이천시", "업종": "8006",
        "판정": {"방향": "감소", "원인": cause, "라벨": f"{cause} 문제",
               "우선순위": priority, "설명": ""},
        "실행후보": [{"규칙": "t", "대상": "전체", "확인": None, "후보": list(candidates)}],
        "게이트": list(gates), "관측량부족": thin,
    }


# ---- 정책 -------------------------------------------------------------------

def test_정책의_대안_구분은_B의_options와_일치한다():
    policy = load_policy()
    kinds = set(policy["candidate_kinds"].values())
    assert kinds <= {"구성 재설계", "혜택 재설계", "판매 노출 개선", "주문·운영 편의 개선"}
    assert policy["ranking"]["metric"] == "increase_pct"


def test_rules의_모든_후보_문자열이_표에_있다():
    """A가 후보 문구를 바꾸면 여기서 먼저 깨진다. 화면에서 조용히 빠지지 않게."""
    from src.diagnose import load_rules

    rules = load_rules()
    table = load_policy()["candidate_kinds"]
    names = {n for r in rules["cell_rules"] for n in r["후보"]}
    names |= {n for r in rules["group_rules"] for n in r["후보"]}
    assert names <= set(table), f"recommend.yaml에 없는 후보: {sorted(names - set(table))}"


# ---- 1단계 ------------------------------------------------------------------

def test_객단가_문제에는_혜택_재설계를_추천하지_않는다():
    """기획서 3절: 여기서 할인하면 객단가 하락을 가속한다."""
    picked = shortlist(diagnosis("객단가", ["메뉴 구성 조정", "상위 옵션 노출", "기본형＋선택 옵션"]))
    assert picked["state"] == "filtered"
    assert set(picked["kinds"]) == {"구성 재설계", "판매 노출 개선"}
    assert "혜택 재설계" not in picked["kinds"]


def test_방문_문제에는_혜택_재설계가_들어온다():
    picked = shortlist(diagnosis("방문", ["주문 과정 개선", "조건부 혜택"]))
    assert set(picked["kinds"]) == {"주문·운영 편의 개선", "혜택 재설계"}


def test_진단이_없으면_필터하지_않고_추천이라고_부르지_않는다():
    picked = shortlist(None)
    assert picked["state"] == "unfiltered"
    assert picked["kinds"] is None


def test_관측량_부족이면_진단을_근거로_쓰지_않는다():
    picked = shortlist(diagnosis("객단가", ["메뉴 구성 조정"], thin=True))
    assert picked["state"] == "unfiltered"


def test_후보가_비면_추천하지_않고_게이트_사유를_남긴다():
    dg = diagnosis("전국 수준", [], gates=["전국 초과분 게이트: 전국 공통 흐름"])
    dg["실행후보"] = []
    picked = shortlist(dg)
    assert picked["state"] == "empty"
    assert picked["kinds"] == {}
    assert picked["notes"] == ["전국 초과분 게이트: 전국 공통 흐름"]


def test_표에_없는_후보는_조용히_버리지_않는다():
    picked = shortlist(diagnosis("객단가", ["메뉴 구성 조정", "A가 새로 만든 후보"]))
    assert picked["unknown"] == ["A가 새로 만든 후보"]
    assert set(picked["kinds"]) == {"구성 재설계"}


# ---- 2단계 ------------------------------------------------------------------

def test_네_대안을_같은_대상_메뉴로_모두_계산한다():
    """B의 화면은 세 개만 계산한다. 추천은 네 개를 같은 조건에 놓아야 비교가 된다."""
    rows = rows_for_all(evaluate_inputs())
    assert {r["alternative_id"] for r in rows} == {"discount", "redesign", "visibility", "ordering"}
    assert len({r["target_menu"] for r in rows}) == 1
    assert len(rows) == 4 * 3  # 대안 4 x 원가 3단계


def test_순위는_필요_증가율_오름차순이다(result):
    outcome = rank(result)
    rates = [r["increase_pct"] for r in outcome["ranked"]]
    assert rates == sorted(rates)
    assert [r["순위"] for r in outcome["ranked"]] == list(range(1, len(rates) + 1))
    assert all(r["cost_level"] == "base" for r in outcome["ranked"])


def test_구성_조정이_할인보다_앞선다(result):
    """기획서 7절의 예시와 같은 방향. 원가가 함께 줄면 필요 증가율이 작다."""
    outcome = rank(result)
    order = [r["alternative_id"] for r in outcome["ranked"]]
    assert order.index("redesign") < order.index("discount")


def test_진단_필터가_할인안을_순위에서_뺀다(result):
    picked = shortlist(diagnosis("객단가", ["메뉴 구성 조정", "상위 옵션 노출"]))
    outcome = rank(result, picked["kinds"])
    assert "discount" not in {r["alternative_id"] for r in outcome["ranked"]}
    assert "redesign" in {r["alternative_id"] for r in outcome["ranked"]}


def test_달성_불가_대안은_순위가_아니라_제외로_간다():
    """건당 공헌이익이 0 이하면 최하위가 아니라 계산 불가다."""
    # 백반류 10,000원에서 7,000원을 깎으면 수수료·포장비·노동비를 빼고 남는 것이 없다.
    form = {"discount.price_delta": -7000}
    outcome = rank(evaluate_inputs(form))
    excluded = {r["alternative_id"]: r["제외사유"] for r in outcome["excluded"]}
    assert "discount" in excluded
    assert "달성 불가" in excluded["discount"]
    assert "discount" not in {r["alternative_id"] for r in outcome["ranked"]}


def test_판매량을_모르면_지수로_순위를_낸다():
    form = {f"{m}.daily_volume": "" for m in ("rice_set", "stew", "noodle")}
    outcome = rank(evaluate_inputs(form))
    assert outcome["ranked"]
    assert all(r["required_volume"] is None for r in outcome["ranked"])
    assert all(r["required_index"] is not None for r in outcome["ranked"])


def test_원가_범위에_따라_1순위가_바뀌면_표시한다(result):
    outcome = rank(result)
    tops = {v for v in outcome["tops"].values() if v}
    assert outcome["unstable"] == (len(tops) > 1)


def test_가격을_바꾸지_않는_대안은_표시로_구분한다(result):
    """도입비용만 반영돼 구조적으로 상위에 오른다. 계산이 유리한 것과 다르다."""
    outcome = rank(result)
    flags = {r["alternative_id"]: r["가격변경없음"] for r in outcome["ranked"]}
    assert flags["visibility"] is True and flags["ordering"] is True
    assert flags["discount"] is False and flags["redesign"] is False
