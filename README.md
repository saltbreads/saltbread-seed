# Daegu Saltbread Places Pipeline (Naver Map Data Enrichment)

대구 지역의 “소금빵” 관련 카페/베이커리 후보 매장을 **정식 API 기반으로 수집**하고,  
네이버 지도 페이지에서 **매장 운영에 도움이 되는 공개 정보(대표사진/영업시간/메뉴 등)**를 구조화하여 CSV로 생성하는 데이터 파이프라인입니다.

> 목적: 후보 매장 리스트를 빠르게 확보하고, 메뉴/영업시간/리뷰 키워드 등 핵심 정보를 일관된 스키마로 정리하여 팀에 전달

---

## 요약

- 1) **네이버 개발자 API(검색 + 지오코드)** 로 후보 매장 seed 데이터 생성  
- 2) 매장명 기반 검색 결과에서 URL 정규식으로 **Naver Place SID 추출**
- 3) SID 기반으로 네이버 지도 페이지 접속 후,  
  - 스크롤 렌더 항목: 전화번호 / AI 브리핑 / 방문자 리뷰 키워드 / 대표사진  
  - 클릭 필요 항목: 영업시간 / 메뉴(전체 펼치기) / 메뉴 이미지 Top5  
  를 자동 수집
- 체크포인트/상태코드/재시도 가드로 **대량 처리 안정성 확보**
- 키워드 쿼리만 바꾸면 다른 지역/다른 디저트 카테고리로 확장 가능
- 키워드 쿼리 형태 { 지역명 } + { 좁은지역 키워드 } + { item 이름 } + { 추가 키워드 1,2... }  
  - { 지역명 } ( 대구, 서울 등 )
  + { 법정주소리스트, 핫플레이스 리스트( ~리단길, ~~골목 등), 지하철역 리스트 } 
  + { item 이름 } (소금빵, 두쫀쿠, 라멘, 돈까스 등)
  + { 추가 키워드 1 } ( 카페, 베이커리 등 )
  + { 추가 키워드 2 } ( 맛집, 명소, 흑백요리사 등 )

---

## Outputs

이 파이프라인은 기본적으로 두 종류의 결과 CSV를 생성합니다.

- `data/output/daegu_saltbread_places_enriched_basic.csv`
  - 대표사진, 전화번호, AI 브리핑, 리뷰 키워드, 영업시간 등 “기본 정보” 중심
- `data/output/daegu_saltbread_places_enriched_menu.csv`
  - 메뉴 탭 기반으로 메뉴명/가격/이미지 URL 전체 + 이미지 우선순위 Top5 포함  
  - (현재 구현은 **basic 컬럼도 함께 포함**되어 최종 전달용 “통합 CSV”로도 활용 가능)

> 참고: 결과 CSV에는 줄바꿈(엔터)이 포함될 수 있습니다. CSV 규칙에 따라 정상적으로 인코딩/escape 되어 저장됩니다.

---

## Pipeline Overview

### Step 1) Seed 수집 (Naver Developer API + Geocode)
- 쿼리 예시:
  - `대구 + (동/주소/핫플/지하철역 등) + 소금빵 + (카페/베이커리/맛집)`
- 네이버 개발자 API로 검색하여 **가게 이름/주소 등 기본 메타** 확보
- 지오코드 API로 **좌표(mapx/mapy, lat/lon)** 저장
- 캐시를 사용하여:
  - 동일 주소/동일 매장 중복 호출 방지
  - 지오코드 중복 처리 및 속도/안정성 개선

> 어필 포인트: “정식 API 루트” 기반으로 seed 데이터를 구성해, 데이터 수집의 정당성과 재현성을 확보

### Step 2) SID 추출 (검색 + URL 정규식)
- `대구 + {가게이름}` 으로 검색
- 결과 URL에서 정규식으로 SID(place/restaurant id) 추출

> 참고: 이 단계 이후부터는 일부 구간에서 자동화 접근이 제한(캡차 등)될 수 있어, 페이지 렌더링 기반 자동화를 사용했습니다.

### Step 3) SID 기반 Enrichment (Selenium)
SID를 순회하면서 네이버 지도 페이지에서 공개 정보를 추출합니다.

- 스크롤로 자동 렌더링되는 항목(클릭 불필요)
  - 전화번호
  - AI 브리핑
  - 방문자 리뷰 키워드(상위 N개)
  - 대표(히어로) 이미지

- 클릭 후 펼쳐서 수집되는 항목
  - 영업시간(토글 펼침 이후 상세 블록)
  - 메뉴 탭 진입 → “펼쳐서 더보기” 반복 클릭(없을 때까지)
  - 메뉴명/가격/메뉴 이미지 URL 전체
  - 우선순위 규칙에 따라 메뉴 이미지 Top5 선정

