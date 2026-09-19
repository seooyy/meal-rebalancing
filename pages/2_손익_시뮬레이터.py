"""화면 2 · 손익 시뮬레이터 — 껍데기는 C, 안쪽은 B.

계산과 위젯은 전부 B의 `src/screen2.py`가 그린다. 이 파일이 하는 일은 넷이다.

  1. 페이지 설정·CSS·제목 (C의 page_setup)
  2. 화면 1과 같은 지역·업종 선택을 물려주기
  3. 화면 1의 진단 결과를 context로 넘기기
  4. B의 계산 결과 + A의 진단을 묶어 대안 추천을 그리기 (C의 ui/recommend.py)

**B의 render_screen2 안쪽을 여기서 다시 그리지 않는다.** 필수 문구(NOTICE),
가상 사례 경고, 관측값/추정값/가정값 태그는 B가 이미 붙인다. 여기서 또 쓰면
둘이 어긋난다. 추천은 B의 계산 결과를 **읽어서** 아래에 덧붙이는 C의 영역이다.
"""

import streamlit as st

from src.screen2 import render_screen2
from ui.common import MIN_CASES, NOTE_THIN, diagnosis, footer, note, page_setup, pct, selector
from ui.recommend import render as render_recommendation

page_setup("화면 2 · 손익 시뮬레이터")

region, buz, buz_nm = selector()
st.caption(f"선택: {region} · {buz_nm}")

# 화면 1의 진단을 참고 정보로 넘긴다. B는 이것을 별도 영역에 표시할 뿐
# 판매량 예측에 쓰지 않는다 (render_screen2 docstring).
dg = diagnosis(region, buz)
context = None

if dg is None:
    note("이 지역·업종은 진단할 수 없어 참고 정보 없이 계산만 한다.")
elif dg["관측량부족"]:
    note(f"<b>{NOTE_THIN}</b> — 관측이 기준 {MIN_CASES:,}건에 못 미쳐 "
         "지역 진단을 참고 정보로 넘기지 않는다. 계산은 그대로 할 수 있다.")
else:
    j, m = dg["판정"], dg["지표"]
    context = {
        "지역": dg["지역"],
        "업종": buz_nm,
        "판정": f'{j["라벨"]} / 우선순위 {j["우선순위"]}',
        "건당금액 변화": pct(m["건당금액_변화_pct"]),
        "건당금액 전국 대비 초과분": f'{m["건당_초과분_pp"]:+.2f}%p',
        "건수 전국 대비 초과분": f'{m["건수_초과분_pp"]:+.2f}%p',
    }
    if dg["실행후보"]:
        context["실행 후보"] = " · ".join(
            f'{c["대상"]}: {", ".join(c["후보"])}' for c in dg["실행후보"]
        )

result = render_screen2(buz=buz, context=context, key="screen2")

# 추천은 진단(dg)과 계산(result)이 모두 있어야 성립한다. context가 아니라 dg를
# 그대로 넘기는 이유는, 관측량 부족으로 context를 비운 경우에도 "왜 추천하지
# 않는지"를 화면이 말해야 하기 때문이다.
render_recommendation(result, dg)

footer()
