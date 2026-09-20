"""1단계: 지역과 업종의 소비 진단."""

import pandas as pd
import streamlit as st

from ui.common import (
    baseline,
    cases,
    check_guide,
    cpi_change,
    diagnosis,
    footer,
    load_csv,
    MIN_CASES,
    note,
    NOTE_THIN,
    obs_count,
    observed,
    page_setup,
    pct,
    pp,
    priority_badge,
    region_metrics,
    selector,
    split_checks,
    stepper,
    won,
    won_exact,
)

ACTION_LABELS = {
    "선택형 세트 구성": "고객이 선택할 수 있는 세트 구성",
    "사이드 메뉴 노출": "사이드 메뉴가 잘 보이도록 개선",
    "주문 과정 개선": "주문 절차 개선",
    "메뉴 구성 조정": "메뉴 구성 조정",
    "상위 옵션 노출": "추가 옵션이 잘 보이도록 개선",
    "기본형＋선택 옵션": "기본 메뉴와 선택 옵션 구성",
    "조건부 혜택": "조건을 정한 혜택 제공",
    "사진 메뉴판": "사진을 활용한 메뉴판",
    "다국어 메뉴 설명": "다국어 메뉴 설명",
    "예약 구성": "예약 조건과 구성 정비",
    "주문·증빙 안내": "주문 및 증빙 절차 안내",
}

page_setup("1단계. 지역 진단")
stepper(1)
st.caption("우리 지역의 결제 변화를 전국 흐름과 비교하고, 가게에서 확인할 실행안을 찾습니다.")

region, buz, buz_nm = selector()

st.subheader("1. 핵심 변화")

m = region_metrics(region, buz)
nat = baseline(buz)

if not len(m):
    st.info("선택한 지역과 업종은 관측 자료가 없어 지표를 표시할 수 없습니다.")
elif not observed(m.iloc[0].cnt_A, m.iloc[0].cnt_B):
    r = m.iloc[0]
    note(f"<b>{NOTE_THIN}</b> — 1~3월 {cases(r.cnt_A)}, 4~6월 {cases(r.cnt_B)}로 "
         f"두 기간 중 적은 쪽이 기준 {MIN_CASES:,}건에 못 미칩니다. 변화율은 표시하지 않습니다.")
