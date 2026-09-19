"""대안 추천 — C 소유.

기획서 6절의 2단계 추천이다.

  1단계 (진단 규칙) : 화면 1의 실행 후보가 가리키는 대안 구분만 남긴다.
  2단계 (계산 결과) : 남은 대안을 **같은 조건으로 다시 계산해** 필요 증가율로 세운다.

1단계가 먼저인 이유는 계산만으로 세우면 지역 진단과 무관한 대안이 1순위가 되기
때문이다. 객단가가 빠진 지역에서 할인안이 상위에 오르는 것이 대표적이다.

**남의 파일은 고치지 않는다** (config/contract.md 3절).
A의 `src/diagnose.py`·`config/rules.yaml`과 B의 `src/simulator.py`·`config/options.yaml`은
읽기만 한다. 후보 문자열을 대안 구분에 잇는 표는 C가 소유하는 `config/recommend.yaml`에 있다.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.simulator import COST_LEVELS, alternative_from_dict, menu_from_dict, simulate

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "config" / "recommend.yaml"
OPTIONS_PATH = ROOT / "config" / "options.yaml"

LEVEL_NAMES = {"low": "낮음", "base": "기준", "high": "높음"}


# ---- 정책 -------------------------------------------------------------------

_policy_cache: dict[str, dict] = {}


def load_policy(path: str | Path = POLICY_PATH) -> dict:
    """config/recommend.yaml을 읽고 B의 대안 구분과 대조한다.

    표의 오른쪽 값이 options.yaml의 types에 없으면 그 후보는 어떤 대안에도
    걸리지 않는다. 화면에는 "추천할 대안 없음"으로만 보여서 원인을 찾기 어렵다.
    여기서 먼저 막는다.
    """
    key = str(path)
    if key in _policy_cache:
        return _policy_cache[key]

    policy = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for field in ("candidate_kinds", "ranking", "display"):
        if not policy.get(field):
            raise ValueError(f"{path}에 {field}가 없습니다.")

    kinds = set(yaml.safe_load(OPTIONS_PATH.read_text(encoding="utf-8"))["types"])
    unknown = sorted(set(policy["candidate_kinds"].values()) - kinds)
    if unknown:
        raise ValueError(
            f"recommend.yaml이 options.yaml에 없는 대안 구분을 가리킵니다: {unknown}"
        )
    _policy_cache[key] = policy
    return policy


# ---- 1단계: 진단 후보 -> 대안 구분 -------------------------------------------

def shortlist(dg: dict | None, policy: dict | None = None) -> dict:
    """화면 1의 진단으로 추천 대상을 좁힌다.

    Returns
    -------
    dict
        state   : 'filtered' 진단이 후보를 지목함 / 'empty' 진단은 됐지만 후보 없음 /
                  'unfiltered' 진단을 쓸 수 없음
        kinds   : 허용할 대안 구분 -> 근거 문자열 목록. state='unfiltered'면 None(필터 없음)
        unknown : recommend.yaml에 없는 후보 문자열. 화면에 그대로 표시한다
        notes   : 화면에 쓸 사유
    """
    policy = policy or load_policy()
    table = policy["candidate_kinds"]

    if dg is None:
        return {"state": "unfiltered", "kinds": None, "unknown": [],
                "notes": ["이 지역·업종은 진단할 수 없습니다."]}
    if dg.get("관측량부족"):
        return {"state": "unfiltered", "kinds": None, "unknown": [],
                "notes": ["관측량 부족 — 진단을 추천 근거로 쓰지 않습니다."]}

    kinds: dict[str, list[str]] = {}
    unknown: list[str] = []
    for candidate in dg.get("실행후보", []):
        for name in candidate["후보"]:
            kind = table.get(name)
            if kind is None:
                unknown.append(name)
                continue
            kinds.setdefault(kind, []).append(f'{candidate["대상"]} · {name}')

    if not kinds:
        # 후보가 비었으면 '문제 없음'이 아니라 '지역 고유 후보가 없음'이다.
        # 게이트 사유를 함께 넘겨 왜 비었는지 보이게 한다 (contract 4절).
        return {"state": "empty", "kinds": {}, "unknown": sorted(set(unknown)),
                "notes": list(dg.get("게이트", []))}

    judge = dg.get("판정", {})
    notes = [f'진단 {judge.get("라벨", "")} (원인 {judge.get("원인", "")}) 기준입니다.']
    return {"state": "filtered", "kinds": kinds, "unknown": sorted(set(unknown)), "notes": notes}


# ---- 2단계: 계산 결과 순위 ---------------------------------------------------

def rows_for_all(result: dict) -> list[dict]:
    """네 대안을 **같은 대상 메뉴·같은 잠식률**로 다시 계산한다.

    B의 화면은 선택한 대안 외에 세 개만 계산하고, 선택하지 않은 대안은 설정 파일의
    기본 대상 메뉴를 쓴다. 대상 메뉴가 서로 다르면 순위가 대안이 아니라 메뉴를
    비교한 결과가 되므로, 추천은 현재 선택한 조건으로 전부 다시 계산한다.
    """
    store = result["store"]
    menus = [menu_from_dict(m) for m in store["menus"]]
    active = result["active"]
    costs = result["prices"]["food_costs"] if result.get("prices") else None

    rows = []
    for option in result["options"]:
        option = dict(option)
        option["target_menu"] = active["target_menu"]
        option["cannibalization"] = dict(active.get("cannibalization") or {})
        rows.extend(simulate(
            menus, alternative_from_dict(option),
            operating_days=store["operating_days"], period_weeks=store["period_weeks"],
            scenario_food_costs=costs,
        ))
    return rows


def rank(result: dict, kinds: dict | None = None, policy: dict | None = None) -> dict:
    """필요 증가율 오름차순. 낮을수록 달성 조건이 가볍다.

    달성 조건을 계산할 수 없는 대안(건당 공헌이익 0 이하, 기존 판매량 0)은 순위에서
    빼고 사유와 함께 따로 돌려준다. 순위 안에 섞으면 '최하위'로 읽힌다.
    """
    policy = policy or load_policy()
    ranking = policy["ranking"]
    level = ranking["level"]
    meta = {o["id"]: o for o in result["options"]}

    def allowed(row):
        return kinds is None or meta[row["alternative_id"]]["kind"] in kinds

    def key(row):
        return (row[ranking["metric"]], *(row[t] for t in ranking["tie_breakers"]), row["alternative"])

    rows = rows_for_all(result)
    for row in rows:
        option = meta[row["alternative_id"]]
        row["kind"] = option["kind"]
        row["근거"] = (kinds or {}).get(row["kind"], [])
        # 판매가격·식재료비를 건드리지 않는 대안은 건당 공헌이익이 그대로다.
        # 필요 증가율에 도입비용만 남아 구조적으로 상위에 오른다. 계산이 유리하다고
        # 읽히면 안 되므로 화면이 이 사실을 말해야 한다.
        row["가격변경없음"] = not (option.get("price_delta") or option.get("food_cost_delta"))

    pool = [r for r in rows if r["cost_level"] == level and allowed(r)]
    ranked = sorted([r for r in pool if r[ranking["metric"]] is not None], key=key)
    for index, row in enumerate(ranked, start=1):
        row["순위"] = index

    excluded = []
    for row in (r for r in pool if r[ranking["metric"]] is None):
        row["제외사유"] = (row["status"] if row["required_volume"] is None and row["required_index"] is None
                        else "기존 판매량 0 — 증가율을 비교할 수 없습니다")
        excluded.append(row)

    # 낮음·기준·높음에서 1순위가 서로 다르면 원가 확인이 먼저다.
    tops = {}
    for lv in COST_LEVELS:
        candidates = sorted([r for r in rows if r["cost_level"] == lv and allowed(r)
                             and r[ranking["metric"]] is not None], key=key)
        tops[lv] = candidates[0]["alternative_id"] if candidates else None
    unstable = len({v for v in tops.values() if v is not None}) > 1

    return {"ranked": ranked, "excluded": excluded, "rows": rows,
            "tops": tops, "unstable": unstable, "level": level}


# ---- 화면 -------------------------------------------------------------------

def render(result: dict | None, dg: dict | None) -> dict | None:
    """화면 2의 계산 결과 아래에 추천을 그린다. 계산이 실패했으면 아무것도 그리지 않는다."""
    import streamlit as st

    if result is None:
        return None

    policy = load_policy()
    display = policy["display"]
    picked = shortlist(dg, policy)
    outcome = rank(result, picked["kinds"], policy)

    st.subheader("대안 추천")

    # --- 1단계 -----------------------------------------------------------
    if picked["state"] == "filtered":
        st.caption("1단계 · 지역 진단이 지목한 대안 구분만 남겼습니다.")
        for kind, why in picked["kinds"].items():
            st.caption(f"　{kind} ← {' / '.join(why)}")
    elif picked["state"] == "empty":
        st.info(display["no_candidate"])
        for line in picked["notes"]:
            st.caption(f"　{line}")
        st.caption("계산 자체는 위 표에서 그대로 확인할 수 있습니다.")
        return outcome
    else:
        st.warning(display["no_diagnosis"])
        for line in picked["notes"]:
            st.caption(f"　{line}")

    if picked["unknown"]:
        st.caption("연결되지 않은 후보 (config/recommend.yaml에 없음): "
                   + ", ".join(picked["unknown"]))

    # --- 2단계 -----------------------------------------------------------
    ranked = outcome["ranked"]
    if not ranked:
        st.info("남은 대안 중 달성 조건을 계산할 수 있는 것이 없습니다.")
    else:
        top = ranked[0]
        label = "1순위" if picked["state"] == "filtered" else "계산상 가장 가벼움"
        st.markdown(
            f'**{label} — {top["alternative"]}** ({top["kind"]}) · '
            f'필요 증가율 {top["increase_pct"]:+.1f}% · 원가 범위 {LEVEL_NAMES[outcome["level"]]}'
        )
        if top["가격변경없음"]:
            st.caption("이 대안은 판매가격·식재료비를 바꾸지 않아 필요 증가율에 도입비용만 반영됩니다. "
                       "건당 공헌이익이 그대로라 계산상 유리하게 나오며, 실제 효과는 고객 반응으로 확인해야 합니다.")
        st.dataframe([{
            "순위": r["순위"], "대안": r["alternative"], "구분": r["kind"],
            "건당 공헌이익": r["unit_cm"], "필요 증가율 %": r["increase_pct"],
            "기간 필요 판매량": r["required_volume"],
            "판매량 미상 시 필요 지수": r["required_index"],
            "총 도입비": r["setup_cost"], "추가 조리시간 분": r["extra_minutes"],
            "진단 근거": " / ".join(r["근거"]) or "—",
        } for r in ranked], hide_index=True)

    if outcome["unstable"]:
        st.warning(display["unstable"])
        st.caption("원가별 1순위 — " + ", ".join(
            f'{LEVEL_NAMES[lv]}: {next((r["alternative"] for r in outcome["rows"] if r["alternative_id"] == aid), "—")}'
            for lv, aid in outcome["tops"].items() if aid))

    for row in outcome["excluded"]:
        st.caption(f'제외 · {row["alternative"]} — {row["제외사유"]}')

    if picked["state"] == "filtered":
        skipped = [o["name"] for o in result["options"] if o["kind"] not in picked["kinds"]]
        if skipped:
            st.caption("진단과 연결되지 않아 추천에서 제외: " + ", ".join(skipped)
                       + " — 계산 자체는 위 표에서 확인할 수 있습니다.")

    st.caption(display["notice"] + ". 실제 도입 여부는 고객 반응과 주방 수용량을 함께 확인해 결정합니다.")
    return outcome
