# B: 손익 시뮬레이터와 식재료 가격 연동

점주가 판매가격·변동비·일평균 판매량을 입력하고, 기존 매장 공헌이익을 유지할 판매량을 비교한다. 필요 판매량은 달성 조건이며 판매 예측이 아니다. 공헌이익은 순이익이 아니다.

## 실행 (PowerShell, 저장소 루트)

이 작업에서 계약 버전 Python 3.13.2 환경은 `.venv/contract`에 별도로 준비했다. 현재 워크스페이스에서는 다음으로 실행한다.

```powershell
.venv/contract/Scripts/python -m src.screen2
```

다른 PC에서는 계약 버전 Python 3.13.2로 가상환경을 만들고 설치한다. 아래 `.venv/Scripts/python` 명령은 가상환경 경로에 맞게 바꾼다.

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-b.txt
.venv/Scripts/python -m src.screen2
```

브라우저에서 `http://127.0.0.1:8765`를 연다. 화면 입력은 서버에 저장하지 않으며 화면에서 외부 가격 API를 호출하지 않는다. `다시 계산` 또는 입력 변경으로 재계산한다. 서버 종료는 Ctrl+C.

화면은 B 담당 컴포넌트의 통합 확인용이다. C의 라우터·레이아웃은 수정하지 않았다.

```powershell
.venv/Scripts/python -m src.simulator --output out/simulator_korean_demo.json
.venv/Scripts/python -m src.simulator --store config/demo_store_western.yaml --output out/simulator_western_demo.json
.venv/Scripts/python -m src.price_scenario --allow-assumptions
.venv/Scripts/python -m pytest tests/test_simulator.py tests/test_price_pipeline.py tests/test_screen2.py -q
```

`--allow-assumptions`는 미수집 상태에서도 레시피의 가정 단가로 CSV를 생성하는 명시적 옵션이다. 이것을 실제 가격 수집 결과로 해석하지 않는다. 두 데모 매장의 가격·원가·판매량·레시피는 모두 가정값이며 공개 메뉴 가격의 확인된 인용값이 아니다. 설정 파일의 출처·태그를 변경하지 않은 채 관측값으로 발표하면 안 된다.

## C에게 넘기는 인터페이스

- `required_volume(base_cm, unit_cm, setup_cost=0) -> int | None`: 계약 유지. 공헌이익 0 이하는 `None`, 그 외에는 올림하며 필요량 하한은 0.
- `Menu`, `Alternative`, `simulate(...) -> list[dict]`: UI 없는 계산 API. 원가 낮음·기준·높음 3행을 반환한다. 데이터 구조는 dataclass 필드를 기준으로 한다.
- `recipe_costs(...)`: 메뉴별 `food_costs`, 재료별 `details`, 메뉴별 `coverage` 반환. `food_costs`를 `simulate(..., scenario_food_costs=...)`에 전달한다.
- `evaluate_inputs(form, context=...)`: 화면 폼 딕셔너리를 검증하고 설정·계산·가격 감사 결과를 반환한다. 출력의 금액은 원, 판매량은 평가기간 전체 수량, 증가율은 %, 입력 비율은 0~1이다.
- `render_screen2(form, context=..., action=...)`: C의 페이지에 넣을 HTML 조각. CSS/스크립트는 `#screen2` 내부를 대상으로 한다. `action`은 같은 출처의 GET/POST 경로로 연결하고, POST는 HTML 응답에 `#simulator-results`를 포함해야 한다. JS를 쓰지 않아도 폼 제출로 동작한다.
- `application`: 프레임워크에 마운트할 수 있는 WSGI 앱. `format=json` 요청은 계산 결과 JSON을 반환한다. 상태 저장이나 파일 변경은 하지 않는다. localhost 실행 서버는 배포용이 아니다.
- `context`는 C가 선택한 지역·업종·후보·집단 비중을 표시할 선택 정보다. 엔진의 수요나 판매량 입력으로 사용하지 않는다. C는 선택 업종을 `buz`에 넘긴다. 실제 C 화면과의 최종 통합은 C 화면 코드가 제공된 뒤 검증해야 한다.

