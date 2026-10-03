# 네이버 부동산 API 레퍼런스

이 프로젝트는 네이버가 공식 제공·보장하는 공개 API가 아닌 내부 웹 조회 경로를 사용한다. 로컬 기반 주소는 `https://neo.land.naver.com/api`다.

| 경로 | 용도 | 이 환경의 검증 상태 |
|---|---|---|
| `/regions/list?cortarNo=...` | 지역 목록 | 2026-10-03 HTTP200 확인 |
| `/search?keyword=...` | 지역명 조회 | 2026-10-03 개포동 조회 확인 |
| `/regions/complexes?cortarNo=...&realEstateType=APT` | 아파트 단지 | 2026-10-03 확인 |
| `/articles/complex/{complexNo}` | 단지 매물 | 2026-10-03 B2 1페이지 확인 |
| `/complexes/{complexNo}` | 단지 상세 | 이번 테스트에서 실제 응답 미검증 |
| `/articles?cortarNo=...&realEstateType=SMS:SG&tradeType=B2` | 작업실용 상가·사무실 | 2026-10-03 실제 MCP 조회 확인 |
| `/articles/{articleNo}` | 광고 상세·공개 사진 URL | 2026-10-03 실제 MCP 조회 확인 |

작업실 조건은 [별도 사양](studio-research.md)에 정의한다. 기존 `search_apartments`의 월세 거래 `price_min/max`는 보증금 기준이며 새 `search_studio_spaces.monthly_rent_lt`만 월세 상한으로 쓴다.

세션은 공개 페이지에서 제공되는 토큰을 메모리 안에서만 사용한다. 사용자 로그인 쿠키·비밀번호를 가져오거나 토큰을 파일에 저장하지 않는다. 원본의 클라이언트 헤더는 유지하며 접근 제한을 피하기 위해 바꾸지 않는다.

로컬 버전은 요청 시작 간 최소 1초 간격, 자동 재시도 없음이다. 401·403·429·리다이렉트·CAPTCHA에서는 같은 서버 실행의 후속 호출도 중단한다. 다른 호스트나 모바일 경로로 차단을 우회하는 fallback은 구현하지 않는다. 오류나 응답 구조 변경을 매물 없음으로 처리하지 않는다.
