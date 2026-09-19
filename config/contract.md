# 인터페이스 계약

A·B·C 세 명이 병렬로 작업하기 위한 약속이다. **1일차 시작 전 30분에 셋이 함께 확정하고, 2일차 통합 전까지 바꾸지 않는다.**

바꿔야 할 일이 생기면 혼자 고치지 말고 나머지 두 명에게 먼저 알린다.

---

## 1. 환경

| 항목 | 버전 |
| --- | --- |
| OS | Windows 11 |
| 셸 | **PowerShell** |
| Python | 3.13.2 |
| pandas | 2.2.3 |
| numpy | 2.2.5 |
| openpyxl | 3.1.5 |

셋 다 위 버전으로 맞춘다. 확인:

```powershell
python -c "import sys,pandas,numpy,openpyxl;print(sys.version.split()[0],pandas.__version__,numpy.__version__,openpyxl.__version__)"
```

**명령어는 PowerShell 기준으로 적는다.** bash 문법(`mkdir -p`, `cp`, `rm -rf`)은 동작하지 않는다.

| bash | PowerShell |
| --- | --- |
| `mkdir -p a b` | `New-Item -ItemType Directory -Force -Path a, b` |
| `cp x y` | `Copy-Item x y` |
| `rm -rf x` | `Remove-Item -Recurse -Force x` |

### 기존 EDA와의 차이 (주의)

`eda_new_results/.../run_manifest.json`의 실행 환경은 Python 3.12.7 / pandas 2.2.2 / **numpy 1.26.4**였다. 지금은 **numpy 2.x**라 메이저 버전이 다르다.

기존 EDA 산출물을 재현할 때 소수점 끝자리가 다를 수 있다. **재현이 목적이 아니라 참고가 목적**이므로 그대로 진행하되, 값이 크게 어긋나면 버전 차이를 먼저 의심한다.

---

## 2. 폴더 구조

```
src/        코드          A: load.py, diagnose.py  B: simulator.py  C: similar_region.py
config/     설정          contract.md(이 파일), rules.yaml, options.yaml, demo_store_*.yaml
tests/      테스트        B가 주로 사용
out/        산출물 CSV    A가 주로 생성, C가 소비
data/       원본 데이터   수정 금지
plan/       계획 문서
```

---

## 3. 파일 소유권

**남의 파일은 고치지 않는다.** 고쳐야 하면 담당자에게 요청한다.

| 파일 | 만드는 사람 | 읽는 사람 |
| --- | --- | --- |
| `src/load.py` | **A** | B, C |
| `src/diagnose.py` | **A** | C |
| `config/rules.yaml` | **A** | C |
| `out/codebook_v1.csv` | **A** | — |
| `out/audit_v1.csv` | **A** | — |
| `out/case_cells_v1.csv` | **A** | C |
| `out/national_baseline_v1.csv` | **A** | C |
| `out/region_group_metrics.csv` | **A** | C |
| `src/simulator.py` | **B** | C |
| `config/options.yaml` | **B** | C |
| `config/demo_store_korean.yaml` | **B** | C |
| `config/demo_store_western.yaml` | **B** | C |
| `tests/test_simulator.py` | **B** | — |
| `src/similar_region.py` | **C** | — |
| `config/region_alias.csv` | **C** | — |
| `out/population_2026m1.csv` | **C** | — |
| `out/similar_regions.csv` | **C** | — |
| 화면 껍데기 (레이아웃·공통 CSS) | **C** | B |
| 화면 2 컴포넌트 | **B** | — |

**화면 껍데기는 C가 소유한다.** C가 1일차 종료 전에 빈 껍데기를 올려두면, 2일차에 B는 자기 화면 파일만 채운다. 둘이 동시에 레이아웃을 고치면 충돌한다.

---

## 4. 함수 시그니처

**아래를 그대로 복사해 쓴다.** 이름이나 인자를 바꾸면 2일차 통합이 깨진다.