else:
    r = m.iloc[0]

    specs = [
        ("일평균 결제금액", r.daily_amt_A, r.daily_amt_B, r.daily_amt_chg_pct, won),
        ("일평균 결제건수", r.daily_cnt_A, r.daily_cnt_B, r.daily_cnt_chg_pct, cases),
        ("건당 결제금액", r.unit_A, r.unit_B, r.unit_chg_pct, won_exact),
    ]
    for col, (label, a, b, chg, fmt) in zip(st.columns(3), specs):
        with col:
            st.metric(label, fmt(b), pct(chg))
            st.caption(f"1\\~3월 {fmt(a)} → 4\\~6월 {fmt(b)}")

    st.caption(f"관측 {cases(obs_count(r.cnt_A, r.cnt_B))} (두 기간 중 적은 쪽), "
               f"기준 {MIN_CASES:,}건 이상")

    st.markdown("**전국과 비교**")
    if nat is None:
        st.warning("전국 비교 데이터를 불러오지 못했습니다. 지역 수치만으로는 변화를 판단하기 어렵습니다.")
    else:
        rows = [
            ("일평균 결제금액", r.daily_amt_chg_pct, nat.daily_amt_chg_pct),
            ("일평균 결제건수", r.daily_cnt_chg_pct, nat.daily_cnt_chg_pct),
            ("건당 결제금액", r.unit_chg_pct, nat.unit_chg_pct),
        ]
        st.dataframe(
            pd.DataFrame([
                {"지표": k, region: pct(v), f"전국 {buz_nm}": pct(n), "전국 대비 차이": pp(v - n)}
                for k, v, n in rows
            ]),
            hide_index=True, width="stretch",
        )
        st.caption("**전국 대비 차이**는 이 지역의 변화율에서 같은 업종의 전국 변화율을 뺀 값입니다. "
                   "0에 가까우면 전국과 비슷한 흐름이고, 양수면 전국보다 높으며 음수면 전국보다 낮습니다. "
                   "전국에서도 두 업종 모두 건당 결제금액이 떨어졌다 "
                   "(일반한식 −1.78%, 서양음식 −6.39%).")

    st.markdown("**고객 집단별 변화**")
    st.caption(
        "일반 개인, 외국인, 법인이 이 지역의 결제금액에서 차지하는 비중과 변화를 보여줍니다. "
        "‘전국 대비 차이’는 이 지역의 변화율에서 같은 업종과 고객 집단의 전국 변화율을 뺀 값입니다. "
        "양수면 전국보다 더 늘었고, 음수면 전국보다 덜 늘었거나 더 많이 줄었다는 뜻입니다."
    )
    g = region_metrics(region, buz, group_by="group")
    if not len(g):
        st.caption("고객 집단별 관측 자료가 없습니다.")
    else:
        recs, thin = [], []
        for t in g.sort_values("share_B_pct", ascending=False).itertuples():
            if not observed(t.cnt_A, t.cnt_B):
                thin.append(f"{t.group} {cases(obs_count(t.cnt_A, t.cnt_B))}"
                            f"(비중 {t.share_B_pct:.2f}%)")
                continue
            gn = baseline(buz, t.group)
            excess = (lambda v, c: pp(v - getattr(gn, c)) if gn is not None else "—")
            recs.append({
                "집단": t.group,
                "4~6월 금액 비중": f"{t.share_B_pct:.2f}%",
                "관측 건수": cases(obs_count(t.cnt_A, t.cnt_B)),
                "일평균 금액": pct(t.daily_amt_chg_pct),
                "전국 대비 금액 차이": excess(t.daily_amt_chg_pct, "daily_amt_chg_pct"),
                "일평균 건수": pct(t.daily_cnt_chg_pct),
                "전국 대비 건수 차이": excess(t.daily_cnt_chg_pct, "daily_cnt_chg_pct"),
                "건당 금액": pct(t.unit_chg_pct),
                "전국 대비 건당 차이": excess(t.unit_chg_pct, "unit_chg_pct"),
            })

        if recs:
            st.dataframe(pd.DataFrame(recs), hide_index=True, width="stretch")
        else:
            st.caption("모든 고객 집단이 관측량 기준에 못 미쳐 변화율을 표시할 수 없습니다.")

        if thin:
            note(f"<b>{NOTE_THIN}</b> — {', '.join(thin)}. "
                 f"두 기간 중 적은 쪽이 {MIN_CASES:,}건 미만이라 변화율을 표에서 제외했습니다. "
                 "해당 결제금액은 위의 전체 수치에는 포함됩니다.")

    cpi = cpi_change(buz)
    if cpi is not None and nat is not None:
        st.markdown("**물가 참고 지표**")
        real_region = r.unit_chg_pct - cpi
        real_nat = nat.unit_chg_pct - cpi
        st.dataframe(
            pd.DataFrame([
                {"건당 결제금액": region, "명목": pct(r.unit_chg_pct),
                 "외식 물가": pct(cpi), "실질(참고)": pct(real_region)},
                {"건당 결제금액": f"전국 {buz_nm}", "명목": pct(nat.unit_chg_pct),
                 "외식 물가": pct(cpi), "실질(참고)": pct(real_nat)},
            ]),
            hide_index=True, width="stretch",
        )
        note(
            "<b>물가를 고려한 참고값입니다.</b><br>"
            "전국 외식 소비자물가 상승률을 건당 결제금액 변화율에서 단순히 뺀 값입니다. "
            "지역별 물가와 실제 구매 품목의 비중은 반영하지 않았습니다. "
            "물가를 고려해도 감소가 남는지 확인하는 용도로만 봐주세요."
        )

# ---- 유사 지역 비교 --------------------------------------------------------

st.subheader("2. 유사 지역 비교")
st.markdown(
    r"인구 특성 3가지와 1\~3월 소비 특성 2가지를 기준으로 비슷한 지역을 찾았습니다. "
    "선택한 지역과 유사 지역의 값을 아래 표에서 비교할 수 있습니다."
)

sim = load_csv("similar_regions.csv")
feat = load_csv("match_features.csv")

if not len(sim) or not len(feat):
    st.warning("유사 지역 산출물이 없어 비교를 표시할 수 없습니다.")
