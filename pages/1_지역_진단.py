"""화면 1 · 지역 진단 — C 소유. 2일차 오전~오후에 채운다."""

import pandas as pd
import streamlit as st

from ui.common import (
    age_excluded_share,
    baseline,
    cases,
    footer,
    load_csv,
    note,
    page_setup,
    pct,
    pp,
    region_metrics,
    selector,
    todo,
    won,
    won_exact,
)

page_setup("화면 1 · 지역 진단")

region, buz, buz_nm = selector()
st.caption(f"선택: {region} · {buz_nm}")

st.subheader("지표")

m = region_metrics(region, buz)
nat = baseline(buz)

if not len(m):
    st.info("이 지역·업종 조합은 관측 자료가 없어 지표를 낼 수 없다.")
else:
    r = m.iloc[0]

    # 1~3월(90일) 대 4~6월(91일). 월 수가 아니라 일수로 나눈 값이다.
    specs = [
        ("일평균 결제금액", r.daily_amt_A, r.daily_amt_B, r.daily_amt_chg_pct, won),
        ("일평균 결제건수", r.daily_cnt_A, r.daily_cnt_B, r.daily_cnt_chg_pct, cases),
        ("건당 결제금액", r.unit_A, r.unit_B, r.unit_chg_pct, won_exact),
    ]
    for col, (label, a, b, chg, fmt) in zip(st.columns(3), specs):
        with col:
            st.metric(label, fmt(b), pct(chg))
            st.caption(f"1~3월 {fmt(a)} → 4~6월 {fmt(b)}")

    # 계약 6-5절. 이 표를 빼면 전국적 흐름을 지역 고유 문제로 오진한다.
    st.markdown("**전국 기준선 병기**")
    if nat is None:
        st.warning("out/national_baseline_v1.csv 가 없어 전국 기준선을 병기하지 못한다. "
                   "기준선 없는 지역 수치는 단독으로 읽지 않는다.")
    else:
        rows = [
            ("일평균 결제금액", r.daily_amt_chg_pct, nat.daily_amt_chg_pct),
            ("일평균 결제건수", r.daily_cnt_chg_pct, nat.daily_cnt_chg_pct),
            ("건당 결제금액", r.unit_chg_pct, nat.unit_chg_pct),
        ]
        st.dataframe(
            pd.DataFrame([
                {"지표": k, region: pct(v), f"전국 {buz_nm}": pct(n), "전국 대비 초과분": pp(v - n)}
                for k, v, n in rows
            ]),
            hide_index=True, width="stretch",
        )
        st.caption("**전국 대비 초과분** = 이 지역 변화율 − 같은 업종 전국 변화율. "
                   "0에 가까우면 전국과 같은 흐름이고, 음수면 전국보다 부진하다. "
                   "전국에서도 두 업종 모두 건당 결제금액이 떨어졌다 "
                   "(일반한식 −1.78%, 서양음식 −6.39%).")

    # 집단별 분해 — GENDER_CD 기준. 법인은 소문자 x다 (계약 6-1절).
    st.markdown("**집단별 분해**")
    g = region_metrics(region, buz, group_by="group")
    if not len(g):
        st.caption("집단별 관측이 없다.")
    else:
        recs = []
        for t in g.sort_values("share_B_pct", ascending=False).itertuples():
            gn = baseline(buz, t.group)
            excess = (lambda v, c: pp(v - getattr(gn, c)) if gn is not None else "—")
            recs.append({
                "집단": t.group,
                "4~6월 금액 비중": f"{t.share_B_pct:.2f}%",
                "일평균 금액": pct(t.daily_amt_chg_pct),
                "금액 초과분": excess(t.daily_amt_chg_pct, "daily_amt_chg_pct"),
                "일평균 건수": pct(t.daily_cnt_chg_pct),
                "건수 초과분": excess(t.daily_cnt_chg_pct, "daily_cnt_chg_pct"),
                "건당 금액": pct(t.unit_chg_pct),
                "건당 초과분": excess(t.unit_chg_pct, "unit_chg_pct"),
            })
        st.dataframe(pd.DataFrame(recs), hide_index=True, width="stretch")

        ex = age_excluded_share(region, buz)
        note(
            "집단은 <code>GENDER_CD</code> 기준이다 — <code>1</code>·<code>2</code> 일반개인, "
            "<code>3</code> 외국인, <code>x</code> 법인. 초과분은 같은 집단의 전국 수치와 비교한 값이다.<br>"
            f"연령별 비교는 이 화면에 아직 없다. 붙일 때 <code>AGE_CD</code> "
            f"<code>1</code>(범위 미확인)과 <code>x</code>(법인)는 제외하며, "
            f"이 지역·업종에서 제외되는 금액 비중은 <b>{ex:.2f}%</b>다. 위 합계에는 포함돼 있다."
        )