```python
# src/load.py — A 담당 (구현 완료)
def load_card(path="data/ABP_CONTEST_DATA.csv", *, validate=True) -> pd.DataFrame:
    """카드 원본을 읽어 타입을 고정하고 파생 열을 붙여 반환.

    파생 열:
      group       : '일반개인' | '외국인' | '법인'
      period      : 'A' (202601~03) | 'B' (202604~06)
      days        : 90 또는 91
      region_key  : 'SIDO_NM CCG_NM' (예: '서울특별시 중구')
    """

def aggregate(df, region=None, buz=None, group_by=None, sido=None) -> pd.DataFrame:
    """지역·업종·집단별 집계.

    buz를 생략하면 ValueError.
    region이 여러 시도에 걸친 이름이면 sido 없이는 ValueError.

    반환 열:
      amt_A/B, cnt_A/B, daily_amt_A/B, daily_cnt_A/B, unit_A/B,
      daily_amt_chg_pct, daily_cnt_chg_pct, unit_chg_pct, share_B_pct
    """

def ambiguous_ccg(df) -> dict[str, list[str]]:
    """여러 시도에 같은 이름이 있는 시군구 -> 시도 목록."""

def national_baseline(df, buz_list=None) -> pd.DataFrame:
    """업종별 전국 기준선."""

def self_check(df=None) -> bool:
    """7절 기준값과 대조. 터미널: python -m src.load"""
```

사용 예:

```python
from src.load import load_card, aggregate, BUZ_KOREAN, BUZ_WESTERN

d = load_card()
aggregate(d, region="미추홀구", buz=BUZ_KOREAN)                    # 지역 1곳
aggregate(d, region="중구", sido="서울특별시", buz=BUZ_KOREAN)      # 모호한 이름
aggregate(d, buz=BUZ_WESTERN)                                     # 전국
aggregate(d, region="이천시", buz=BUZ_WESTERN, group_by="group")   # 집단별
aggregate(d, buz=BUZ_KOREAN, group_by="region_key")               # 255개 지역 전체
```

```python
# src/diagnose.py — A 담당 (구현 완료, 2일차)
def diagnose(df, region: str, buz: str, sido=None, rules=None) -> dict:
    """화면 1이 쓰는 단일 셀 진단. 판정 + 실행 후보 + 게이트 기록.

    반환 키:
      지역, 업종, 관측량부족(bool)
      지표   : 일평균금액_변화_pct, 일평균건수_변화_pct, 건당금액_변화_pct,
               금액_초과분_pp, 건수_초과분_pp, 건당_초과분_pp, 관측건수_최소
      판정   : 방향, 원인, 라벨, 우선순위, 설명   <- 설명은 그대로 화면에 쓴다
      실행후보: [{규칙, 대상, 확인, 후보[], B기간_비중_pct,
                전국_대비_초과분_pp, ...}]  <- 비었으면 아무것도 그리지 않는다
      참고   : 우선순위 '낮음'일 때만 문자열. 후보 대신 이 한 줄만 표시한다
      게이트  : 후보가 왜 비었는지 사람이 읽을 수 있는 문자열 목록
      표시   : {footer, 주석, (대체문구)}  <- 카드에 고정 표시

    rules를 주면 config/rules.yaml 대신 그 규칙으로 계산한다 (게이트 실험용).

    **후보가 비었을 때 화면에 아무 말도 하지 않는 것이 정상이다.**
    빈 목록을 '문제 없음'으로 바꿔 쓰지 않는다. 게이트 문자열은 개발용이며
    사용자에게 그대로 노출하지 않는다.
    """

def region_cells(df, buz_list=None) -> pd.DataFrame:   # 255지역 x 업종 = 510칸
def group_cells(df, buz_list=None) -> pd.DataFrame:    # + 집단 = 1,530칸
def age_cells(df, buz_list=None) -> pd.DataFrame:      # + 연령 2~6 = 2,550칸
def load_rules(path="config/rules.yaml") -> dict
```

