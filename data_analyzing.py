import pandas as pd, numpy as np
df = pd.read_csv("ABP_CONTEST_DATA.csv", dtype={'TP_BUZ_NO':str})

# 1) 규모와 밀도 — 큐브가 얼마나 비어 있나
axes = ['STRD_YYMM','CCG_NM','GENDER_CD','AGE_CD','TP_BUZ_NO']
print(len(df), {c: df[c].nunique() for c in axes})
print("충진율:", len(df) / np.prod([df[c].nunique() for c in axes]))
# 10% 밑이면 세분 셀 대부분이 결측 → 군 단위 분석은 업종 대분류로 올려야 함

# 2) CCG_NM의 정체 — 전체 계획의 분기점
# 인구 대비 소비액이 도심에서 폭증하면 '가맹점 소재지'
chk = df.groupby('CCG_NM')['amt'].sum().sort_values(ascending=False).head(20)
# 종로구·중구가 상위에 있고 인구 대비 비율이 극단적이면 가맹점 기준

# 3) 업종 코드 계층 — 앞 2자리가 중분류인가
df['GRP2'] = df['TP_BUZ_NO'].str[:2]
print(df.groupby('GRP2')['TP_BUZ_NM'].unique().head(20))
# 40xx=유통, 80xx=요식 식으로 묶이면 롤업 축 확보

# 4) 법인(X)·외국인(3) 실제 비중
print(df.groupby('GENDER_CD')['amt'].sum() / df['amt'].sum())
# X가 5% 미만이면 ③ 법인카드 주제는 표본 부족으로 폐기

# 5) 계절성 크기 — 6개월 추세를 믿어도 되는가
m = df.groupby('STRD_YYMM')['amt'].sum()
print(m / m.mean())
# 2월(설)·5월(가정의달) 편차가 10% 넘으면 시계열 추세 해석 금지

# 6) 행정구역 키 목록만 먼저 뽑아두기
region = df[['SIDO_NM','CCG_NM']].drop_duplicates().sort_values(['SIDO_NM','CCG_NM'])
print(len(region))
region.to_csv("region_keys.csv", index=False, encoding="utf-8-sig")
# 실패 건은 수작업 보정. 여기서 놓치면 지도가 구멍 납니다