else:
    cur = sim[(sim["region_key"] == region) & (sim["buz"].astype(str) == buz)]
    fv = feat[feat["buz"].astype(str) == buz].set_index("region_key")

    if not len(cur):
        st.info("선택한 지역과 업종은 관측 자료가 없어 비교할 수 없습니다.")
    else:
        note_txt = cur.iloc[0].get("note", "")
        if isinstance(note_txt, str) and note_txt:
            st.warning(note_txt)

        nb = cur[cur["rank"] > 0]

        def row(key, rank_label, dist):
            f = fv.loc[key] if key in fv.index else None
            return {
                "순위": rank_label,
                "지역": key,
                "총인구": f"{int(f.pop_total):,}명" if f is not None else "—",
                "20~30대": f"{f.ratio_20_39:.1f}%" if f is not None else "—",
                "60대 이상": f"{f.ratio_60_plus:.1f}%" if f is not None else "—",
                "1~3월 일평균": f"{f.daily_amt_A / 1e8:.2f}억" if f is not None else "—",
                "1~3월 건당": f"{int(f.unit_A):,}원" if f is not None else "—",
                "거리": "—" if dist is None else f"{dist:.2f}",
            }

        table = [row(region, "기준", None)]
        table += [row(t.neighbor_key, str(int(t.rank)), t.distance) for t in nb.itertuples()]
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

        st.caption("**유사도 거리**는 5가지 특성의 차이를 하나의 값으로 나타낸 것입니다. "
                   "0에 가까울수록 비슷하며, 실제 지리적 거리를 뜻하지 않습니다.")

    with st.expander("유사 지역을 선정한 기준"):
        st.markdown(
            r"""
**비교 기준 5가지**

| 구분 | 기준 | 사용한 이유 |
| --- | --- | --- |
| 인구 | 총인구 | 지역의 기본적인 상권 규모 |
| 인구 | 20\~30대 비율 | 외식 소비에 영향을 줄 수 있는 연령 구성 |
| 인구 | 60대 이상 비율 | 외식 소비에 영향을 줄 수 있는 연령 구성 |
| 소비 | 1\~3월 하루 평균 결제액 | 해당 업종의 소비 규모 |
| 소비 | 1\~3월 건당 결제액 | 가격대 |

각 기준은 단위와 숫자의 크기가 다릅니다. 어느 한 기준이 결과를 좌우하지 않도록
전국 분포를 기준으로 값을 표준화한 뒤 유사도를 계산했습니다.

**선정 원칙**

1. **선정에는 1\~3월 자료만 사용했습니다.** 비교하려는 4\~6월의 변화를 선정 기준에
   포함하면 결과가 비슷한 지역을 미리 고르게 되므로 제외했습니다.
2. **업종별로 따로 계산했습니다.** 일반한식과 서양음식은 소비 규모와 건당 결제금액이
   다르므로 같은 기준으로 섞어 비교하지 않았습니다.

**결과를 주의해서 봐야 하는 경우**

- **비교 대상이 드문 지역:** 인구와 소비 특성이 다른 지역과 크게 다르면 유사 지역의 비교 가치가 낮을 수 있습니다.
- **소비 특성이 이례적인 지역:** 주민 구성은 비슷하지만 소비 규모가 크게 다르면 외부 방문객의 소비가 영향을 줬을 수 있습니다.

지역 소비 지표는 BC카드 결제 데이터를 지역별로 집계한 결과입니다.
"""
        )

st.subheader("3. 판정과 실행 후보")
st.caption("카드 결제 데이터로 매장에서 먼저 확인할 항목과 실행 후보를 찾았습니다. "
           "아직 매장의 가격, 원가, 판매량을 반영하지 않았으므로 추천 순위는 다음 단계에서 결정합니다.")

dg = diagnosis(region, buz)

if dg is None:
    st.info("선택한 지역과 업종은 진단할 수 없습니다.")
elif dg["관측량부족"]:
    note(f"<b>{NOTE_THIN}</b> — 관측 {cases(dg['지표']['관측건수_최소'])}로 기준 "
         f"{MIN_CASES:,}건에 못 미칩니다. 판정과 실행 후보는 표시하지 않습니다.")