**`out/region_group_metrics.csv` (2,040행 = 255지역 x 2업종 x 4행) — C가 읽는다**

| 열 | 내용 |
| --- | --- |
| `region_key`, `buz`, `group` | `group`은 `전체`·`일반개인`·`외국인`·`법인`. **`전체` 행이 셀 단위 값이다** |
| `amt_A/B`, `cnt_A/B`, `daily_*`, `unit_A/B` | 원지표 |
| `daily_amt_chg_pct`, `daily_cnt_chg_pct`, `unit_chg_pct` | A→B 변화율 (%) |
| `share_B_pct` | **셀 안에서의** B기간 금액 비중. 전체 행은 100 |
| `금액기여도_pct` | `(집단 B금액 − 집단 A일평균×91) ÷ 전체 A일평균×91`. 집단 3행 합 = 전체 행의 `daily_amt_chg_pct` |
| `cnt_excess_pp`, `unit_excess_pp`, `amt_excess_pp` | 전국 대비 초과분. 집단 행은 **전국 동일 집단** 기준 |
| `n_min`, `관측량부족` | `min(cnt_A, cnt_B)`와 1,000 미달 여부 |
| `후보생성` | 우선순위·관측량 게이트 통과 여부. **화면은 이 열만 보고 후보 영역을 그린다** |
| `방향`, `원인`, `라벨`, `우선순위`, `설명` | 셀 단위 판정. 같은 셀의 집단 4행에 동일하게 반복된다 |

`out/region_age_metrics.csv` (2,550행)는 `group` 대신 `AGE_CD`(2~6)를 쓰고,
`금액기여도_pct`·판정 열 대신 **`제외비중_pct`** (코드 `1`+`x`의 B기간 금액 비중)를 담는다.
**이 값을 화면에 반드시 표시한다** (6-3절).

`관측량부족`이 참인 행은 수치를 숨기고 "관측량 부족"으로 표시한다. `라벨`이
`관측량 부족`이면 A기간 관측 자체가 없어 변화율을 낼 수 없는 칸이다.

```python
# src/simulator.py — B 담당
def required_volume(base_cm: float, unit_cm: float, setup_cost: float = 0) -> int | None:
    """필요 판매량 = 올림[(base_cm + setup_cost) / unit_cm]

    unit_cm <= 0 이면 None을 반환한다 (판매량 증가만으로 달성 불가).
    """
```

```python
# src/similar_region.py — C 담당
def find_similar(region: str, buz: str, k: int = 5) -> pd.DataFrame:
    """인구·초기 소비 기준 유사 지역 k곳과 거리를 반환. 업종별로 따로 계산한다."""
```

---

## 5. 공통 상수

`src/load.py` 상단에 정의하고, B·C는 `from src.load import ...` 로 가져다 쓴다.

```python
DAYS_A, DAYS_B = 90, 91
PERIOD_A = ["202601", "202602", "202603"]
PERIOD_B = ["202604", "202605", "202606"]

GROUP_MAP = {"1": "일반개인", "2": "일반개인", "3": "외국인", "x": "법인"}
AGE_FOR_COMPARISON = ["2", "3", "4", "5", "6"]

BUZ_KOREAN  = "8001"   # 일반한식
BUZ_WESTERN = "8006"   # 서양음식

NOISE_BAND = 0.01      # ±1%, 이 안쪽은 "변화 미미"
SHARE_GATE = 0.05      # B기간 금액 비중 5% 미만이면 실행 후보에서 제외
```

**일수로 나눈다. 월 수가 아니다.** A는 90일, B는 91일이다.

---

## 6. 데이터 규칙 (어기면 조용히 틀린다)

### 6-1. 법인은 소문자 `x`

```python
dtype = {"GENDER_CD": str, "AGE_CD": str, "TP_BUZ_NO": str}
```

대문자 `X`로 필터하면 법인 금액이 **전부 사라진다.** 그런데 합계는 그럴듯해 보여서 발견이 늦다.