## 계산 의미

- 기본 4주, 24영업일은 가정이다. 점주가 실제 영업일을 입력한다. 기간 총 판매량 = 일평균 판매량 × 영업일. 도입비용은 이 기간의 총액이며 매일 중복 차감하지 않는다.
- 건당 변동비 = 식재료비 + 포장비 + 판매가격 × 수수료율 + 변동 노동비. 대안 적용 판매에는 추가 노동비를 더한다. 추가 조리시간과 노동비는 별도 입력이다.
- 혜택은 적용 비율에 따라 변경 전/후 건당 공헌이익을 가중평균한다. 할인에 따라 수수료도 재계산한다.
- 매장 기준 공헌이익은 변경 전 3메뉴 합계로 고정한다. 가격 시나리오는 변경 후 식재료비에만 적용한다. 레시피 입력 방식 선택 시 변경 후 식재료비 전체를 대체하므로, 변경 전 원가와 실제 레시피가 맞는지는 점주가 확인해야 한다.
- 잠식률은 다른 메뉴의 기간 기존 판매량 감소 비율이다. 대상 메뉴 자신의 잠식률 입력은 사용하지 않는다. `ceil((기존 매장 공헌이익 + 도입비용 - 다른 메뉴의 변경 후 공헌이익) / 대상 메뉴의 변경 후 건당 공헌이익)`으로 대상 필요량을 구한다.
- 대상 메뉴 기존 판매량이 0이면 필요량은 계산하지만 증가율은 표시하지 않는다. 한 메뉴라도 판매량이 미상이라면 대상 메뉴 지수 100 계산으로 전환하며 매장 금액·도입비용·잠식은 제외한다.
- 수요 증가를 가정해 넣지 않는다. 업종 이름 때문에 한쪽이 더 불리하도록 수식을 변경하지 않는다. 도입비용 회수 차이는 입력 공헌이익·판매량에 따른다.

## 가격 수집

기존 `.env`가 있으면 덮어쓰지 말고 값만 확인한다. 없다면:

```powershell
Copy-Item .env.example .env
# 편집기에서 PRICE_API_KEY 입력. 채팅/코드/로그에 키를 넣지 않는다.
.venv/Scripts/python -m src.collect_price
.venv/Scripts/python -m src.price_scenario
```

서비스 주소는 로컬 API 명세의 `https://apis.data.go.kr/B552845/perDay/price`다. 예전 `.env`에 odcloud 주소가 있으면 수정해야 한다. URL override는 이 주소만 허용한다. 환경변수 설정이 `.env`보다 우선한다.

