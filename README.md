## Plan A: Naver Map allSearch 기반 enrich 시도 (결과: 실패/차단)

- 목표: Naver Map 내부 API(allSearch)로 placeId(sid)를 얻고 상세 정보(영업시간/메뉴/키워드 등) enrich
- 시도:
  - allSearch endpoint: `https://map.naver.com/p/api/search/allSearch`
  - type=place, searchCoord, boundary 적용
  - header 강화 (accept-language, x-requested-with 등)
- 결과:
  - 응답에 `result.ncaptcha`가 포함되며 `confirmRules: CE_EMPTY_TOKEN` 발생
  - `result.place`가 빈 객체로 내려와 후보(place list)가 0건 → sid 매칭 불가
- 결론:
  - 내부 API 직접 호출은 자동화 방어(캡차/토큰)로 대량 수집에 부적합
  - Plan B로 전환: Selenium 기반의 “사람 행동에 가까운” 방식으로 sid 수집 + 실패 케이스 저장/재시도 설계