**검증**: 전국 법인 금액 비중이 **6.13%** 로 나와야 한다. 0%가 나오면 대소문자 실수다.

### 6-2. 업종은 필수 그룹 키

일반한식 36,869원 대 서양음식 11,023원. 합산하면 업종 구성비 변화가 객단가 변화로 둔갑한다.

`aggregate()`에서 `buz=None`이면 `ValueError`를 던진다.

### 6-3. AGE_CD 1과 x는 연령 비교에서 제외

- `1` = 범위 미확인 (금액 0.96%)
- `x` = 법인 (연령 없음)

전체 합계에는 포함하되 연령별 비교에서는 빼고, **제외 비중을 화면에 표시한다.**

### 6-4. 1인당 소비 환산 금지

`CCG_NM`이 가맹점 소재지인지 고객 거주지인지 확인되지 않았다. 강남구 서양음식 일평균 48,792건이 강남구 주민 수로 설명되지 않는 것이 그 증거다 (사례에서는 제외했으나 255개 지역 전체를 다룰 때 남는 문제).

**1인당 환산 함수를 코드베이스에 만들지 않는다.**

### 6-6. 시군구명만으로 지역을 특정하지 않는다 ⚠️

**`CCG_NM`은 유일하지 않다.** 시군구명은 233개인데 실제 지역은 255개다.

| 시군구명 | 존재하는 시도 수 |
| --- | --- |
| 중구, 동구 | 각 **6곳** |
| 서구 | 5곳 |
| 남구, 북구 | 각 4곳 |
| 강서구, 고성군 | 각 2곳 |

`region="중구"`로 필터하면 서울·부산·대구·인천·대전·울산 6곳이 **에러 없이 합산된다.** 금액 5,207억 원이 한 덩어리로 나오는데 그럴듯해 보여서 발견이 늦다.

**지역 키는 `region_key`(= `SIDO_NM + " " + CCG_NM`)를 쓴다.** `load_card()`가 만들어 준다.

```python
# 틀림 — 6개 중구가 합쳐진다
df.groupby("CCG_NM")

# 맞음
df.groupby("region_key")
aggregate(df, region="중구", sido="서울특별시", buz=BUZ_KOREAN)
```

`aggregate()`는 모호한 이름에 `sido`가 없으면 `ValueError`를 던진다. 하지만 `groupby`를 직접 쓰면 아무도 막아주지 않는다.

**C 주의**: 유사 지역 매칭에서 인구 데이터와 붙일 때도 `region_key` 기준으로 맞춘다. `CCG_NM`으로 join하면 22개 지역이 잘못 합쳐진다.

### 6-5. 지역 수치에는 전국 기준선을 병기

| 업종 | 일평균 금액 | 일평균 건수 | 건당 금액 |
| --- | --- | --- | --- |
| 일반한식 | +8.13% | +10.09% | −1.78% |
| 서양음식 | +7.88% | +15.25% | −6.39% |

두 업종 모두 전국적으로 건당금액이 떨어졌다. 기준선 없이 보면 전국 흐름을 지역 문제로 오진한다.

---

## 7. 검증 기준값

각자 작업 결과가 아래와 맞는지 확인한다. 어긋나면 진행하지 말고 원인을 찾는다.

### 전체 자동 검증

```powershell
python -m src.load
```

아래 항목을 한 번에 대조한다. **"전부 통과"가 나와야 다음 단계로 간다.**

### A — 4셀 + 전국 (일평균금액 / 일평균건수 / 건당금액)

| 대상 | 기대값 |
| --- | --- |
| 미추홀구 일반한식 (인천) | −2.05% / +2.82% / −4.74% |
| **이천시 서양음식 (경기)** | **−1.80% / +10.47% / −11.11%** |
| 미추홀구 서양음식 | +4.92% / +13.90% / −7.89% |
| 이천시 일반한식 | +3.71% / +4.95% / −1.18% |
| 전국 일반한식 | +8.13% / +10.09% / −1.78% |
| 전국 서양음식 | +7.88% / +15.25% / −6.39% |