# ---- 유사 지역 비교 --------------------------------------------------------

st.subheader("유사 지역 비교")
st.markdown(
    r"**인구 3가지 + 1\~3월 소비 2가지**, 모두 5가지가 닮은 지역을 고른다. "
    "아래 표에서 기준 지역과 값을 직접 비교할 수 있다."
)

sim = load_csv("similar_regions.csv")
feat = load_csv("match_features.csv")

if not len(sim) or not len(feat):
    todo("C", "out/similar_regions.csv · out/match_features.csv 생성 후 표시")
else:
    cur = sim[(sim["region_key"] == region) & (sim["buz"].astype(str) == buz)]
    fv = feat[feat["buz"].astype(str) == buz].set_index("region_key")

    if not len(cur):
        st.info("이 지역·업종은 관측 자료가 없어 비교할 수 없다.")
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

        st.caption("**거리**는 5가지 기준을 전국 평균 대비로 환산해 잰 값이다. "
                   "0에 가까울수록 닮았다. 지도상 거리가 아니다.")

    with st.expander("어떤 기준으로 골랐나"):
        st.markdown(
            r"""
**닮은 정도를 재는 기준 5가지**

| | 기준 | 왜 넣었나 |
| --- | --- | --- |
| 인구 | 총인구 | 상권 크기의 바탕 |
| 인구 | 20\~30대 비율 | 연령 구성이 다르면 외식 패턴이 다르다 |
| 인구 | 60대 이상 비율 | 〃 |
| 소비 | 1\~3월 하루 평균 결제액 | 업종 상권의 규모 |
| 소비 | 1\~3월 건당 결제액 | 가격대 |

단위가 제각각이라(40만 명 · 25% · 1.8억 원) 그대로 비교하면 인구가 전부 잡아먹는다.
그래서 **전국 평균에서 얼마나 벗어났는지**로 모두 바꾼 뒤 거리를 잰다.

**지키는 규칙 2가지**

1. **4\~6월 자료는 매칭에 쓰지 않는다.** 4\~6월 변화가 닮은 곳을 고르면
   "비슷한 곳을 골랐더니 비슷하더라"가 되어 비교의 의미가 사라진다.
   고를 때는 1\~3월까지만 쓰고, 4\~6월은 비교할 때만 꺼낸다.
2. **업종별로 따로 계산한다.** 건당 결제액이 한식 약 3.6만 원, 서양음식 약 1.1만 원으로
   3배 넘게 차이 난다. 섞으면 업종 구성이 가격대 차이로 둔갑한다.

**경고가 뜨는 경우 2가지**

- *비교 대상이 드물다* — 인구·소비 조건이 전국 분포에서 외따로 떨어진 지역(울릉군 등)
- *소비 성격이 이례적이다* — 주민 구성은 닮았는데 소비 규모가 딴판인 지역.
  외부에서 유입된 소비로 보인다(강남구·종로구 서양음식 등)

주민 1인당 소비로 환산하지 않는다. 카드 데이터의 지역이 가맹점 소재지인지
고객 거주지인지 확인되지 않았기 때문이다.
"""
        )

st.subheader("실행 후보")
todo("A→C", "out/region_group_metrics.csv 와 config/rules.yaml 이 나오면 연결")

footer()
