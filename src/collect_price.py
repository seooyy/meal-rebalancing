"""Resumable public price collection; raw source files are never modified."""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import requests
from dotenv import load_dotenv

from src.simulator import number

ENDPOINT = "https://apis.data.go.kr/B552845/perDay/price"
ROOT = Path(__file__).resolve().parent.parent
KEY_FIELDS = ("se_cd", "ctgry_cd", "item_cd", "vrty_cd", "grd_cd")
DAILY_FIELDS = ["ingredient_id", "date", *KEY_FIELDS, "sgg_cd", "mrkt_cd", "unit", "unit_sz", "recipe_unit", "unit_price", "source"]


class PriceError(RuntimeError):
    """Safe error: deliberately excludes request URL, parameters and service key."""


class AuthenticationError(PriceError):
    pass


def read_mapping(path=ROOT / "config/price_mapping.csv") -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len({r["ingredient_id"] for r in rows}) != len(rows):
        raise ValueError("품목 매핑 ID 중복")
    for row in rows:
        for key in KEY_FIELDS:
            if not row.get(key):
                raise ValueError(f"{row['ingredient_id']}: {key} 누락")
        number(row["unit_sz"], "unit_sz", minimum="0.000001")
        number(row["recipe_units_per_package"], "recipe_units_per_package", minimum="0.000001")
    if len({tuple(r[k] for k in KEY_FIELDS) for r in rows}) != len(rows):
        raise ValueError("동일 API 품목에 중복 매핑이 있습니다")
    return rows


def write_csv(path, rows, fields):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def parse_page(payload):
    try:
        response = payload.get("response", payload)
        header = response["header"]
        code = str(header["resultCode"])
        if code in {"20", "21", "22", "30", "31", "32", "99", "SERVICE_KEY_IS_NOT_REGISTERED_ERROR"}:
            raise AuthenticationError("API 인증/권한 오류: 키 및 활용신청 상태를 확인하세요")
        if code not in {"0", "00", "000", "0000", "NORMAL_SERVICE"}:
            raise PriceError("API가 오류 결과를 반환했습니다")
        body = response["body"]
        total = int(body["totalCount"])
        items = body.get("items") or []
        if isinstance(items, dict):
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        if total < 0 or not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
            raise ValueError
        return total, items
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PriceError("API 응답 스키마가 명세와 다릅니다") from None


def request_page(session, endpoint, key, params, *, sleep=time.sleep, retries=3):
    # Reject arbitrary hosts so a mistaken override cannot send the key elsewhere.
    if endpoint != ENDPOINT:
        raise PriceError("PRICE_API_BASE는 명세의 HTTPS 서비스 URL이어야 합니다")
    for attempt in range(retries + 1):
        try:
            response = session.get(endpoint, params={**params, "serviceKey": unquote(key)}, timeout=(10, 45), allow_redirects=False)
            if response.status_code in {401, 403}:
                raise AuthenticationError("API 인증/권한 오류")
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < retries:
                    sleep(min(2 ** attempt, 8))
                    continue
                raise PriceError("API 일시 오류: 재시도 한도 초과")
            if response.status_code != 200:
                raise PriceError(f"API HTTP 오류 ({response.status_code})")
            try:
                payload = response.json()
            except ValueError:
                raise PriceError("API가 JSON을 반환하지 않았습니다; 인증 및 서비스 상태 확인") from None
            parse_page(payload)
            # Error-free payload only; no key-bearing request metadata is persisted.
            return payload
        except (requests.Timeout, requests.ConnectionError):
            if attempt >= retries:
                raise PriceError("API 연결 실패: 재시도 한도 초과") from None
            sleep(min(2 ** attempt, 8))
        except requests.RequestException:
            raise PriceError("API 요청 실패") from None


def month_ranges(start: date, end: date):
    if start > end:
        raise ValueError("수집 시작일이 종료일보다 늦습니다")
    current = start
    while current <= end:
        last = min(end, date(current.year, current.month, calendar.monthrange(current.year, current.month)[1]))
        yield current, last
        current = date.fromordinal(last.toordinal() + 1)