법인 금액 비중 전국 **6.13%**.

관측 범위: (시도,시군구) 쌍 **255**, 시군구명 **233**, 월별 지역수 모두 255.

안전장치: `aggregate(df)` → ValueError, `aggregate(df, region="중구", buz=...)` → ValueError.

분해 잔차 **1e-10 미만** (실측 2.67e-16).

### B — 시뮬레이터

```python
required_volume(600000, 6000) == 100
required_volume(600000, 5000) == 120
required_volume(600000, 5700) == 106     # 105.26 → 올림
required_volume(600000, 5999) == 101     # 올림 경계
required_volume(600000, 0)    is None
required_volume(600000, 6000, setup_cost=60000) == 110
```

### C — 지역 매칭

- 인구 데이터와 카드 데이터의 시군구 **미매칭 0건** (255개 전부)
- 강남구에서 거리 기준 "유사 지역 없음" 판정이 작동

---

## 8. 브랜치 규칙

| 담당 | 브랜치 |
| --- | --- |
| A | `feat/data-foundation` |
| B | `feat/stage4-simulator` |
| C | `feat/stage3-similar-region` |

```powershell
git checkout main
git pull origin main
git checkout -b <브랜치명>
git push -u origin <브랜치명>     # 첫 push에만 -u
```

### A의 예외 — 로더는 즉시 main에 넣는다

**C의 1일차 오후가 `src/load.py`에 걸려 있다.** A 브랜치 안에만 있으면 C가 못 쓴다.

로더를 완성하면 바로 PR을 올리고 **리뷰를 기다리지 말고 merge**한다. 나머지 집계 작업은 브랜치에서 계속하고 1일차 끝에 두 번째 PR로 합친다.

C는 merge 후 이렇게 받는다.

```powershell
git checkout main
git pull origin main
```

---

## 9. 커밋 규칙

- 작은 단위로 끊는다. 한 커밋에 여러 관심사를 섞지 않는다.
- `.env`, 원본 CSV, 참가신청서류는 **절대 커밋하지 않는다.** `.gitignore`에 등록돼 있지만 커밋 전 `git status`로 확인한다.
- 인증키를 코드나 노트북에 직접 쓰지 않는다. `.env`만 사용한다.

접두어:

| 접두어 | 용도 |
| --- | --- |
| `feat:` | 기능 추가 |
| `fix:` | 버그 수정 |
| `docs:` | 문서 |
| `chore:` | 설정·데이터·잡일 |
| `test:` | 테스트 |

---

## 10. 금지 문구

화면과 산출물에 아래 표현을 쓰지 않는다.

- "20대 소비 증가 = 가성비 선호", "중장년 증가 = 모임형 메뉴 선호" — 연령·집단 차이를 선호나 동기로 바로 해석하지 않는다
- "주민 1인당 외식비" — 6-4 참조
- 필요 판매량을 **예측**으로 표현하는 문구 — "달성 조건"이지 "이만큼 팔릴 것"이 아니다
- 공헌이익을 **순이익**처럼 쓰는 표현

필수 문구:

- "BC카드 관측 집계 기준"
- "5월 결제금액이 전국 평균 대비 약 +11%로 높음 — 계절 요인 포함"
- "필요 판매량은 달성 조건이며 판매 예측이 아니다"
- 예시 매장에 "가상 사례" 배지

---

## 11. 미해결 정의 (주최 측 확인 대상)

답변이 오면 이 문서와 `plan/00`을 함께 갱신한다.

1. `CCG_NM`이 가맹점 소재지인가 고객 거주지인가
2. `GENDER_CD=3`(외국인)의 모집단 정의
3. `AGE_CD=1`의 연령 범위
4. 파생 집계의 공유·제출 허용 범위

확인 전까지는 모든 산출물에 "BC카드 관측 집계 기준"을 표기하고 1인당 환산을 하지 않는다.
