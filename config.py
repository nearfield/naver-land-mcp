"""설정 상수: API URL, 헤더, 거래 유형, 기본값."""

import os

# 2026-07: 네이버가 new.land.naver.com(구 도메인)의 프론트엔드 페이지를 폐기하고
# neo.land.naver.com으로 이전함(API 경로 구조는 동일, 도메인만 변경).
API_BASE = "https://neo.land.naver.com/api"
MAIN_PAGE_URL = "https://neo.land.naver.com/complexes"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://neo.land.naver.com/complexes",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Rate limiting
REQUEST_DELAY_SEC = 1.0       # 기존 수집 루프 딜레이; 클라이언트도 최소 1초 보장
RETRY_DELAY_SEC = 5.0         # 원본 호환 상수. 로컬 확장에서는 자동 재시도 없음
MAX_RETRIES = 1              # 원본 호환 상수. 접근 제한은 즉시 중단
REQUEST_TIMEOUT_SEC = 10

# 스냅샷 저장 경로 (변동 감지용)
SNAPSHOT_DIR = os.path.expanduser("~/.naver-land")
SNAPSHOT_PATH = os.path.join(SNAPSHOT_DIR, "snapshot.json")

# MCP 타임아웃(60초) 에 맞춘 기본 한도.
# crawl_district 한 번에 처리할 최대 단지 수. dealCount 내림차순으로 선택.
DEFAULT_MAX_COMPLEXES = 5

# search_apartments 응답 매물 수 기본/최대치.
# 무제한 반환 시 대형 지역(개포동 2,500건+)에서 응답이 수백만 자가 되어
# MCP 클라이언트 토큰 한도를 넘기므로 반드시 상한을 둔다.
DEFAULT_SEARCH_LIMIT = 30
MAX_SEARCH_LIMIT = 100

# crawl_district 전체 수집 시간 예산(초). MCP 클라이언트 타임아웃(60초)보다
# 여유 있게 짧아야 한다 — 초과 시 그때까지 모은 부분 결과를 반환한다.
CRAWL_TIME_BUDGET_SEC = 35.0

# 가격 기본 범위 (만원 단위) — 가격 명시 안 한 호출 시 전 범위 검색
DEFAULT_PRICE_MIN = 0
DEFAULT_PRICE_MAX = 999999

TRADE_TYPES = {
    "A1": "매매",
    "B1": "전세",
    "B2": "월세",
}

# 지역코드는 네이버 검색 API (/search) 로 동적 조회 — 하드코딩 제거.
# naver_land.resolve_region() / crawl_district() 참조.