def collect(mappings, *, key, raw_dir=ROOT / "data/price_raw", start=date(2026, 1, 1),
            end=date(2026, 6, 30), endpoint=ENDPOINT, session=None, sleep=time.sleep):
    if not key or key.strip().startswith("여기에"):
        raise AuthenticationError("PRICE_API_KEY를 환경변수 또는 .env에 설정하세요")
    if endpoint != ENDPOINT:
        raise PriceError("PRICE_API_BASE를 명세 URL로 수정하세요")
    session = session or requests.Session()
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    all_items, failures = [], []
    for mapping in mappings:
        for first, last in month_ranges(start, end):
            params = {"returnType": "JSON", "numOfRows": 1000,
                      "cond[exmn_ymd::GTE]": first.strftime("%Y%m%d"),
                      "cond[exmn_ymd::LTE]": last.strftime("%Y%m%d")}
            params.update({f"cond[{k}::EQ]": mapping[k] for k in KEY_FIELDS})
            # All markets are collected: local selection and national fallback happen later.
            identity = hashlib.sha256(json.dumps({"endpoint": endpoint, **params}, sort_keys=True).encode()).hexdigest()[:20]
            folder = raw_dir / first.strftime("%Y-%m") / identity
            folder.mkdir(parents=True, exist_ok=True)
            part = []
            total = None
            page = 1
            try:
                while total is None or len(part) < total:
                    cache = folder / f"{page:05}.json"
                    if cache.exists():
                        try:
                            payload = json.loads(cache.read_text(encoding="utf-8"))
                            count, items = parse_page(payload)
                        except (ValueError, PriceError):
                            payload = request_page(session, endpoint, key, {**params, "pageNo": page}, sleep=sleep)
                            count, items = parse_page(payload)
                    else:
                        payload = request_page(session, endpoint, key, {**params, "pageNo": page}, sleep=sleep)
                        count, items = parse_page(payload)
                    encoded = json.dumps(payload, ensure_ascii=False)
                    if key in encoded or unquote(key) in encoded:
                        raise PriceError("인증정보가 응답에 포함되어 저장을 중단했습니다")
                    if total is not None and total != count:
                        raise PriceError("수집 중 전체 건수가 변경됨: 해당 월 캐시를 확인하세요")
                    total = count
                    if len(part) < total and not items:
                        raise PriceError("전체 건수 도달 전 빈 페이지")
                    if items and page > 1 and items == previous:
                        raise PriceError("페이지가 반복되어 수집 중단")
                    part.extend(items)
                    previous = items
                    if len(part) > total:
                        raise PriceError("페이지 합계가 전체 건수를 초과합니다")
                    temporary = cache.with_suffix(".tmp")
                    temporary.write_text(encoded, encoding="utf-8")
                    temporary.replace(cache)
                    page += 1
                    if len(part) < total:
                        sleep(0.2)
                all_items.extend(part)
                (folder / "complete.json").write_text(json.dumps({"start": str(first), "end": str(last), "count": total}), encoding="utf-8")
                sleep(0.2)
            except AuthenticationError:
                raise
            except PriceError as exc:
                failures.append({"ingredient_id": mapping["ingredient_id"], "start": str(first), "end": str(last), "error": str(exc)})
    return all_items, failures


