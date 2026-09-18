"""화면 1 · 지역 진단 — C 소유. 2일차 오전~오후에 채운다."""

import pandas as pd
import streamlit as st

from ui.common import footer, load_csv, page_setup, selector, todo

page_setup("화면 1 · 지역 진단")

region, buz, buz_nm = selector()
st.caption(f"선택: {region} · {buz_nm}")

st.subheader("지표")
todo("C", "일평균 금액·건수·건당금액 (A→B 변화율) + 전국 기준선 병기")

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
