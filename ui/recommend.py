"""지역 진단 후보를 손익 조건으로 비교하는 추천 정책.

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
    for field in ("candidate_kinds", "candidate_actions", "ranking", "display"):
        if not policy.get(field):
            raise ValueError(f"{path}에 {field}가 없습니다.")

    kinds = set(yaml.safe_load(OPTIONS_PATH.read_text(encoding="utf-8"))["types"])
    unknown = sorted(set(policy["candidate_kinds"].values()) - kinds)
    if unknown:
        raise ValueError(
            f"recommend.yaml이 options.yaml에 없는 대안 구분을 가리킵니다: {unknown}"
        )
    missing_actions = sorted(set(policy["candidate_kinds"]) - set(policy["candidate_actions"]))
    if missing_actions:
        raise ValueError(f"recommend.yaml에 실행안이 없는 후보: {missing_actions}")
    for name, action in policy["candidate_actions"].items():
        if action.get("base_option") not in {"discount", "redesign", "visibility", "ordering"}:
            raise ValueError(f"{name}: base_option이 올바르지 않습니다")
        if not all(action.get(field) for field in ("title", "action", "measure", "precheck")):
            raise ValueError(f"{name}: 실행안 설명이 부족합니다")
        if not isinstance(action.get("assumptions", {}), dict):
            raise ValueError(f"{name}: assumptions는 항목 묶음이어야 합니다")
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


def action_specs(dg: dict | None, policy: dict | None = None) -> list[dict]:
    """Turn screen-1 candidate wording into concrete, calculable action cards."""
    policy = policy or load_policy()
    if shortlist(dg, policy)["state"] != "filtered":
        return []
    specs, seen = [], set()
    for card in dg.get("실행후보", []):
        for candidate in card.get("후보", []):
            if candidate in seen or candidate not in policy["candidate_actions"]:
                continue
            seen.add(candidate)
            action = dict(policy["candidate_actions"][candidate])
            specs.append({"id": f"candidate_{len(specs) + 1}", "candidate": candidate,
                          "kind": policy["candidate_kinds"][candidate], **action})
    return specs


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
        row["실행"] = option.get("action", "")
        row["확인할 숫자"] = option.get("measure", "")
        row["실행 전 확인"] = option.get("precheck", "")
        row["기본 가정"] = option.get("assumptions", {})
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
    """역할을 손익 비교로 한정한 결과 화면."""
    import streamlit as st

    if result is None:
        return None
    policy = load_policy()
    picked = shortlist(dg, policy)
    if picked["state"] == "empty":
        st.info(policy["display"]["no_candidate"])
        return {"ranked": [], "excluded": [], "rows": [], "tops": {}, "unstable": False}

    outcome = rank(result, picked["kinds"], policy)
    ranked = outcome["ranked"]
    menus = {menu["id"]: menu for menu in result["store"]["menus"]}

    if ranked:
        top = ranked[0]
        extra = (None if top["required_daily_volume"] is None else
                 top["required_daily_volume"] - menus[top["target_menu"]]["daily_volume"])
        reason = (f"현재 판매량을 100으로 보면 {top['required_index']:,.0f}까지 늘어야 현재 이익을 유지할 수 있습니다."
                  if extra is None and top["required_index"] is not None
                  else "판매량을 입력하면 하루에 더 팔아야 하는 수량을 계산할 수 있습니다."
                  if extra is None
                  else f"현재 이익을 유지하려면 하루 약 {extra:,.1f}건을 더 팔아야 하며, 비교한 실행안 중 부담이 가장 작습니다.")
        st.success(f'우선 검토 실행안 · {top["alternative"]}\n\n{reason}')
    else:
        st.info("현재 이익을 유지하는 조건을 계산할 수 있는 실행안이 없습니다.")

    if outcome["unstable"]:
        st.warning("재료비에 따라 우선순위가 달라집니다. 실제 원가를 먼저 확인해 주세요.")
    else:
        st.caption("재료비를 낮음·기준·높음으로 바꿔도 첫 번째 실행안은 같습니다.")

    st.markdown("**실행안별 핵심 결과**")
    st.caption("공헌이익은 판매가격에서 재료비·포장비·수수료·변동 인건비를 뺀 금액이며 순이익과 다릅니다.")
    st.dataframe([{
        "순위": row["순위"],
        "실행안": row["alternative"],
        "더 팔아야 하는 비율(%)": None if row["increase_pct"] is None else round(row["increase_pct"], 1),
        "하루에 더 팔아야 하는 수량": (None if row["required_daily_volume"] is None else round(
            row["required_daily_volume"] - menus[row["target_menu"]]["daily_volume"], 1)),
        "현재 판매량을 100으로 봤을 때": row["required_index"],
    } for row in ranked], hide_index=True, width="stretch")
    st.caption("이 순위는 현재 이익을 유지하기 위해 얼마나 더 팔아야 하는지를 비교한 결과이며 실제 판매 성과를 예측하지 않습니다.")

    with st.expander("상세 계산값과 입력 조건 보기"):
        st.dataframe([{
            "실행안": row["alternative"], "현재 공헌이익": row["base_store_cm"],
            "판매량이 같을 때 공헌이익": row["after_store_cm_after_setup"],
            "차이": None if row["base_store_cm"] is None else row["after_store_cm_after_setup"] - row["base_store_cm"],
        } for row in ranked], hide_index=True, width="stretch")
        labels = {"price_delta": "판매가격 증감", "food_cost_delta": "재료비 증감",
                  "application_rate": "적용 비율", "setup_cost": "초기 비용",
                  "extra_minutes": "추가 시간", "extra_labor_cost": "추가 인건비"}
        for row in ranked:
            assumptions = row.get("기본 가정", {})
            text = " · ".join(f"{labels.get(k, k)} {v}" for k, v in assumptions.items()) or "별도 변경값 없음"
            st.caption(f'{row["alternative"]} · {text}')

    assumptions = []
    if any(menu.get("daily_volume") is None for menu in result["store"]["menus"]):
        assumptions.append("판매량 미입력: 대상 메뉴 지수 100 기준이며 도입비·잠식·매장 합계는 제외")
    for menu in result["store"]["menus"]:
        if menu.get("public_price_ingredients"):
            assumptions.append(f'{menu["name"]} 공개가격 적용: ' + ", ".join(menu["public_price_ingredients"]))
        for label in menu.get("assumed_zero_fields", ()):
            assumptions.append(f'{menu["name"]} {label} 미입력: 0원 가정')
        if "가정값" in menu.get("tags", {}).values():
            assumptions.append(f'{menu["name"]} 원가 모름: 기본 원가율 35%로 참고 계산')
    st.markdown("**계산 전에 확인할 내용**")
    if assumptions:
        for line in dict.fromkeys(assumptions):
            st.caption("- " + line)
    else:
        st.caption("- 미입력으로 0원 처리한 항목이 없습니다.")
    for row in outcome["excluded"]:
        st.caption(f'비교 제외 · {row["alternative"]}: {row["제외사유"]}')
    return outcome