def normalize(items, mappings, start=date(2026, 1, 1), end=date(2026, 6, 30)):
    if start > end:
        raise ValueError("수집 시작일이 종료일보다 늦습니다")
    mapped = {tuple(m[k] for k in KEY_FIELDS): m for m in mappings}
    accepted, rejected, duplicates = {}, [], 0
    for item in items:
        identity = tuple(str(item.get(k, "")) for k in KEY_FIELDS)
        mapping = mapped.get(identity)
        if mapping is None:
            rejected.append({"reason": "unmapped_codes"})
            continue
        try:
            day = datetime.strptime(str(item["exmn_ymd"]).replace("-", ""), "%Y%m%d").date()
            if not start <= day <= end:
                raise ValueError("out_of_period")
            if item.get("unit") != mapping["unit"] or number(item["unit_sz"]) != number(mapping["unit_sz"]):
                raise ValueError("unit_mismatch")
            price = number(str(item["exmn_dd_prc"]).replace(",", ""), "price", minimum="0.000001")
            price /= number(mapping["recipe_units_per_package"], minimum="0.000001")
            region, market = str(item["sgg_cd"]), str(item["mrkt_cd"])
            if not region or not market:
                raise ValueError("missing_market")
            row = {"ingredient_id": mapping["ingredient_id"], "date": str(day),
                   **dict(zip(KEY_FIELDS, identity)), "sgg_cd": region, "mrkt_cd": market,
                   "unit": mapping["unit"], "unit_sz": mapping["unit_sz"], "recipe_unit": mapping["recipe_unit"],
                   "unit_price": float(price), "source": "공개 가격 기반 추정"}
            key = (row["ingredient_id"], row["date"], region, market)
            if key in accepted:
                if accepted[key]["unit_price"] != row["unit_price"]:
                    raise ValueError("conflicting_duplicate")
                duplicates += 1
            else:
                accepted[key] = row
        except (KeyError, ValueError, TypeError) as exc:
            reason = str(exc) if str(exc) in {"out_of_period", "unit_mismatch", "missing_market", "conflicting_duplicate"} else "invalid_price_or_fields"
            rejected.append({"ingredient_id": mapping["ingredient_id"], "reason": reason})
            if reason == "conflicting_duplicate":
                raise PriceError("동일 날짜·시장에 서로 다른 가격: 원시 응답 확인 필요") from None
    rows = sorted(accepted.values(), key=lambda r: (r["ingredient_id"], r["date"], r["sgg_cd"], r["mrkt_cd"]))
    expected = (end - start).days + 1
    quality = [{"ingredient_id": m["ingredient_id"], "expected_calendar_days": expected,
                "observed_days": len({r["date"] for r in rows if r["ingredient_id"] == m["ingredient_id"]}),
                "missing_rate": 1 - len({r["date"] for r in rows if r["ingredient_id"] == m["ingredient_id"]}) / expected}
               for m in mappings]
    return rows, {"quality": quality, "rejected": rejected, "duplicates": duplicates,
                  "note": "달력일 기준 결측률에는 휴장일 포함; 결측을 0원으로 채우지 않음"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping", default=str(ROOT / "config/price_mapping.csv"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data/price_raw")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data/out")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    try:
        mapping = read_mapping(args.mapping)
        items, failures = collect(mapping, key=os.getenv("PRICE_API_KEY"), endpoint=os.getenv("PRICE_API_BASE", ENDPOINT),
                                  start=args.start, end=args.end, raw_dir=args.raw_dir)
        rows, audit = normalize(items, mapping, args.start, args.end)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        manifest = {"start": str(args.start), "end": str(args.end), "collected_at": datetime.now(timezone.utc).isoformat(),
                    "failures": failures, **audit}
        (args.out_dir / "price_collection_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if not rows:
            raise PriceError("사용 가능한 가격 0건: 수집 감사 내역과 품목·단위 매핑을 확인하세요. 기존 가격 CSV는 유지합니다")
        # Failed runs must never replace a previously complete dataset.
        output = "price_daily.partial.csv" if failures else "price_daily.csv"
        write_csv(args.out_dir / output, rows, DAILY_FIELDS)
        write_csv(args.out_dir / "price_missingness.csv", audit["quality"], ["ingredient_id", "expected_calendar_days", "observed_days", "missing_rate"])
        print(f"{output}: {len(rows)} rows, failed partitions: {len(failures)}")
        return 1 if failures else 0
    except (PriceError, ValueError) as exc:
        print(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
