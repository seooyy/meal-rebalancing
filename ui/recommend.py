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

    st.subheader("후보별 공헌이익 비교")
    st.caption("공헌이익은 판매가에서 식재료비·포장비·수수료·변동 인건비를 뺀 금액입니다. 순이익은 아닙니다.")
    st.dataframe([{
        "후보": row["alternative"],
        "현재 공헌이익": row["base_store_cm"],
        "실행 후 공헌이익": row["after_store_cm_after_setup"],
        "차이": (None if row["base_store_cm"] is None else
                row["after_store_cm_after_setup"] - row["base_store_cm"]),
        "손익 유지에 필요한 하루 추가 판매": (None if row["required_daily_volume"] is None else round(
            row["required_daily_volume"] - menus[row["target_menu"]]["daily_volume"], 1)),
    } for row in ranked], hide_index=True, width="stretch")
    st.caption("후보 기본 가정으로 계산했습니다. 실제 할인액·도입비·추가 원가가 다르면 결과가 달라집니다.")

    if ranked:
        top = ranked[0]
        st.markdown(f'**1순위 후보: {top["alternative"]}**')
        extra = (None if top["required_daily_volume"] is None else
                 top["required_daily_volume"] - menus[top["target_menu"]]["daily_volume"])
        reason = ("판매량을 정확히 입력하면 하루 추가 판매 부담을 계산할 수 있습니다."
                  if extra is None else f"현재 공헌이익을 유지하는 데 필요한 하루 추가 판매가 약 {extra:,.1f}건으로 가장 적습니다.")
        st.write("1순위 이유: " + reason)
    else:
        st.info("손익 유지 조건을 계산할 수 있는 후보가 없습니다.")

    if outcome["unstable"]:
        st.warning("원가가 달라지면 1순위가 바뀝니다. 실제 원가를 먼저 확인하세요.")
    else:
        st.caption("원가의 낮음·기준·높음 범위에서 1순위가 바뀌지 않았습니다.")

    with st.expander("후보 계산에 사용한 기본 가정"):
        labels = {"price_delta": "판매가 변화", "food_cost_delta": "추가 원가",
                  "application_rate": "적용 비율", "setup_cost": "도입비",
                  "extra_minutes": "추가 시간", "extra_labor_cost": "추가 인건비"}
        for row in ranked:
            assumptions = row.get("기본 가정", {})
            text = " · ".join(f"{labels.get(k, k)} {v}" for k, v in assumptions.items()) or "별도 변경값 없음"
            st.caption(f'{row["alternative"]}: {text}')

    assumptions = []
    for menu in result["store"]["menus"]:
        for label in menu.get("assumed_zero_fields", ()):
            assumptions.append(f'{menu["name"]} {label} 미입력: 0원 가정')
        if "가정값" in menu.get("tags", {}).values():
            assumptions.append(f'{menu["name"]} 원가 모름: 기본 원가율 35%로 참고 계산')
    st.markdown("**미입력·가정값 목록**")
    if assumptions:
        for line in dict.fromkeys(assumptions):
            st.caption("- " + line)
    else:
        st.caption("- 미입력으로 0원 처리한 항목이 없습니다.")
    for row in outcome["excluded"]:
        st.caption(f'계산 제외 · {row["alternative"]}: {row["제외사유"]}')
    st.caption("추천은 현재 입력값과 후보 기본 가정에서 공헌이익 부담이 가장 작은 실행안입니다. 성공 가능성의 순위가 아닙니다.")
    return outcome

