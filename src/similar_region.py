"""인구·초기 소비 기준 유사 지역 매칭 — C 담당 (단계 3).

매칭 변수 5개를 표준화한 뒤 유클리드 거리로 최근접 k곳을 고른다.

    총인구(log) · 20~30대 비율 · 60대 이상 비율
    A기간 일평균 금액(log) · A기간 건당금액(log)

규칙 두 가지를 어기지 않는다.

1. **B기간 결과 변수를 넣지 않는다.** 넣으면 "비슷한 변화를 보인 지역"을
   고르게 되어, 그 지역들과 비교해 변화를 설명하는 순환 논리가 된다.
2. **업종별로 따로 계산한다.** 한식과 서양음식은 객단가가 3배 차이 난다.

터미널 검증:
    python -m src.similar_region
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from src.load import BUZ_KOREAN, BUZ_WESTERN, aggregate, load_card

POP_CSV = "out/population_2026m1.csv"
OUT_CSV = "out/similar_regions.csv"
FEAT_CSV = "out/match_features.csv"

BUZ_NAME = {BUZ_KOREAN: "일반한식", BUZ_WESTERN: "서양음식"}

POP_FEATURES = ["log_pop", "ratio_20_39", "ratio_60_plus"]
CONS_FEATURES = ["log_daily_amt_A", "log_unit_A"]
FEATURES = POP_FEATURES + CONS_FEATURES

K_DEFAULT = 5
OUTLIER_PCT = 90.0

# "유사 지역 없음"은 두 가지 이유로 뜬다. 원인이 다르므로 따로 계산해 따로 표시한다.
#
#  A. 비교 대상 희소 (sparse)
#     5개 변수 전체 거리 기준 최근접 k곳의 평균 거리가 전국 상위 10%.
#     울릉군·화천군처럼 인구도 소비도 전국 분포에서 외따로 떨어진 지역이 걸린다.
#
#  B. 소비 성격 이례 (atypical) — 유입형 상권 탐지
#     인구 변수 3개로만 최근접 k곳을 고른 뒤, 그 이웃들과의 *소비 변수* 거리를 잰다.
#     주민 구성이 닮았는데 소비 규모가 딴판이면 외부 유입으로 소비가 만들어진 것이다.
#     1인당 소비 환산(계약 6-4 금지)을 쓰지 않고 유입형을 잡기 위한 우회로다.
#
# A만으로는 유입형이 안 걸린다. 강남구는 인구 프로필이 평범해서(55.6만, 연령 구성 중간)
# 인구 변수 3개가 거리를 지배하고 소비 규모 하나만 튀는 것이 5변수 평균에 희석된다.

_cache: dict[str, pd.DataFrame] = {}


def build_features(buz: str, df=None) -> pd.DataFrame:
    """업종 하나에 대한 매칭 변수표. index=region_key.

    A기간 관측이 없는 지역은 제외하고 reason에 남긴다.
    """
    if df is None:
        df = load_card()
    card = aggregate(df, buz=buz, group_by="region_key")
    pop = pd.read_csv(POP_CSV, encoding="utf-8-sig")

    f = pop[["region_key", "pop_total", "ratio_20_39", "ratio_60_plus"]].merge(
        card[["region_key", "daily_amt_A", "unit_A", "share_B_pct"]], on="region_key", how="left"
    )

    # A기간 금액이 0이면 log를 못 쓴다. 관측량 부족으로 빼고 이유를 남긴다.
    f["usable"] = (f["daily_amt_A"] > 0) & (f["unit_A"] > 0) & f["daily_amt_A"].notna()
    f["log_pop"] = np.log(f["pop_total"])
    f["log_daily_amt_A"] = np.log(f["daily_amt_A"].where(f["usable"]))
    f["log_unit_A"] = np.log(f["unit_A"].where(f["usable"]))
    return f.set_index("region_key")


def _dist(z: pd.DataFrame, cols: list[str]) -> np.ndarray:
    """표준화된 변수표에서 유클리드 거리 행렬. 대각선은 inf(자기 자신은 이웃이 아니다)."""
    X = z[cols].to_numpy()
    d = np.sqrt(np.maximum(((X[:, None, :] - X[None, :, :]) ** 2).sum(axis=2), 0))
    np.fill_diagonal(d, np.inf)
    return d


def _matrix(buz: str, df=None):
    """표준화 변수표와 거리 행렬 3종(전체·인구·소비). 업종별로 캐시한다."""
    if buz in _cache:
        return _cache[buz]
    f = build_features(buz, df)
    use = f[f["usable"]]
    z = (use[FEATURES] - use[FEATURES].mean()) / use[FEATURES].std(ddof=0)
    _cache[buz] = (use, z, _dist(z, FEATURES), _dist(z, POP_FEATURES), _dist(z, CONS_FEATURES))
    return _cache[buz]


def flags(buz: str, k: int = K_DEFAULT, df=None) -> pd.DataFrame:
    """지역별 경고 판정표. index=region_key.

    반환 열: mean_dist, cutoff_dist, sparse, cons_gap, cutoff_gap, atypical,
             has_similar, note
    """
    use, _, dist, dist_pop, dist_cons = _matrix(buz, df)

    nd = np.sort(dist, axis=1)[:, :k]
    mean_dist = nd.mean(axis=1)
    cutoff_dist = float(np.percentile(mean_dist, OUTLIER_PCT))

    pop_idx = np.argsort(dist_pop, axis=1)[:, :k]
    cons_gap = np.take_along_axis(dist_cons, pop_idx, axis=1).mean(axis=1)
    cutoff_gap = float(np.percentile(cons_gap, OUTLIER_PCT))

    out = pd.DataFrame({
        "mean_dist": mean_dist.round(4),
        "cutoff_dist": round(cutoff_dist, 4),
        "sparse": mean_dist > cutoff_dist,
        "cons_gap": cons_gap.round(4),
        "cutoff_gap": round(cutoff_gap, 4),
        "atypical": cons_gap > cutoff_gap,
    }, index=use.index)
    out["has_similar"] = ~(out["sparse"] | out["atypical"])

    def note(r):
        if r["sparse"] and r["atypical"]:
            return "유사 지역 없음 — 비교 대상이 희소하고 소비 성격도 이례적"
        if r["sparse"]:
            return "유사 지역 없음 — 인구·소비 조건이 비슷한 지역이 드물다"
        if r["atypical"]:
            return "참고 — 주민 구성이 비슷한 지역보다 소비 규모가 크게 다르다(유입 가능성)"
        return ""

    out["note"] = out.apply(note, axis=1)
    return out


def _resolve(region: str, pool: pd.Index, sido: str | None) -> str:
    """'미추홀구' 또는 '인천광역시 미추홀구'를 region_key로 바꾼다.

    시군구명만으로 여러 시도에 걸리면 ValueError. 계약 6-6과 같은 규칙이다.
    """
    if region in pool:
        return region
    if sido:
        key = f"{sido} {region}"
        if key in pool:
            return key
        raise ValueError(f"'{key}'가 관측 지역에 없다.")
    hits = [k for k in pool if k.split(" ", 1)[1] == region]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ValueError(
            f"'{region}'은 {len(hits)}개 시도에 있다: {[h.split()[0] for h in hits]}. sido를 지정한다."
        )
    raise ValueError(f"'{region}'을 찾지 못했다. region_key는 '시도 시군구' 형식이다.")


def find_similar(region: str, buz: str, k: int = K_DEFAULT, *, sido: str | None = None,
                 df=None) -> pd.DataFrame:
    """인구·초기 소비 기준 유사 지역 k곳과 거리를 반환. 업종별로 따로 계산한다.

    반환 열: rank, neighbor_key, distance, has_similar, mean_dist, cutoff
      has_similar=False 이면 유입형 상권 등으로 비교 대상이 마땅치 않다는 뜻이다.
    """
    use, _, dist, _, _ = _matrix(buz, df)
    key = _resolve(region, use.index, sido)
    i = use.index.get_loc(key)

    order = np.argsort(dist[i])[:k]
    fl = flags(buz, k, df).loc[key]

    out = pd.DataFrame({
        "region_key": key,
        "buz": buz,
        "buz_nm": BUZ_NAME.get(buz, buz),
        "rank": np.arange(1, len(order) + 1),
        "neighbor_key": use.index[order],
        "distance": np.round(dist[i][order], 4),
    })
    for c in ["mean_dist", "cutoff_dist", "sparse", "cons_gap", "cutoff_gap",
              "atypical", "has_similar", "note"]:
        out[c] = fl[c]
    return out


def build(k: int = K_DEFAULT, out_path: str = OUT_CSV, df=None) -> pd.DataFrame:
    """255지역 × 2업종 × k곳을 out/similar_regions.csv로 저장."""
    if df is None:
        df = load_card()
    frames = []
    for buz in (BUZ_KOREAN, BUZ_WESTERN):
        use, _, dist, _, _ = _matrix(buz, df)
        fl = flags(buz, k, df)
        idx = np.argsort(dist, axis=1)[:, :k]
        nd = np.take_along_axis(dist, idx, axis=1)
        for r, key in enumerate(use.index):
            blk = pd.DataFrame({
                "region_key": key,
                "buz": buz,
                "buz_nm": BUZ_NAME[buz],
                "rank": np.arange(1, k + 1),
                "neighbor_key": use.index[idx[r]],
                "distance": np.round(nd[r], 4),
            })
            for c in fl.columns:
                blk[c] = fl.loc[key, c]
            frames.append(blk)

        # 관측량 부족으로 빠진 지역도 기록에 남긴다. 화면에서 빈칸이 되지 않게.
        f = build_features(buz, df)
        for key in f.index[~f["usable"]]:
            frames.append(pd.DataFrame({
                "region_key": [key], "buz": [buz], "buz_nm": [BUZ_NAME[buz]],
                "rank": [0], "neighbor_key": [None], "distance": [np.nan],
                "mean_dist": [np.nan], "cutoff_dist": [np.nan], "sparse": [True],
                "cons_gap": [np.nan], "cutoff_gap": [np.nan], "atypical": [False],
                "has_similar": [False], "note": ["관측량 부족 — 유사 지역 비교 불가"],
            }))

    out = pd.concat(frames, ignore_index=True).sort_values(
        ["buz", "region_key", "rank"]).reset_index(drop=True)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")

    # 화면에서 "무엇이 닮았는지" 보여주려면 매칭 변수 원값이 필요하다.
    # 따로 저장해 두면 화면이 16MB 카드 원본 없이도 뜬다.
    feats = []
    for buz in (BUZ_KOREAN, BUZ_WESTERN):
        f = build_features(buz, df).reset_index()
        f["buz"] = buz
        f["buz_nm"] = BUZ_NAME[buz]
        feats.append(f[["region_key", "buz", "buz_nm", "pop_total", "ratio_20_39",
                        "ratio_60_plus", "daily_amt_A", "unit_A", "usable"]])
    pd.concat(feats, ignore_index=True).round(2).to_csv(
        FEAT_CSV, index=False, encoding="utf-8-sig")
    return out


def self_check() -> bool:
    ok = True

    def chk(label, cond, detail=""):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"  {'OK  ' if cond else 'FAIL'}  {label}{('   ' + detail) if detail else ''}")

    df = load_card()

    print("[1] 변수 구성")
    for buz in (BUZ_KOREAN, BUZ_WESTERN):
        f = build_features(buz, df)
        chk(f"{BUZ_NAME[buz]} 255지역", len(f) == 255, f"사용가능 {int(f['usable'].sum())}곳")
    chk("B기간 변수 미포함", not any("_B" in c for c in FEATURES), str(FEATURES))

    print("[2] 업종별 분리")
    ko = find_similar("미추홀구", BUZ_KOREAN, df=df)["neighbor_key"].tolist()
    we = find_similar("미추홀구", BUZ_WESTERN, df=df)["neighbor_key"].tolist()
    chk("한식/서양음식 결과가 다르다", ko != we)

    print("[3] 안전장치")
    try:
        find_similar("중구", BUZ_KOREAN, df=df); chk("region='중구' -> ValueError", False)
    except ValueError:
        chk("region='중구' -> ValueError", True)
    r = find_similar("중구", BUZ_KOREAN, sido="서울특별시", df=df)
    chk("sido 지정 시 동작", len(r) == 5, r["region_key"].iloc[0])

    print("[4] 예외 판정")
    for buz in (BUZ_KOREAN, BUZ_WESTERN):
        fl = flags(buz, df=df)
        n_s, n_a = int(fl["sparse"].sum()), int(fl["atypical"].sum())
        chk(f"{BUZ_NAME[buz]} 희소 판정 ~10%", 20 <= n_s <= 31, f"{n_s}곳 / 255")
        chk(f"{BUZ_NAME[buz]} 이례 판정 ~10%", 20 <= n_a <= 31, f"{n_a}곳 / 255")
    for name, sido, buz in [("강남구", "서울특별시", BUZ_WESTERN),
                            ("종로구", "서울특별시", BUZ_WESTERN)]:
        r = find_similar(name, buz, sido=sido, df=df)
        chk(f"{name} {BUZ_NAME[buz]} 유사 지역 없음", not r["has_similar"].iloc[0],
            f"소비괴리 {r['cons_gap'].iloc[0]} vs 기준 {r['cutoff_gap'].iloc[0]}")
    for name, sido, buz in [("강남구", "서울특별시", BUZ_KOREAN)]:
        r = find_similar(name, buz, sido=sido, df=df)
        print(f"  INFO  {name} {BUZ_NAME[buz]}: has_similar={r['has_similar'].iloc[0]} "
              f"(소비괴리 {r['cons_gap'].iloc[0]} vs 기준 {r['cutoff_gap'].iloc[0]}) "
              f"— 한식 소비는 전국적으로 인구를 따라가 유입형이 드러나지 않는다")

    print("[5] 산출물")
    out = build(df=df)
    n = (out["rank"] > 0).sum()
    chk("similar_regions.csv 행수", n == len(out[out['rank'] > 0]), f"이웃행 {n}, 전체 {len(out)}")
    chk("업종 2종", set(out["buz"]) == {BUZ_KOREAN, BUZ_WESTERN})
    chk("자기 자신이 이웃에 없다", (out["region_key"] != out["neighbor_key"]).all())

    print("[6] 눈으로 확인 — 미추홀구 한식 유사 지역 5곳")
    pop = pd.read_csv(POP_CSV, encoding="utf-8-sig").set_index("region_key")
    r = find_similar("미추홀구", BUZ_KOREAN, df=df)
    base = pop.loc[r["region_key"].iloc[0]]
    print(f"    기준: {r['region_key'].iloc[0]:22s} 인구 {int(base.pop_total):>9,} "
          f"20~30대 {base.ratio_20_39:5.2f}% 60대+ {base.ratio_60_plus:5.2f}%")
    for t in r.itertuples():
        p = pop.loc[t.neighbor_key]
        print(f"    {t.rank}. {t.neighbor_key:22s} 인구 {int(p.pop_total):>9,} "
              f"20~30대 {p.ratio_20_39:5.2f}% 60대+ {p.ratio_60_plus:5.2f}%  거리 {t.distance}")

    print("\n=== " + ("전부 통과" if ok else "실패 있음") + " ===")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if self_check() else 1)
