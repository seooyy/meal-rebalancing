"""확인 항목 안내 테스트 — C 담당.

A가 rules.yaml의 확인 문구를 바꾸면 화면에서 안내가 조용히 빠진다.
여기서 먼저 깨지게 한다.
"""
from __future__ import annotations

import yaml

from src.diagnose import load_rules
from ui.common import CHECK_GUIDE_PATH, split_checks

GUIDE = yaml.safe_load(CHECK_GUIDE_PATH.read_text(encoding="utf-8"))["items"]


def rule_checks():
    rules = load_rules()
    texts = [r["확인"] for r in rules["cell_rules"] if r["확인"]]
    texts += [r["확인"] for r in rules["group_rules"] if r["확인"]]
    return {name for t in texts for name in split_checks(t)}


def test_확인_문자열을_항목으로_끊는다():
    assert split_checks("영업일·품절·주문 불편·고객 의견, 그리고 메뉴 판매 비중·옵션 선택률") == [
        "영업일", "품절", "주문 불편", "고객 의견", "메뉴 판매 비중", "옵션 선택률"]
    assert split_checks("실제 이용 언어와 주문의 어려움") == ["실제 이용 언어와 주문의 어려움"]
    assert split_checks("예약·단체 주문·증빙 요청") == ["예약", "단체 주문", "증빙 요청"]
    assert split_checks(None) == []


def test_rules의_모든_확인_항목에_안내가_있다():
    missing = sorted(rule_checks() - set(GUIDE))
    assert not missing, f"check_guide.yaml에 없는 확인 항목: {missing}"


def test_안내는_항목마다_한_줄이다():
    for name, g in GUIDE.items():
        assert g.get("안내"), f"{name}의 안내가 비었다"
        assert "\n" not in g["안내"], f"{name}의 안내가 여러 줄이다"


def test_메뉴를_바꿀_일이_아닌_항목은_따로_표시한다():
    """영업일·품절이 원인이면 손익 시뮬레이터를 돌리기 전에 끝난다."""
    stops = {n for n, g in GUIDE.items() if g.get("stop")}
    assert stops == {"영업일", "품절"}


def test_쓰이지_않는_안내는_남기지_않는다():
    """rules.yaml이 부르지 않는 항목이 쌓이면 어느 것이 실제로 쓰이는지 알 수 없다."""
    unused = sorted(set(GUIDE) - rule_checks())
    assert not unused, f"rules.yaml이 부르지 않는 항목: {unused}"