- 2026-01-01~06-30, 품목별·월별로 1,000건씩 수집. 429/서버 오류/연결 오류는 최대 3회 재시도, 인증 오류는 즉시 중단한다. 로그·예외에 URL과 키를 포함하지 않는다.
- 원시 응답은 `data/price_raw/<월>/<조건 해시>/`에 보존한다. 재실행은 유효한 저장 페이지를 재사용한다. 실패한 월의 일부 데이터는 정상 데이터로 합치지 않는다.
- 실패 구간이 있으면 `price_daily.partial.csv`와 실패 매니페스트를 남기고 종료코드 1. 기존 `price_daily.csv`를 덮어쓰지 않는다. 완전 수집은 `price_daily.csv`, `price_missingness.csv`, `price_collection_manifest.json`을 생성한다.
- 시장·품종·등급·단위가 바뀐 시계열을 이어 붙이지 않는다. `price_mapping.csv`의 단위·포장 크기는 엄격한 수집 필터다. 코드 조합은 제공 엑셀로 검증했지만 실제 포장 단위와 해당 중도매 가격 존재 여부는 첫 실수집에서 확인해야 한다. 불일치는 감사 내역에 남기며 자동으로 추측해 환산하지 않는다.
- 지역코드와 시장코드가 있으면 해당 시장을 사용한다. 지역만 있으면 관측일 수가 가장 많은 시장 하나를 고정하고, 동률은 코드순이다. 해당 지역·시장 자료가 전혀 없으면 동일 규격 전국 시장의 날짜별 평균으로 대체한다. 전국 평균은 그 사실을 표시한다.
- 달력일 기준 결측률은 휴장일도 포함한다. 50% 초과 결측 시 관측값의 주별 평균 시계열로 바꾸어 시나리오를 계산하고 표시한다. 0원 대체·미관측일 보간을 하지 않는다.
- 기준 = 시계열 평균, 상승/하락 = 90/10분위 선형 보간. 사용자 지정은 기준 단가 × (1+입력 변동률). 단위는 레시피별 kg·개·L로 고정한다.
- 실제 매입단가가 최우선. 공개 시계열이 있으면 실제 매입단가에 공개 시계열의 상대 변동률을 적용한다. 시계열이 없으면 상승/하락을 임의 생성하지 않고 미적용 사유를 표시한다. 사용자 지정은 미지원 품목에도 적용한다.
- 커버리지의 분모는 식재료비다. 공개 가격 적용 비중과 실제 매입단가 적용 비중을 각각 제공한다. 업종 합계는 기존 메뉴 판매량으로 가중하며 판매량 미상 시 제공하지 않는다. 공개가격 비중 70% 미만은 `참고 수준`이다.
- 코드표에는 우유·수입육 코드도 있다. 계획 문서의 “코드 자체가 없다”와 실제 수집 가능 여부는 구분한다. 현재 레시피에 없는 품목은 수집하지 않는다.

CSV 산출물: `price_scenarios.csv`, `price_coverage.csv`, `price_industry_coverage.csv`, `price_recipe_details.csv`. 미수집 가상 산출물은 `미수집: 가정값`으로 명시한다. 원본·비밀키·원시 응답은 커밋 대상이 아니다.

## 검증과 남은 외부 조건

계산 테스트는 계약의 100/120/106/101/110과 0.01원, 매장 전체 손계산, 기간·잠식·원가 범위·수수료를 검증한다. API 모의 테스트는 페이징·재개·인증·재시도·단위·결측·지역 대체를 검증한다. 화면 테스트는 직접 입력·출처·가격 시나리오의 필요 판매량 반영과 HTML escaping을 검사한다.

Edge가 설치된 Windows에서는 선택적으로 실제 브라우저 검증을 실행한다. 로컬 임시 포트에서만 서버를 실행하고 테스트 후 종료한다.

```powershell
.venv/Scripts/python -m pip install -r requirements-b-browser.txt
$env:RUN_BROWSER_TESTS='1'
.venv/Scripts/python -m pytest tests/test_screen2_browser.py -q
```

전체 테스트의 기존 데이터 검증은 `data/ABP_CONTEST_DATA.csv`가 있어야 한다. B 구현 때문에 테스트를 건너뛰도록 A 파일을 수정하지 않았다.

실제 API 키가 설정되지 않은 상태의 모의 테스트는 실수집 성공을 의미하지 않는다. 실제 가격 수집, 포장단위 확인, C 화면 통합은 해당 입력/코드 제공 후 별도 완료 확인이 필요하다. Python 패치 버전과 실행 결과는 작업 완료 보고의 실제 검증 환경을 따른다; 계약 버전은 3.13.2다.

검증 결과 (2026-09-19): Python 3.13.2 / pandas 2.2.3 / numpy 2.2.5 / openpyxl 3.1.5에서 B 테스트 66개 통과(Edge 브라우저 3개 포함). 전체는 74개 통과, 기존 카드 원본 미제공으로 25개 실패했다. A 테스트나 코드를 수정하지 않았다. 요약은 `out/b_validation.json`에 기록했다.