---

## Menu Image Top5 Rule

메뉴 이미지(5개)는 아래 우선순위를 적용하여 선별합니다.

1. 메뉴명이 정확히 `소금빵`
2. 메뉴명에 `소금빵` or `시오` 포함 (ex. 메론소금빵, 모카시오번)
3. 메뉴명에 `버터롤` or `소금` or `솔트` or `salt` or `butter roll` 포함
4. 메뉴명에 `빵` 포함 (상위 조건에서 소금빵 없다고 간주)
5. 위 조건으로 부족할 경우 메뉴 등록 순서대로 채움 (단, 중복 제외)

> 운영 팁: 이미지가 없는 메뉴가 있을 수 있어, “이미지 존재 여부”를 우선 고려하도록 설계할 수 있습니다.

---

## Reliability: Checkpoints & Status Codes

대량 처리 안정성을 위해 아래를 적용했습니다.

- **Checkpoint CSV 저장**
  - 실행 중간에도 안전하게 진행상황을 저장하여 중단/재시작이 가능
- **상태코드(status) 기반 분기**
  - 항목별로 `OK / NOT_FOUND / EMPTY / ERR:*` 등을 구분
  - pending 조건 + 재시도 횟수로 불필요한 반복을 줄이고, 일시적 렌더 실패는 회복 가능
- **타임아웃/스크롤/지터 sleep**
  - 렌더링 지연과 로딩 편차를 흡수

---

## Project Structure
```
.
├── scripts/
│ ├── enrich_daegu_place_basic.py
│ └── enrich_daegu_place_menu.py
├── src/
│ ├── clients/
│ │ └── selenium_naver_map.py
│ └── utils/
│ └── scroll.py
├── data/
│ ├── interim/ # checkpoints (gitignore 권장)
│ └── output/ # final csv (gitignore 권장)
├── requirements.txt
└── README.md
```


**구조 의도**
- `scripts/` : 실행 엔트리(파이프라인 orchestration)
- `src/clients/` : 외부 시스템(네이버 지도/웹드라이버) 접근 로직 모듈화
- `src/utils/` : 스크롤/대기/공통 유틸 분리
- `data/` : 산출물/중간 산출물을 코드와 분리

---

## How to Run

### 1) 환경 준비
```bash
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2) Seed 데이터 생성 (Naver Search API + Geocode)
```bash
python -m scripts.run_daegu_saltbread
```
- Input
  - data/inputs/daegu/admin_dongs.csv (optional, keyword 컬럼)
  - data/inputs/daegu/hotspots.csv (optional, keyword 컬럼)
  - data/inputs/daegu/subway_stations_raw.csv (optional, station_name_ko 컬럼)
  - item 이름, 키워드 리스트 (ex 소금빵, 휘낭시에, 라멘 등)

***이부분만 변경하면 바로 다른 아이템, 지역으로 확장 가능합니다** 

### 3) Naver Place SID 수집
```bash
python -m scripts.collect_daegu_place_ids
```


### 4) Basic Enrichment ( 대표사진, 전화번호, 영업시간, AI브리핑, 리뷰키워드 등 ) 
```bash
python -m scripts.enrich_daegu_place_basic
```

### 5) Menu Enrichment ( 메뉴명, 가격, 이미지url )
```bash
python -m scripts.enrich_daegu_place_menu
```


## Notes on Data Use & Ethics

본 프로젝트는 아래 원칙을 지향합니다.

- **Seed 데이터는 정식 API 루트(네이버 개발자 API) 기반으로 수집**합니다.
- 페이지 기반 수집(Selenium)은 매장 측이 직접 등록했거나, **노출될수록 매장 운영에 도움이 되는 공개 정보**(대표사진/영업시간/메뉴/리뷰 키워드 등) 중심으로 **구조화**합니다.
- 개인 창작물(예: 블로그 글 전문 등)처럼 **재배포/도용 이슈가 큰 콘텐츠**를 대량 수집하거나 재가공하는 용도로 사용하지 않습니다.
- 본 작업은 **학습/프로젝트 목적**이며, 특정 개인/채널의 수익화를 위한 무단 재배포 목적이 아닙니다.
- 서비스 운영 정책/로봇 배제 표준 및 관련 법령을 준수하며, 과도한 요청으로 서비스에 부담을 주지 않도록 **쿼터/딜레이/재시도 가드**를 적용합니다.

---

## Metrics (fill later)

- **Total candidates:** `{N}`
- **Basic OK rate:** `{X%}`
- **Menu OK rate:** `{Y%}`
- **Avg time / place:** `{t}s`
- **Top failure reasons:** `{...}`

