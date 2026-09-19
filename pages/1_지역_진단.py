"""화면 1 · 지역 진단 — C 소유. 2일차 오전~오후에 채운다."""

import pandas as pd
import streamlit as st

from ui.common import (
    age_excluded_share,
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
elif not observed(m.iloc[0].cnt_A, m.iloc[0].cnt_B):
    # 관측량 게이트. 적은 건수에서는 변화율이 크게 흔들려 그대로 읽으면 오진한다.
    r = m.iloc[0]
    # note()는 <div>로 감싸 HTML 블록이 되므로 안쪽은 마크다운으로 해석되지 않는다.
    # 물결표를 이스케이프하면 역슬래시가 그대로 보인다 (아래 st.caption과 반대).
    note(f"<b>{NOTE_THIN}</b> — 1~3월 {cases(r.cnt_A)} · 4~6월 {cases(r.cnt_B)}로 "
         f"두 기간 중 적은 쪽이 기준 {MIN_CASES:,}건에 못 미친다. 변화율을 표시하지 않는다.")
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
            # 물결표를 이스케이프한다. '1~3월 ... 4~6월'의 ~ 두 개가 짝을 이뤄
            # 마크다운 취소선이 되고 사이의 숫자가 전부 그어진다.
            st.caption(f"1\\~3월 {fmt(a)} → 4\\~6월 {fmt(b)}")

    st.caption(f"관측 {cases(obs_count(r.cnt_A, r.cnt_B))} (두 기간 중 적은 쪽) · "
               f"기준 {MIN_CASES:,}건 이상")

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
        recs, thin = [], []
        for t in g.sort_values("share_B_pct", ascending=False).itertuples():
            # 집단 칸은 1,530칸 중 107칸(7.0%)이 기준에 못 미친다.
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
                "금액 초과분": excess(t.daily_amt_chg_pct, "daily_amt_chg_pct"),
                "일평균 건수": pct(t.daily_cnt_chg_pct),
                "건수 초과분": excess(t.daily_cnt_chg_pct, "daily_cnt_chg_pct"),
                "건당 금액": pct(t.unit_chg_pct),
                "건당 초과분": excess(t.unit_chg_pct, "unit_chg_pct"),
            })

        if recs:
            st.dataframe(pd.DataFrame(recs), hide_index=True, width="stretch")
        else:
            st.caption("모든 집단이 관측량 기준에 못 미쳐 표시할 수치가 없다.")

        if thin:
            note(f"<b>{NOTE_THIN}</b> — {' · '.join(thin)}. "
                 f"두 기간 중 적은 쪽이 {MIN_CASES:,}건 미만이라 변화율을 표에서 뺐다. "
                 "위 전체 수치에는 포함돼 있다.")

        ex = age_excluded_share(region, buz)
        note(
            "집단은 <code>GENDER_CD</code> 기준이다 — <code>1</code>·<code>2</code> 일반개인, "
            "<code>3</code> 외국인, <code>x</code> 법인. 초과분은 같은 집단의 전국 수치와 비교한 값이다.<br>"
            f"연령별 비교는 이 화면에 아직 없다. 붙일 때 <code>AGE_CD</code> "
            f"<code>1</code>(범위 미확인)과 <code>x</code>(법인)는 제외하며, "
            f"이 지역·업종에서 제외되는 금액 비중은 <b>{ex:.2f}%</b>다. 위 합계에는 포함돼 있다."
        )

    # 물가 참고 지표 (단계 6-A). 주 지표가 아니라 건당금액에 붙는 각주다.
    # subheader를 쓰지 않고 낮게 배치해 주 지표처럼 보이지 않게 한다.
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
            "<b>전국 외식 물가 기준</b>이다. 시군구 물가가 아니라 지역 물가와 다를 수 있다.<br>"
            "품목 단순 평균이며 소비 비중 가중평균이 아니다. 단순 차감이며 정밀 "
            "디플레이션이 아니다. 카드 결제금액은 개인 소비 바스켓과 범위가 달라 "
            "두 지표를 같은 선상에 놓지 않는다.<br>"
            "물가 상승분을 빼고도 감소가 남는지만 본다. 주 지표를 대체하지 않는다."
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