else:
    j = dg["판정"]
    st.markdown(
        f'<div class="mr-verdict">{priority_badge(j["우선순위"])}<b>{j["라벨"]}</b>'
        f'<br><span class="mr-verdict-why">{j["설명"]}</span></div>',
        unsafe_allow_html=True,
    )

    mi = dg["지표"]
    st.caption("**판정의 근거** — 이 지역의 변화율을 같은 업종의 전국 변화율과 비교했습니다.")
    for 이름, 지역값, 초과분, 전국열 in (
        ("결제건수", mi["일평균건수_변화_pct"], mi["건수_초과분_pp"], "daily_cnt_chg_pct"),
        ("건당금액", mi["건당금액_변화_pct"], mi["건당_초과분_pp"], "unit_chg_pct"),
    ):
        # 반올림 오차를 피하려고 전국값을 초과분에서 역산하지 않는다.
        전국값 = float(nat[전국열]) if nat is not None else 지역값 - 초과분
        움직임 = "늘었습니다" if 지역값 > 0 else "줄었습니다" if 지역값 < 0 else "변화가 없습니다"
        견줌 = "낮습니다" if 초과분 < 0 else "높습니다"
        st.caption(f"**{이름}:** 이 지역은 {pct(지역값)}로 {움직임}. "
                   f"전국 {pct(전국값)}와 비교하면 {abs(초과분):.2f}%p {견줌}.")
    st.caption("**‘뒤처진다’가 반드시 ‘줄었다’는 뜻은 아닙니다.** 전국보다 덜 늘어난 경우도 포함합니다.")
    st.caption(f"**우선순위:** 이 지역 일평균 결제금액은 {pct(mi['일평균금액_변화_pct'])}입니다. "
               "금액이 줄고 있으면서 그 원인이 전국 공통 흐름이 아닐 때만 '높음'이 되고, "
               "늘고 있으면 전국보다 낮아도 '낮음'으로 표시합니다. "
               "지역 소비가 증가하는 상황을 문제로 단정하지 않기 위한 기준입니다.")

    cands = dg["실행후보"]
    if cands:
        guide = check_guide()
        갈라읽기 = len(cands) > 1
        for c in cands:
            대상 = "지역 전체" if c["대상"] == "전체" else f'{c["대상"]} 집단'
            범위 = ("집단을 나누지 않은 지역 전체" if c["대상"] == "전체"
                  else f'4~6월 금액의 {c["B기간_비중_pct"]:.2f}%를 차지하는 집단')
            if not 갈라읽기:
                대상, 범위 = "", ""

            checks, 멈춤항목 = [], []
            for name in split_checks(c["확인"]):
                g = guide.get(name)
                if g is None:
                    checks.append(f'<li><span class="mr-check-name">{name}</span></li>')
                    continue
                if g.get("stop"):
                    멈춤항목.append(name)
                멈춤 = ('<span class="mr-check-stop">먼저 해결</span>'
                      if g.get("stop") else "")
                checks.append(
                    f'<li><span class="mr-check-name">{name}</span>{멈춤}'
                    f'<span class="mr-check-see">{g["안내"]}</span></li>'
                )

            items = "".join(f"<li>{ACTION_LABELS.get(x, x.replace('·', ' 및 '))}</li>" for x in c["후보"])
            extra = f'<div class="mr-card-note">{c["비고"]}</div>' if c.get("비고") else ""
            기준 = "전국" if c["대상"] == "전체" else "전국 같은 집단"
            초과 = c["전국_대비_초과분_pp"]
            수치 = (f'{기준} 대비 {abs(초과):.2f}%p 낮음' if 초과 < 0
                  else f'{기준} 대비 {초과:.2f}%p 높음')
            st.markdown(
                f'<div class="mr-card">'
                f'<div class="mr-card-head"><b>① 매장에서 먼저 확인할 것</b>'
                f'<span class="mr-card-num">{f"{범위}<br>" if 범위 else ""}{수치}</span></div>'
                f'<div class="mr-card-desc">{f"<b>{대상}</b><br>" if 대상 else ""}'
                f'카드 데이터만으로는 원인을 알 수 없습니다. 아래 항목을 순서대로 확인해 주세요.</div>'
                f'<ol class="mr-check-list">{"".join(checks)}</ol></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="mr-card">'
                f'<div class="mr-card-head"><b>② 손익을 비교할 실행안</b>'
                f'<span class="mr-card-num">{대상}</span></div>'
                f'<div class="mr-card-desc">확인한 내용과 관련된 실행안만 다음 단계에서 비교합니다.'
                f'{f" {", ".join(멈춤항목)}에서 원인을 찾았다면 실행안을 비교하기 전에 해당 문제부터 해결해 주세요." if 멈춤항목 else ""}</div>'
                f'<ul class="mr-card-list">{items}</ul>{extra}</div>',
                unsafe_allow_html=True,
            )
        tail = ("아직 실행안의 우선순위는 정해지지 않았습니다. 가게 정보에 메뉴, 원가, 판매량을 입력하면 "
                "**손익 검증**에서 실행안별 필요 판매량을 비교할 수 있습니다.")
        if len(cands) > 1:
            tail = "카드는 대상별로 구분했습니다. **결제금액 비중이 큰 집단부터** 확인해 주세요. " + tail
        st.caption(tail)
        st.page_link("pages/2_가게_정보.py", label="가게 정보 입력하고 손익 검증하기 →")
    elif dg["참고"]:
        note(dg["참고"])

footer()
