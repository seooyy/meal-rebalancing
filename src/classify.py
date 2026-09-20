"""변화 유형 분류.

절대 변화율만 보면 안 되는 이유:

  전국 서양음식 건당금액이 −6.39% 하락한 상황에서, 어떤 지역의 −4.13%는
  '하락'이 아니라 '전국보다 2.26%p 선방'이다. 반대로 −11.11%는 전국보다
  4.72%p 더 빠진 지역 고유의 문제다. 절대 수치만 보면 둘 다 "객단가 하락"
  으로 같게 취급된다.

그래서 두 층으로 판정한다.

  1층 방향 : 일평균 결제금액이 늘었나 줄었나 (절대 변화)
  2층 원인 : 건수와 건당금액 중 무엇이 전국보다 부진한가 (전국 대비 초과분)

계약: docs/contract.md, docs/plan/02_지역_소비집단_진단.md
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

# ---------------------------------------------------------------------------
# 임계값 — 255개 지역 초과분 분포의 사분위 범위(IQR) 절반에서 도출
#
#   건당금액 초과분 IQR: 한식 4.0%p, 서양음식 3.6%p  -> 밴드 ±2.0%p
#   건수     초과분 IQR: 한식 10.8%p, 서양음식 8.4%p -> 밴드 ±5.0%p
#
# 두 지표의 변동 폭이 4배 가까이 달라 같은 밴드를 쓰면 안 된다.
# 건수에 ±2%p를 쓰면 지역의 75~80%가 "부진"으로 잡힌다.
# ---------------------------------------------------------------------------

AMT_BAND = 1.0   # 일평균 금액 변화 ±1% 안쪽은 "정체"
UNIT_BAND = 2.0  # 건당금액 초과분 ±2%p 안쪽은 "전국 수준"
CNT_BAND = 5.0   # 건수 초과분 ±5%p 안쪽은 "전국 수준"


@dataclass
class Diagnosis:
    """진단 결과. 화면과 rules.yaml이 이 필드를 참조한다."""

    방향: str          # 감소 | 정체 | 성장
    원인: str          # 객단가 | 방문 | 동반 | 전국 수준
    라벨: str          # 화면에 표시할 한 줄
    우선순위: str      # 높음 | 중간 | 낮음 | 없음
    건당_초과분: float
    건수_초과분: float
    설명: str

    def to_dict(self) -> dict:
        return asdict(self)


def _direction(amt_chg: float) -> str:
    if amt_chg < -AMT_BAND:
        return "감소"
    if amt_chg > AMT_BAND:
        return "성장"
    return "정체"


def _cause(cnt_excess: float, unit_excess: float) -> str:
    unit_bad = unit_excess < -UNIT_BAND
    cnt_bad = cnt_excess < -CNT_BAND
    if unit_bad and cnt_bad:
        return "동반"
    if unit_bad:
        return "객단가"
    if cnt_bad:
        return "방문"
    return "전국 수준"


def classify(
    amt_chg: float,
    cnt_chg: float,
    unit_chg: float,
    nat_cnt_chg: float,
    nat_unit_chg: float,
) -> Diagnosis:
    """지역 변화율과 동일 업종 전국 변화율을 받아 진단을 돌려준다.

    Parameters
    ----------
    amt_chg, cnt_chg, unit_chg : 해당 지역·업종의 A→B 변화율 (%)
    nat_cnt_chg, nat_unit_chg : 동일 업종 전국 변화율 (%)

    Notes
    -----
    금액 초과분이 아니라 **건수·건당금액 초과분**으로 원인을 가른다.
    금액은 두 성분의 곱이라 원인 판별에 쓰면 중복 계산이 된다.
    """
    cnt_excess = cnt_chg - nat_cnt_chg
    unit_excess = unit_chg - nat_unit_chg

    direction = _direction(amt_chg)
    cause = _cause(cnt_excess, unit_excess)

    # 우선순위: 매출이 줄고 있으면서 전국보다 부진할 때만 높다.
    # 매출이 늘고 있는 매장에 "문제가 있다"고 말하면 신뢰를 잃는다.
    if direction == "감소":
        priority = "높음" if cause != "전국 수준" else "중간"
    elif direction == "정체":
        priority = "중간" if cause != "전국 수준" else "낮음"
    else:
        priority = "낮음" if cause != "전국 수준" else "없음"

    label, explain = _describe(direction, cause, cnt_excess, unit_excess)
    return Diagnosis(
        방향=direction,
        원인=cause,
        라벨=label,
        우선순위=priority,
        건당_초과분=round(unit_excess, 2),
        건수_초과분=round(cnt_excess, 2),
        설명=explain,
    )


def _describe(direction: str, cause: str, ce: float, ue: float) -> tuple[str, str]:
    if cause == "전국 수준":
        if direction == "감소":
            return (
                "전국 공통 흐름 속 감소",
                "매출은 줄었지만 건수·건당금액 모두 전국 평균과 비슷하게 움직였습니다. "
                "이 지역만의 문제로 보기 어렵습니다.",
            )
        if direction == "성장":
            return (
                "전국 수준 성장",
                "전국 흐름과 비슷하게 성장했습니다. 점검이 필요한 변화가 발견되지 않았습니다.",
            )
        return (
            "변화 미미",
            "매출도 구성도 전국 흐름과 비슷합니다. 점검이 필요한 변화가 발견되지 않았습니다.",
        )

    if cause == "객단가":
        head = "객단가 문제" if direction != "성장" else "성장 중 객단가 약세"
        return (
            head,
            f"1건당 결제금액이 전국 평균보다 {abs(ue):.1f}%p 더 떨어졌습니다. "
            "손님 수보다 주문 구성을 먼저 확인해야 합니다. "
            "여기서 할인하면 객단가 하락을 가속합니다.",
        )

    if cause == "방문":
        head = "방문 문제" if direction != "성장" else "성장 중 방문 약세"
        return (
            head,
            f"결제 건수 증가가 전국 평균보다 {abs(ce):.1f}%p 뒤처집니다. "
            "주문 구성보다 방문 기회(영업일·품절·주문 편의)를 먼저 확인해야 합니다.",
        )

    return (
        "동반 부진",
        f"건수는 전국보다 {abs(ce):.1f}%p, 건당금액은 {abs(ue):.1f}%p 뒤처집니다. "
        "한 가지 대안으로 풀기 어렵습니다. 규모가 큰 쪽부터 확인하세요.",
    )


def classify_row(region_row, national_row) -> Diagnosis:
    """aggregate() 결과 한 행과 전국 한 행을 받는 편의 함수."""
    return classify(
        amt_chg=region_row["daily_amt_chg_pct"],
        cnt_chg=region_row["daily_cnt_chg_pct"],
        unit_chg=region_row["unit_chg_pct"],
        nat_cnt_chg=national_row["daily_cnt_chg_pct"],
        nat_unit_chg=national_row["unit_chg_pct"],
    )