st.subheader("판정과 실행 후보")
st.caption("여기까지는 **카드 집계만으로 낸 점검 방향**이다. 매장 가격·원가·판매량은 "
           "아직 하나도 들어가지 않았다. 어느 것을 먼저 할지는 화면 2에서 정한다.")

dg = diagnosis(region, buz)

if dg is None:
    st.info("이 지역·업종 조합은 진단할 수 없다.")
elif dg["관측량부족"]:
    note(f"<b>{NOTE_THIN}</b> — 관측 {cases(dg['지표']['관측건수_최소'])}로 기준 "
         f"{MIN_CASES:,}건에 못 미친다. 판정과 실행 후보를 내지 않는다.")
else:
    # 판정은 모든 셀에 남긴다. 우선순위로 거르는 것은 아래 후보 목록뿐이다.
    j = dg["판정"]
    st.markdown(
        f'<div class="mr-verdict">{priority_badge(j["우선순위"])}<b>{j["라벨"]}</b>'
        f'<br><span class="mr-verdict-why">{j["설명"]}</span></div>',
        unsafe_allow_html=True,
    )

    # A의 설명문은 초과분(%p)만 말한다. 그것만 읽으면 "뒤처짐"을 "줄었다"로
    # 오해한다. 미추홀구 한식 건수는 실제로 +2.82% 늘었고, 전국이 +10.09%라
    # 뒤처진 것이다. 지역 변화율과 전국 변화율을 나란히 깔아 그 차이를 보인다.
    mi = dg["지표"]
    st.caption("**판정의 근거** — 전국과 나란히 놓은 값이다.")
    for 이름, 지역값, 초과분, 전국열 in (
        ("결제건수", mi["일평균건수_변화_pct"], mi["건수_초과분_pp"], "daily_cnt_chg_pct"),
        ("건당금액", mi["건당금액_변화_pct"], mi["건당_초과분_pp"], "unit_chg_pct"),
    ):
        # 전국값은 기준선에서 직접 읽는다. 초과분에서 역산하면 둘 다 소수점
        # 둘째 자리로 반올림된 값이라 위 병기 표와 0.01%p씩 어긋난다.
        전국값 = float(nat[전국열]) if nat is not None else 지역값 - 초과분
        움직임 = "늘었다" if 지역값 > 0 else "줄었다" if 지역값 < 0 else "그대로다"
        견줌 = "뒤처진다" if 초과분 < 0 else "앞선다"
        st.caption(f"　· **{이름}** — 이 지역 {pct(지역값)}로 {움직임}. "
                   f"전국 {pct(전국값)}와 견주면 {abs(초과분):.2f}%p {견줌}.")
    st.caption("　**뒤처진다 ≠ 줄었다.** 전국보다 덜 늘어도 뒤처진 것으로 잡힌다.")
    # 이 셀의 방향을 단정해 쓰면 안 된다. 성장 중인 지역(이천시 한식 +3.71%)에
    # "매출이 줄었고"가 그대로 나갔었다. 값을 먼저 보이고 규칙은 일반형으로 적는다.
    st.caption(f"　**우선순위** — 이 지역 일평균 결제금액은 {pct(mi['일평균금액_변화_pct'])}다. "
               "금액이 줄고 있으면서 그 원인이 전국 공통 흐름이 아닐 때만 '높음'이 되고, "
               "늘고 있으면 전국보다 부진해도 '낮음'에 그친다. "
               "매출이 늘고 있는 매장에 문제가 있다고 말하지 않기 위해서다.")

    cands = dg["실행후보"]
    if cands:
        guide = check_guide()
        # 대상 라벨은 카드가 둘 이상일 때만 뜻이 있다. 셀 원인 후보(대상 '전체')와
        # 집단 후보(외국인·법인)를 갈라 읽어야 하기 때문이다. 후보가 생기는 44칸 중
        # 39칸은 '전체' 카드 하나뿐이라, 그때 라벨은 비교 대상 없이 남는 군더더기다.
        갈라읽기 = len(cands) > 1
        for c in cands:
            # '전체'는 '모든 후보'가 아니라 '집단을 나누지 않은 지역 전체'다.
            # 화면에서 두 뜻이 헷갈려 라벨을 풀어 쓴다.
            대상 = "지역 전체" if c["대상"] == "전체" else f'{c["대상"]} 집단'
            범위 = ("집단을 나누지 않은 지역 전체" if c["대상"] == "전체"
                  else f'4~6월 금액의 {c["B기간_비중_pct"]:.2f}%를 차지하는 집단')
            if not 갈라읽기:
                대상, 범위 = "", ""

            # 항목 이름 밑에 안내 한 줄. 안내가 없는 항목은 이름만 내보낸다.
            # A가 확인 문구를 바꿨다는 신호라 숨기지 않는다.
            checks, 멈춤항목 = [], []
            for name in split_checks(c["확인"]):
                g = guide.get(name)
                if g is None:
                    checks.append(f'<li><span class="mr-check-name">{name}</span></li>')
                    continue
                if g.get("stop"):
                    멈춤항목.append(name)
                멈춤 = ('<span class="mr-check-stop">여기서 끝날 수 있음</span>'
                      if g.get("stop") else "")
                checks.append(
                    f'<li><span class="mr-check-name">{name}</span>{멈춤}'
                    f'<span class="mr-check-see">{g["안내"]}</span></li>'
                )

            items = "".join(f"<li>{x}</li>" for x in c["후보"])
            extra = f'<div class="mr-card-note">{c["비고"]}</div>' if c.get("비고") else ""
            # 셀 후보의 초과분은 음수(전국보다 부진)지만, 집단 후보는 게이트를
            # 통과한 쪽이라 양수(전국 같은 집단보다 더 늘었다)다. 부호를 보지 않고
            # abs()로 '부진'이라 쓰면 증가 신호가 부진으로 뒤집힌다.
            기준 = "전국" if c["대상"] == "전체" else "전국 같은 집단"
            초과 = c["전국_대비_초과분_pp"]
            수치 = (f'{기준}보다 {abs(초과):.2f}%p 부진' if 초과 < 0
                  else f'{기준}보다 {초과:.2f}%p 더 늘었다')
            # 라벨을 비웠을 때 ' · 전국보다 …'처럼 구분점이 앞에 남지 않게 조립한다.
            머리 = f'<b>{대상}</b>' if 대상 else ""

            # 확인과 후보를 카드 둘로 나눈다. 한 카드에 있으면 아래 목록이 확인의
            # 결과처럼 붙어 읽혀, 확인하기 전에 후보부터 고르게 된다.
            st.markdown(
                f'<div class="mr-card">'
                f'<div class="mr-card-head">{머리}'
                f'<span class="mr-card-num">{f"{범위} · " if 범위 else ""}{수치}</span></div>'
                f'<div class="mr-card-check"><b>① 먼저 확인할 것</b> — 위에서부터 순서대로 본다. '
                f'카드 데이터에는 왜 그랬는지가 없어서, 원인은 이 확인이 가른다.</div>'
                f'<ol class="mr-check-list">{"".join(checks)}</ol></div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div class="mr-card mr-card-next">'
                f'<div class="mr-card-check"><b>② 확인한 뒤 고를 후보</b>'
                f'{f" · {대상}" if 대상 else ""} — 순위가 아니다. 위 ①에서 짚인 쪽을 고른다.'
                # 멈춤 항목이 없는 카드(집단 후보 등)에 이 문장을 붙이면 거짓말이 된다.
                f'{f" ①에서 {chr(183).join(멈춤항목)} 쪽이 원인이면 여기까지 오지 않는다." if 멈춤항목 else ""}</div>'
                f'<ul class="mr-card-list">{items}</ul>{extra}</div>',
                unsafe_allow_html=True,
            )
        tail = ("후보에는 순위도 손익 계산도 없다. **화면 2**에서 매장 숫자를 넣으면 "
                "이 후보들이 대안으로 바뀌고 필요 판매량 순으로 정렬된다.")
        if len(cands) > 1:
            tail = "카드는 겨냥하는 대상별로 나뉜다. **금액 비중이 큰 쪽부터** 확인한다. " + tail
        st.caption(tail)
    elif dg["참고"]:
        # 우선순위 '낮음'. 후보 대신 이 한 줄만 나간다.
        note(dg["참고"])
    # 후보도 참고도 없으면 아무것도 그리지 않는다. 빈 목록을 "문제 없음"으로
    # 바꿔 쓰지 않는다 (계약 4절). '게이트' 문자열은 개발용이라 노출하지 않는다.

footer()
